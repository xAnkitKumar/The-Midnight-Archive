"""Agent 1 orchestration: idea batches, scoring, persistence and selection."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from midnight_archive.config import Settings
from midnight_archive.database import Database
from midnight_archive.errors import DuplicateError, ValidationRejected
from midnight_archive.models import Idea, IdeaSession
from midnight_archive.providers import IdeaProvider, build_provider
from midnight_archive.utils import atomic_write_json, premise_hash, utcnow_iso, utcstamp

DEFAULT_WEIGHTS: dict[str, float] = {
    "hook": 0.30,
    "originality": 0.15,
    "suspense": 0.20,
    "visual": 0.20,
    "ending": 0.15,
}


@dataclass(frozen=True)
class GenerationResult:
    session_id: str
    file: Path
    stored: list[Idea]
    skipped_duplicates: int


def score_total(scores: dict[str, int], settings: Settings) -> float:
    """Weighted 0-100 score. Weights are configurable in settings.yaml."""

    configured = settings.get("ideas.score_weights")
    weights = dict(DEFAULT_WEIGHTS)
    if isinstance(configured, dict):
        for key, value in configured.items():
            if key in weights:
                weights[key] = float(value)
    total_weight = sum(weights.values()) or 1.0
    weighted = sum(float(scores.get(key, 0)) * weight for key, weight in weights.items())
    return round(weighted / total_weight * 10, 1)


def new_session_id() -> str:
    return f"IDEAS-{utcstamp()}-{secrets.token_hex(2).upper()}"


def _idea_payloads(
    provider: IdeaProvider,
    count: int,
    seed: int,
    db: Database,
    settings: Settings,
    extra_recent: Iterable[str] = (),
) -> tuple[list[dict[str, Any]], int]:
    """Ask the provider for candidates until ``count`` unique premises exist."""

    recent = [row["premise"] for row in db.list_ideas(limit=100) if row["premise"]]
    recent.extend(str(item) for item in extra_recent)
    accepted: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    skipped = 0

    for attempt in range(4):
        wanted = count - len(accepted)
        if wanted <= 0:
            break
        candidates = provider.generate(
            count=wanted + 3, seed=seed + attempt * 7919, recent_premises=recent
        )
        for candidate in candidates:
            if len(accepted) >= count:
                break
            premise = str(candidate.get("premise", "")).strip()
            if not premise:
                skipped += 1
                continue
            digest = premise_hash(premise)
            if digest in seen_hashes or db.idea_exists(premise):
                skipped += 1
                continue
            seen_hashes.add(digest)
            accepted.append(candidate)
        if not candidates:
            break

    if len(accepted) < count:
        raise ValidationRejected(
            f"Only {len(accepted)} unique ideas could be generated (requested {count}). "
            "Try a different seed or clear older ideas."
        )
    return accepted[:count], skipped


def generate_ideas(
    settings: Settings,
    db: Database,
    *,
    count: int | None = None,
    label: str | None = None,
    seed: int | None = None,
    provider_name: str | None = None,
    allow_paid: bool = False,
) -> GenerationResult:
    requested = int(count or settings.get("ideas.default_count", 15))
    if requested < 1 or requested > 50:
        raise ValidationRejected("Idea count must be between 1 and 50")
    actual_seed = int(seed if seed is not None else secrets.randbelow(1_000_000))
    provider = build_provider(settings, provider_name, allow_paid=allow_paid)

    payloads, skipped = _idea_payloads(provider, requested, actual_seed, db, settings)

    next_number = db.next_idea_number()
    created_at = utcnow_iso()
    ideas: list[Idea] = []
    for offset, payload in enumerate(payloads):
        scores = payload.get("scores") or {}
        idea_id = f"IDEA-{next_number + offset:04d}"
        ideas.append(
            Idea(
                id=idea_id,
                title=str(payload.get("title", "")).strip(),
                category=str(payload.get("category", "")).strip(),  # type: ignore[arg-type]
                premise=str(payload.get("premise", "")).strip(),
                hook=str(payload.get("hook", "")).strip(),
                twist=str(payload.get("twist", "")).strip(),
                visual_hook=str(payload.get("visual_hook", "")).strip(),
                scores=scores,
                total=score_total(scores, settings),
                source=str(payload.get("source", "local_generator")),  # type: ignore[arg-type]
                premise_hash=premise_hash(str(payload.get("premise", ""))),
                created_at=created_at,
            )
        )

    session_id = new_session_id()
    session = IdeaSession(
        id=session_id,
        label=label or provider.name,
        provider=provider.name,
        seed=actual_seed,
        created_at=created_at,
        ideas=ideas,
    )

    ideas_dir = settings.root / str(settings.get("paths.ideas", "data/ideas"))
    ideas_dir.mkdir(parents=True, exist_ok=True)
    target = ideas_dir / f"{session_id}.json"
    atomic_write_json(target, session.model_dump(mode="json"))

    db.add_idea_session(
        session_id=session_id,
        label=session.label,
        provider=provider.name,
        seed=actual_seed,
        requested_count=requested,
        file_path=settings.relative(target),
    )
    stored_ids = db.add_ideas(session_id, [idea.model_dump(mode="json") for idea in ideas])
    stored = [idea for idea in ideas if idea.id in set(stored_ids)]
    db.update_session_file(session_id, settings.relative(target))

    return GenerationResult(
        session_id=session_id,
        file=target,
        stored=stored,
        skipped_duplicates=skipped + (len(ideas) - len(stored)),
    )


def select_idea(
    db: Database,
    idea_id: str,
    title_override: str | None = None,
    actor: str = "human",
) -> Any:
    """Turn a scored idea into a video in SELECTED state."""

    idea = db.get_idea(idea_id)
    if idea["status"] == "selected":
        raise DuplicateError(
            f"{idea_id} is already linked to video {idea['video_id']}. "
            "Select a different idea."
        )
    if idea["status"] == "rejected":
        raise DuplicateError(f"{idea_id} was rejected and cannot be selected")

    video = db.create_video(
        title=(title_override or str(idea["title"])).strip(),
        category=str(idea["category"]),
        premise=str(idea["premise"]),
        idea_id=idea_id,
        actor=actor,
        reason=f"concept selected from {idea_id}",
    )
    db.mark_idea_selected(idea_id, str(video["id"]))
    return db.transition(
        str(video["id"]), "SELECTED", actor=actor, reason=f"selected idea {idea_id}"
    )


def create_concept_video(
    db: Database,
    *,
    title: str,
    category: str,
    premise: str | None = None,
    source_type: str = "original",
    source_reference: str | None = None,
    actor: str = "human",
) -> Any:
    """Create a hand-picked concept (for ideas that came from outside a batch)."""

    return db.create_video(
        title=title,
        category=category,
        premise=premise,
        source_type=source_type,
        source_reference=source_reference,
        actor=actor,
        reason="manual concept",
    )
