"""SQLite persistence for videos, ideas, artifacts, QC reports and jobs.

The database is the coordinator of the pipeline. It owns:

* the **status machine** (a video can only move along explicit edges),
* **duplicate prevention** (titles, premises and script content are unique),
* **artifact versions** (nothing is overwritten in place),
* **job records** with idempotency keys and bounded retries.

Timestamps are UTC ISO-8601 strings so they sort correctly.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from midnight_archive.errors import (
    DuplicateError,
    NotFoundError,
    PipelineError,
    StatusTransitionError,
    TmaError,
)
from midnight_archive.utils import premise_hash, slugify, title_key, utcnow_iso

SCHEMA_VERSION = 2

STATUSES: tuple[str, ...] = (
    "IDEA",
    "SELECTED",
    "SCRIPTED",
    "STORYBOARD_READY",
    "ASSETS_READY",
    "AUDIO_READY",
    "RENDERED",
    "QUALITY_CHECKED",
    "AWAITING_APPROVAL",
    "APPROVED",
    "PUBLISHED",
)

#: Allowed forward/backward movements. APPROVED and PUBLISHED are terminal:
#: an approved or published video is never modified again.
TRANSITIONS: dict[str, frozenset[str]] = {
    "IDEA": frozenset({"SELECTED"}),
    "SELECTED": frozenset({"SCRIPTED"}),
    "SCRIPTED": frozenset({"SELECTED", "STORYBOARD_READY"}),
    "STORYBOARD_READY": frozenset({"SCRIPTED", "ASSETS_READY"}),
    "ASSETS_READY": frozenset({"STORYBOARD_READY", "AUDIO_READY"}),
    "AUDIO_READY": frozenset({"ASSETS_READY", "RENDERED"}),
    "RENDERED": frozenset({"AUDIO_READY", "QUALITY_CHECKED"}),
    "QUALITY_CHECKED": frozenset({"RENDERED", "AWAITING_APPROVAL"}),
    "AWAITING_APPROVAL": frozenset({"APPROVED", "SCRIPTED"}),
    "APPROVED": frozenset({"PUBLISHED"}),
    "PUBLISHED": frozenset(),
}

IMMUTABLE_STATUSES = frozenset({"APPROVED", "PUBLISHED"})

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    title_key TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    status TEXT NOT NULL,
    premise TEXT,
    source_type TEXT NOT NULL DEFAULT 'original',
    source_reference TEXT,
    slug TEXT NOT NULL,
    idea_id TEXT,
    script_json TEXT,
    storyboard_json TEXT,
    script_hash TEXT UNIQUE,
    latest_qc_total REAL,
    latest_qc_verdict TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    approved_at TEXT,
    published_at TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS idea_sessions (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    provider TEXT NOT NULL,
    seed INTEGER NOT NULL,
    requested_count INTEGER NOT NULL,
    stored_count INTEGER NOT NULL DEFAULT 0,
    file_path TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ideas (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES idea_sessions(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    title_key TEXT NOT NULL,
    category TEXT NOT NULL,
    premise TEXT NOT NULL,
    premise_hash TEXT NOT NULL UNIQUE,
    hook TEXT NOT NULL,
    twist TEXT NOT NULL,
    visual_hook TEXT NOT NULL,
    scores_json TEXT NOT NULL,
    total REAL NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    video_id TEXT REFERENCES videos(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS status_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    from_status TEXT,
    to_status TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    version INTEGER NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (video_id, kind, version)
);

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    provider TEXT,
    license TEXT,
    source_url TEXT,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (video_id, path)
);

CREATE TABLE IF NOT EXISTS quality_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    reviewer TEXT NOT NULL,
    total REAL NOT NULL,
    verdict TEXT NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    url TEXT NOT NULL,
    caption TEXT,
    hashtags_json TEXT,
    published_at TEXT NOT NULL,
    UNIQUE (video_id, platform, url)
);

CREATE TABLE IF NOT EXISTS performance_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    views INTEGER NOT NULL DEFAULT 0,
    likes INTEGER NOT NULL DEFAULT 0,
    comments INTEGER NOT NULL DEFAULT 0,
    shares INTEGER NOT NULL DEFAULT 0,
    saves INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT,
    stage TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 2,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS technical_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    mp4_path TEXT NOT NULL,
    total_checks INTEGER NOT NULL,
    passed INTEGER NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_videos_status ON videos (status);
CREATE INDEX IF NOT EXISTS idx_ideas_session ON ideas (session_id);
CREATE INDEX IF NOT EXISTS idx_ideas_total ON ideas (total DESC);
CREATE INDEX IF NOT EXISTS idx_events_video ON status_events (video_id);
CREATE INDEX IF NOT EXISTS idx_stats_video ON performance_stats (video_id);
CREATE INDEX IF NOT EXISTS idx_technical_video ON technical_checks (video_id);
"""


@dataclass(frozen=True)
class JobOutcome:
    status: str  # "succeeded" or "replayed"
    attempts: int
    job_id: int
    result: Any = None


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._init_schema()

    # ------------------------------------------------------------------ plumbing
    def _init_schema(self) -> None:
        version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        self._conn.executescript(_SCHEMA_SQL)
        if version < 2:
            # Phase 2 adds licence metadata to existing installs without a rebuild.
            columns = {
                str(row[1]) for row in self._conn.execute("PRAGMA table_info(assets)")
            }
            if "commercial_use" not in columns:
                self._conn.execute(
                    "ALTER TABLE assets ADD COLUMN commercial_use INTEGER NOT NULL DEFAULT 1"
                )
            if "attribution" not in columns:
                self._conn.execute("ALTER TABLE assets ADD COLUMN attribution TEXT")
        if version < SCHEMA_VERSION:
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def sqlite_version(self) -> str:
        return str(self._conn.execute("SELECT sqlite_version()").fetchone()[0])

    def integrity_ok(self) -> bool:
        return str(self._conn.execute("PRAGMA integrity_check").fetchone()[0]) == "ok"

    # ---------------------------------------------------------------------- ideas
    def next_idea_number(self) -> int:
        row = self._conn.execute("SELECT id FROM ideas ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            return 1
        try:
            return int(str(row["id"]).split("-")[1]) + 1
        except (IndexError, ValueError):  # pragma: no cover - corrupted id
            return self._conn.execute("SELECT COUNT(*) FROM ideas").fetchone()[0] + 1

    def add_idea_session(
        self,
        session_id: str,
        label: str,
        provider: str,
        seed: int,
        requested_count: int,
        file_path: str | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO idea_sessions (id, label, provider, seed, requested_count, file_path, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, label, provider, seed, requested_count, file_path, utcnow_iso()),
        )
        self._conn.commit()

    def add_ideas(self, session_id: str, ideas: Iterable[dict[str, Any]]) -> list[str]:
        """Insert ideas, silently skipping duplicates. Returns inserted ids."""

        inserted: list[str] = []
        now = utcnow_iso()
        for idea in ideas:
            scores = idea["scores"]
            try:
                self._conn.execute(
                    "INSERT INTO ideas (id, session_id, title, title_key, category, premise,"
                    " premise_hash, hook, twist, visual_hook, scores_json, total, source, status,"
                    " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)",
                    (
                        idea["id"],
                        session_id,
                        idea["title"],
                        title_key(idea["title"]),
                        idea["category"],
                        idea["premise"],
                        idea.get("premise_hash") or premise_hash(idea["premise"]),
                        idea["hook"],
                        idea["twist"],
                        idea["visual_hook"],
                        json.dumps(scores, ensure_ascii=False),
                        float(idea["total"]),
                        idea["source"],
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                continue
            inserted.append(idea["id"])
        self._conn.execute(
            "UPDATE idea_sessions SET stored_count = (SELECT COUNT(*) FROM ideas WHERE session_id = ?)"
            " WHERE id = ?",
            (session_id, session_id),
        )
        self._conn.commit()
        return inserted

    def update_session_file(self, session_id: str, file_path: str) -> None:
        self._conn.execute(
            "UPDATE idea_sessions SET file_path = ? WHERE id = ?", (file_path, session_id)
        )
        self._conn.commit()

    def idea_exists(self, premise: str) -> bool:
        digest = premise_hash(premise)
        row = self._conn.execute("SELECT 1 FROM ideas WHERE premise_hash = ?", (digest,)).fetchone()
        return row is not None

    def list_ideas(self, limit: int = 50, session_id: str | None = None) -> list[sqlite3.Row]:
        if session_id:
            return self._conn.execute(
                "SELECT * FROM ideas WHERE session_id = ? ORDER BY total DESC, id ASC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return self._conn.execute(
            "SELECT * FROM ideas ORDER BY total DESC, id ASC LIMIT ?", (limit,)
        ).fetchall()

    def get_idea(self, idea_id: str) -> sqlite3.Row:
        row = self._conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Idea {idea_id} not found")
        return row

    def mark_idea_selected(self, idea_id: str, video_id: str) -> None:
        self._conn.execute(
            "UPDATE ideas SET status = 'selected', video_id = ? WHERE id = ?", (video_id, idea_id)
        )
        self._conn.commit()

    def list_sessions(self, limit: int = 10) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM idea_sessions ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()

    # --------------------------------------------------------------------- videos
    def next_video_id(self) -> str:
        row = self._conn.execute("SELECT id FROM videos ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            return "TMA-0001"
        try:
            number = int(str(row["id"]).split("-")[1]) + 1
        except (IndexError, ValueError):  # pragma: no cover - corrupted id
            number = self._conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0] + 1
        return f"TMA-{number:04d}"

    def create_video(
        self,
        *,
        title: str,
        category: str,
        premise: str | None = None,
        idea_id: str | None = None,
        source_type: str = "original",
        source_reference: str | None = None,
        actor: str = "cli",
        reason: str | None = None,
    ) -> sqlite3.Row:
        key = title_key(title)
        if not key:
            raise DuplicateError("Title must contain letters or digits")
        existing = self._conn.execute("SELECT id FROM videos WHERE title_key = ?", (key,)).fetchone()
        if existing is not None:
            raise DuplicateError(
                f"A video titled '{title}' already exists ({existing['id']}). "
                "Use a distinct title or continue the existing video."
            )

        video_id = self.next_video_id()
        now = utcnow_iso()
        try:
            self._conn.execute(
                "INSERT INTO videos (id, title, title_key, category, status, premise, source_type,"
                " source_reference, slug, idea_id, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, 'IDEA', ?, ?, ?, ?, ?, ?, ?)",
                (
                    video_id,
                    title,
                    key,
                    category,
                    premise,
                    source_type,
                    source_reference,
                    slugify(title),
                    idea_id,
                    now,
                    now,
                ),
            )
            self._conn.execute(
                "INSERT INTO status_events (video_id, from_status, to_status, actor, reason, created_at)"
                " VALUES (?, NULL, 'IDEA', ?, ?, ?)",
                (video_id, actor, reason or "video created", now),
            )
        except sqlite3.IntegrityError as exc:  # pragma: no cover - guarded above
            self._conn.rollback()
            raise DuplicateError(f"Could not create video: {exc}") from exc
        self._conn.commit()
        return self.require_video(video_id)

    def require_video(self, video_id: str) -> sqlite3.Row:
        row = self._conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Video {video_id} not found")
        return row

    def list_videos(self, status: str | None = None, limit: int = 50) -> list[sqlite3.Row]:
        if status:
            if status not in STATUSES:
                raise PipelineError(f"Unknown status '{status}'. Valid: {', '.join(STATUSES)}")
            return self._conn.execute(
                "SELECT * FROM videos WHERE status = ? ORDER BY id DESC LIMIT ?", (status, limit)
            ).fetchall()
        return self._conn.execute(
            "SELECT * FROM videos ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()

    def transition(
        self,
        video_id: str,
        to_status: str,
        actor: str = "cli",
        reason: str | None = None,
    ) -> sqlite3.Row:
        video = self.require_video(video_id)
        current = str(video["status"])
        if to_status not in STATUSES:
            raise StatusTransitionError(
                f"Unknown status '{to_status}'. Valid: {', '.join(STATUSES)}"
            )
        allowed = TRANSITIONS[current]
        if to_status not in allowed:
            if not allowed:
                detail = "it is final and must never be modified"
            else:
                detail = "allowed: " + ", ".join(sorted(allowed))
            raise StatusTransitionError(
                f"Cannot move {video_id} from {current} to {to_status} ({detail})"
            )

        now = utcnow_iso()
        fields = ["status = ?", "updated_at = ?"]
        params: list[Any] = [to_status, now]
        if to_status == "APPROVED":
            fields.append("approved_at = ?")
            params.append(now)
        if to_status == "PUBLISHED":
            fields.append("published_at = ?")
            params.append(now)
        params.append(video_id)
        self._conn.execute(f"UPDATE videos SET {', '.join(fields)} WHERE id = ?", params)
        self._conn.execute(
            "INSERT INTO status_events (video_id, from_status, to_status, actor, reason, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (video_id, current, to_status, actor, reason, now),
        )
        self._conn.commit()
        return self.require_video(video_id)

    def status_history(self, video_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM status_events WHERE video_id = ? ORDER BY id ASC", (video_id,)
        ).fetchall()

    def set_script(self, video_id: str, payload: dict[str, Any], digest: str) -> None:
        try:
            self._conn.execute(
                "UPDATE videos SET script_json = ?, script_hash = ?, updated_at = ? WHERE id = ?",
                (json.dumps(payload, ensure_ascii=False), digest, utcnow_iso(), video_id),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            self._conn.rollback()
            raise DuplicateError(
                "This script already exists on another video. Reusing a produced script is blocked."
            ) from exc

    def set_storyboard(self, video_id: str, payload: dict[str, Any]) -> None:
        self._conn.execute(
            "UPDATE videos SET storyboard_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(payload, ensure_ascii=False), utcnow_iso(), video_id),
        )
        self._conn.commit()

    def set_latest_qc(self, video_id: str, total: float, verdict: str) -> None:
        self._conn.execute(
            "UPDATE videos SET latest_qc_total = ?, latest_qc_verdict = ?, updated_at = ? WHERE id = ?",
            (total, verdict, utcnow_iso(), video_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------ artifacts
    def next_artifact_version(self, video_id: str, kind: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS v FROM artifacts WHERE video_id = ? AND kind = ?",
            (video_id, kind),
        ).fetchone()
        return int(row["v"]) + 1

    def add_artifact(
        self, video_id: str, kind: str, version: int, path: str, digest: str
    ) -> int:
        cursor = self._conn.execute(
            "INSERT INTO artifacts (video_id, kind, version, path, sha256, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (video_id, kind, version, path, digest, utcnow_iso()),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def list_artifacts(self, video_id: str, kind: str | None = None) -> list[sqlite3.Row]:
        if kind:
            return self._conn.execute(
                "SELECT * FROM artifacts WHERE video_id = ? AND kind = ? ORDER BY version ASC",
                (video_id, kind),
            ).fetchall()
        return self._conn.execute(
            "SELECT * FROM artifacts WHERE video_id = ? ORDER BY kind ASC, version ASC", (video_id,)
        ).fetchall()

    # ------------------------------------------------------------------- quality
    def add_quality_report(
        self, video_id: str, reviewer: str, total: float, verdict: str, payload: dict[str, Any]
    ) -> int:
        cursor = self._conn.execute(
            "INSERT INTO quality_reports (video_id, reviewer, total, verdict, report_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (video_id, reviewer, total, verdict, json.dumps(payload, ensure_ascii=False), utcnow_iso()),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    # ------------------------------------------------------------------- assets
    def add_asset(
        self,
        video_id: str,
        kind: str,
        path: str,
        sha256: str,
        *,
        provider: str | None = None,
        license_name: str | None = None,
        source_url: str | None = None,
        commercial_use: bool = True,
        attribution: str | None = None,
    ) -> None:
        self.require_video(video_id)
        self._conn.execute(
            "INSERT INTO assets (video_id, kind, path, provider, license, source_url, sha256,"
            " commercial_use, attribution, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(video_id, path) DO UPDATE SET kind=excluded.kind,"
            " provider=excluded.provider, license=excluded.license,"
            " source_url=excluded.source_url, sha256=excluded.sha256,"
            " commercial_use=excluded.commercial_use, attribution=excluded.attribution",
            (
                video_id,
                kind,
                path,
                provider,
                license_name,
                source_url,
                sha256,
                1 if commercial_use else 0,
                attribution,
                utcnow_iso(),
            ),
        )
        self._conn.commit()

    def list_assets(self, video_id: str, kind: str | None = None) -> list[sqlite3.Row]:
        if kind:
            return self._conn.execute(
                "SELECT * FROM assets WHERE video_id = ? AND kind = ? ORDER BY id ASC",
                (video_id, kind),
            ).fetchall()
        return self._conn.execute(
            "SELECT * FROM assets WHERE video_id = ? ORDER BY id ASC", (video_id,)
        ).fetchall()

    # --------------------------------------------------------------- technical QC
    def add_technical_check(
        self, video_id: str, mp4_path: str, passed: bool, total_checks: int, payload: dict[str, Any]
    ) -> int:
        cursor = self._conn.execute(
            "INSERT INTO technical_checks (video_id, mp4_path, total_checks, passed, report_json,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                video_id,
                mp4_path,
                total_checks,
                1 if passed else 0,
                json.dumps(payload, ensure_ascii=False),
                utcnow_iso(),
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def latest_technical_check(self, video_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM technical_checks WHERE video_id = ? ORDER BY id DESC LIMIT 1",
            (video_id,),
        ).fetchone()

    def latest_quality_report(self, video_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM quality_reports WHERE video_id = ? ORDER BY id DESC LIMIT 1", (video_id,)
        ).fetchone()

    def quality_reports(self, video_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM quality_reports WHERE video_id = ? ORDER BY id ASC", (video_id,)
        ).fetchall()

    # --------------------------------------------------------------- publications
    def add_publication(
        self,
        video_id: str,
        platform: str,
        url: str,
        caption: str | None = None,
        hashtags: list[str] | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO publications (video_id, platform, url, caption, hashtags_json, published_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                video_id,
                platform,
                url,
                caption,
                json.dumps(hashtags or [], ensure_ascii=False),
                utcnow_iso(),
            ),
        )
        self._conn.commit()

    def list_publications(self, video_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM publications WHERE video_id = ? ORDER BY id ASC", (video_id,)
        ).fetchall()

    # ------------------------------------------------------------------ analytics
    def add_stats(
        self,
        video_id: str,
        platform: str = "instagram",
        views: int = 0,
        likes: int = 0,
        comments: int = 0,
        shares: int = 0,
        saves: int = 0,
        notes: str | None = None,
    ) -> None:
        self.require_video(video_id)
        from midnight_archive.utils import utcnow_iso as _now

        self._conn.execute(
            "INSERT INTO performance_stats (video_id, platform, captured_at, views, likes,"
            " comments, shares, saves, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (video_id, platform, _now(), views, likes, comments, shares, saves, notes),
        )
        self._conn.commit()

    def list_stats(self, video_id: str | None = None, limit: int = 50) -> list[sqlite3.Row]:
        if video_id:
            return self._conn.execute(
                "SELECT * FROM performance_stats WHERE video_id = ? ORDER BY captured_at DESC LIMIT ?",
                (video_id, limit),
            ).fetchall()
        return self._conn.execute(
            "SELECT * FROM performance_stats ORDER BY captured_at DESC LIMIT ?", (limit,)
        ).fetchall()

    # ----------------------------------------------------------------------- jobs
    def run_job(
        self,
        stage: str,
        idempotency_key: str,
        action: Callable[[], Any],
        video_id: str | None = None,
        max_attempts: int = 2,
    ) -> JobOutcome:
        """Run ``action`` once, with bounded retries and a replay guard.

        A successful job with the same idempotency key is never executed again.
        Deterministic ``TmaError`` failures are not retried; unexpected errors
        get up to ``max_attempts`` attempts.
        """

        existing = self._conn.execute(
            "SELECT * FROM jobs WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        if existing is not None and existing["status"] == "succeeded":
            return JobOutcome("replayed", int(existing["attempts"]), int(existing["id"]))

        now = utcnow_iso()
        if existing is None:
            cursor = self._conn.execute(
                "INSERT INTO jobs (video_id, stage, idempotency_key, status, attempts, max_attempts,"
                " created_at, updated_at) VALUES (?, ?, ?, 'pending', 0, ?, ?, ?)",
                (video_id, stage, idempotency_key, max_attempts, now, now),
            )
            job_id = int(cursor.lastrowid)
            attempts = 0
        else:
            job_id = int(existing["id"])
            attempts = int(existing["attempts"])
            self._conn.execute(
                "UPDATE jobs SET status = 'pending', updated_at = ? WHERE id = ?", (now, job_id)
            )
        self._conn.commit()

        last_error: Exception | None = None
        for _ in range(max_attempts):
            attempts += 1
            started = utcnow_iso()
            self._conn.execute(
                "UPDATE jobs SET status = 'running', attempts = ?, started_at = ?, updated_at = ?,"
                " error = NULL WHERE id = ?",
                (attempts, started, started, job_id),
            )
            self._conn.commit()
            try:
                result = action()
            except TmaError as exc:
                self._fail_job(job_id, str(exc))
                raise
            except Exception as exc:  # noqa: BLE001 - recorded then retried
                last_error = exc
                self._fail_job(job_id, f"{type(exc).__name__}: {exc}")
                continue
            done = utcnow_iso()
            self._conn.execute(
                "UPDATE jobs SET status = 'succeeded', error = NULL, updated_at = ?, finished_at = ?"
                " WHERE id = ?",
                (done, done, job_id),
            )
            self._conn.commit()
            return JobOutcome("succeeded", attempts, job_id, result)

        raise PipelineError(
            f"Job '{stage}' failed after {attempts} attempt(s): {last_error}"
        ) from last_error

    def _fail_job(self, job_id: int, message: str) -> None:
        now = utcnow_iso()
        self._conn.execute(
            "UPDATE jobs SET status = 'failed', error = ?, updated_at = ?, finished_at = ? WHERE id = ?",
            (message, now, now, job_id),
        )
        self._conn.commit()

    def job(self, idempotency_key: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM jobs WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()

    def list_jobs(self, video_id: str | None = None, limit: int = 20) -> list[sqlite3.Row]:
        if video_id:
            return self._conn.execute(
                "SELECT * FROM jobs WHERE video_id = ? ORDER BY id DESC LIMIT ?", (video_id, limit)
            ).fetchall()
        return self._conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
