"""Manual performance tracking.

Instagram publishing and analytics scraping are deliberately out of scope.
Stats are typed in by the owner after checking the app, and stored with a
capture timestamp so growth can be compared over time.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from midnight_archive.database import Database


@dataclass(frozen=True)
class StatsRecord:
    video_id: str
    platform: str
    captured_at: str
    views: int
    likes: int
    comments: int
    shares: int
    saves: int
    notes: str | None

    @property
    def engagement_rate(self) -> float:
        if self.views <= 0:
            return 0.0
        interactions = self.likes + self.comments + self.shares + self.saves
        return round(interactions / self.views * 100, 2)


def record_stats(
    db: Database,
    video_id: str,
    *,
    views: int = 0,
    likes: int = 0,
    comments: int = 0,
    shares: int = 0,
    saves: int = 0,
    platform: str = "instagram",
    notes: str | None = None,
) -> None:
    for name, value in (
        ("views", views),
        ("likes", likes),
        ("comments", comments),
        ("shares", shares),
        ("saves", saves),
    ):
        if value < 0:
            raise ValueError(f"{name} cannot be negative")
    db.add_stats(
        video_id,
        platform=platform,
        views=views,
        likes=likes,
        comments=comments,
        shares=shares,
        saves=saves,
        notes=notes,
    )


def latest_stats(db: Database, video_id: str | None = None, limit: int = 50) -> list[StatsRecord]:
    rows: list[sqlite3.Row] = db.list_stats(video_id, limit)
    return [
        StatsRecord(
            video_id=str(row["video_id"]),
            platform=str(row["platform"]),
            captured_at=str(row["captured_at"]),
            views=int(row["views"]),
            likes=int(row["likes"]),
            comments=int(row["comments"]),
            shares=int(row["shares"]),
            saves=int(row["saves"]),
            notes=row["notes"],
        )
        for row in rows
    ]
