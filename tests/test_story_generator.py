from __future__ import annotations

import json

import pytest

from midnight_archive.config import Settings
from midnight_archive.database import Database
from midnight_archive.errors import DuplicateError
from midnight_archive.providers import OfflineIdeaProvider
from midnight_archive.story_generator import generate_ideas, score_total, select_idea


def test_generates_fifteen_unique_scored_ideas(project: Settings, db: Database) -> None:
    result = generate_ideas(project, db, count=15, seed=1234, label="test-session")
    assert len(result.stored) == 15
    assert result.file.is_file()

    ids = [idea.id for idea in result.stored]
    assert ids == [f"IDEA-{index:04d}" for index in range(1, 16)]
    premises = {idea.premise_hash for idea in result.stored}
    assert len(premises) == 15

    categories = {idea.category for idea in result.stored}
    assert categories == {"psychological_horror", "mystery", "mind_bending"}

    for idea in result.stored:
        assert 0 <= idea.total <= 100
        assert idea.source == "local_generator"
        assert idea.scores.hook >= 1

    payload = json.loads(result.file.read_text(encoding="utf-8"))
    assert payload["provider"] == "offline"
    assert len(payload["ideas"]) == 15
    assert len(db.list_ideas()) == 15


def test_offline_provider_is_deterministic(project: Settings) -> None:
    first = OfflineIdeaProvider(project).generate(15, seed=99)
    second = OfflineIdeaProvider(project).generate(15, seed=99)
    assert [item["premise"] for item in first] == [item["premise"] for item in second]
    assert len({item["premise"] for item in first}) == 15


def test_provider_reuses_no_component_across_calls(project: Settings) -> None:
    provider = OfflineIdeaProvider(project)
    first = provider.generate(10, seed=5)
    second = provider.generate(5, seed=6)
    assert not ({item["premise"] for item in first} & {item["premise"] for item in second})
    hooks = [item["hook"] for item in first + second]
    assert len(hooks) == len(set(hooks))


def test_select_idea_creates_selected_video(project: Settings, db: Database) -> None:
    result = generate_ideas(project, db, count=3, seed=7)
    best = max(result.stored, key=lambda idea: idea.total)
    video = select_idea(db, best.id)
    assert video["status"] == "SELECTED"
    assert video["id"] == "TMA-0001"
    assert video["idea_id"] == best.id

    with pytest.raises(DuplicateError):
        select_idea(db, best.id)


def test_total_score_uses_configured_weights(project: Settings) -> None:
    scores = {"hook": 10, "originality": 10, "suspense": 10, "visual": 10, "ending": 10}
    assert score_total(scores, project) == 100.0
    zero = {key: 0 for key in scores}
    assert score_total(zero, project) == 0.0
