from __future__ import annotations

import json
from pathlib import Path

from midnight_archive.cli import main
from midnight_archive.config import Settings
from midnight_archive.database import Database

from tests.conftest import for_video


def run(project: Settings, *args: str) -> int:
    return main(["--root", str(project.root), *args])


def test_cli_ideas_json_output(project: Settings, capsys) -> None:
    code = run(project, "ideas", "--count", "5", "--seed", "42", "--json")
    output = capsys.readouterr().out
    assert code == 0
    payload = json.loads(output)
    assert payload["session_id"].startswith("IDEAS-")
    assert len(payload["stored"]) == 5
    assert payload["stored"][0]["id"] == "IDEA-0001"


def test_cli_ideas_list(project: Settings, capsys) -> None:
    assert run(project, "ideas", "--count", "3", "--seed", "1") == 0
    capsys.readouterr()
    assert run(project, "ideas", "--list", "--limit", "3") == 0
    output = capsys.readouterr().out
    assert "IDEA-0001" in output


def test_cli_select_and_import_demo(project: Settings, db: Database, demo_script: dict, demo_storyboard: dict, tmp_path: Path, capsys) -> None:
    assert run(
        project,
        "new",
        "--title",
        "The Man Who Received Tomorrow's Newspaper",
        "--category",
        "mind_bending",
        "--select",
    ) == 0
    capsys.readouterr()

    script_path = tmp_path / "script.json"
    script_path.write_text(json.dumps(for_video(demo_script, "TMA-0001")), encoding="utf-8")
    assert run(project, "import-script", "--video", "TMA-0001", "--file", str(script_path)) == 0
    capsys.readouterr()

    board_path = tmp_path / "storyboard.json"
    board_path.write_text(json.dumps(for_video(demo_storyboard, "TMA-0001")), encoding="utf-8")
    assert run(project, "import-storyboard", "--video", "TMA-0001", "--file", str(board_path)) == 0
    capsys.readouterr()

    video = db.require_video("TMA-0001")
    assert video["status"] == "STORYBOARD_READY"
    assert video["script_json"] is not None
    assert video["storyboard_json"] is not None

    assert run(project, "review", "--video", "TMA-0001", "--json") == 0
    review = json.loads(capsys.readouterr().out)
    assert review["preflight_score"] >= 80

    assert run(project, "show", "--video", "TMA-0001", "--json") == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["video"]["status"] == "STORYBOARD_READY"
    assert shown["script_metrics"]["word_count"] == 128


def test_cli_invalid_script_exits_2(project: Settings, db: Database, demo_script: dict, tmp_path: Path, capsys) -> None:
    assert run(project, "new", "--title", "Broken Draft", "--category", "mystery", "--select") == 0
    bad = for_video(demo_script, "TMA-0001")
    bad["narration"] = bad["narration"][:2]
    bad["final_line"] = bad["narration"][-1]["text"]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    assert run(project, "import-script", "--video", "TMA-0001", "--file", str(path)) == 2
    assert db.require_video("TMA-0001")["status"] == "SELECTED"


def test_cli_unknown_video_exits_1(project: Settings, capsys) -> None:
    assert run(project, "show", "--video", "TMA-9999") == 1
    assert "not found" in capsys.readouterr().out.lower()


def test_cli_select_idea_starts_a_video(project: Settings, db: Database, capsys) -> None:
    assert run(project, "ideas", "--count", "3", "--seed", "11") == 0
    capsys.readouterr()
    assert run(project, "select", "--idea", "IDEA-0001") == 0
    video = db.require_video("TMA-0001")
    assert video["status"] == "SELECTED"
    assert video["idea_id"] == "IDEA-0001"
    capsys.readouterr()
    assert run(project, "select", "--idea", "IDEA-0001") == 1
    assert "already linked" in capsys.readouterr().out.lower()
