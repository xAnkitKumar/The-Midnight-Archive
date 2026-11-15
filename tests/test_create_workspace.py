from pathlib import Path
import pytest
from scripts.create_workspace import create_workspace, LFS_HEADER

def fixture_source(tmp_path: Path) -> Path:
    src = tmp_path / "archive"
    for folder in ("midnight_archive", "config", "agents", "schemas", "docs", "scripts", "tests", "assets/tts", "assets/fonts", "output", "data"):
        (src / folder).mkdir(parents=True)
    (src / "midnight_archive/app.py").write_text("example = True\n")
    (src / "config/settings.yaml").write_text("app: example\n")
    (src / "README.md").write_text("Example\n")
    (src / ".env.example").write_text("EXAMPLE_ONLY=\n")
    (src / ".env").write_text("PRIVATE_VALUE=never-copy\n")
    (src / "data/archive.db").write_bytes(b"old database")
    (src / "output/old-story.json").write_text("{}")
    (src / "assets/manifest.json").write_text('{"old": true}')
    (src / "assets/tts/voice.bin").write_bytes(b"real model fixture")
    return src

def test_create_clean_workspace_excludes_state_and_credentials(tmp_path: Path):
    source = fixture_source(tmp_path)
    dest = create_workspace(tmp_path / "new-story", source=source)
    assert (dest / "midnight_archive/app.py").is_file()
    assert (dest / "assets/tts/voice.bin").read_bytes() == b"real model fixture"
    assert (dest / ".env.example").is_file()
    assert (dest / "WORKSPACE.md").is_file()
    for forbidden in (".env", "data", "output", "assets/manifest.json", ".git", ".venv"):
        assert not (dest / forbidden).exists()

def test_workspace_refuses_existing_destination_without_changes(tmp_path: Path):
    source = fixture_source(tmp_path)
    dest = tmp_path / "existing"; dest.mkdir()
    marker = dest / "keep.txt"; marker.write_text("keep")
    with pytest.raises(FileExistsError):
        create_workspace(dest, source=source)
    assert marker.read_text() == "keep"
    assert list(dest.iterdir()) == [marker]

def test_workspace_refuses_destination_inside_source(tmp_path: Path):
    source = fixture_source(tmp_path)
    with pytest.raises(ValueError, match="outside"):
        create_workspace(source / "nested", source=source)
    assert not (source / "nested").exists()

def test_workspace_refuses_lfs_pointer_before_creating_destination(tmp_path: Path):
    source = fixture_source(tmp_path)
    (source / "assets/tts/voice.bin").write_bytes(LFS_HEADER + b"\noid sha256:fixture\n")
    dest = tmp_path / "new-story"
    with pytest.raises(ValueError, match="Git LFS pointer"):
        create_workspace(dest, source=source)
    assert not dest.exists()

def test_story_only_workspace_can_skip_media(tmp_path: Path):
    source = fixture_source(tmp_path)
    (source / "assets/tts/voice.bin").write_bytes(LFS_HEADER + b"\n")
    dest = create_workspace(tmp_path / "story-only", source=source, skip_media=True)
    assert (dest / "midnight_archive/app.py").is_file()
    assert not (dest / "assets").exists()

def test_workspace_requires_valid_source_before_creating_destination(tmp_path: Path):
    source = tmp_path / "empty"; source.mkdir()
    dest = tmp_path / "new-story"
    with pytest.raises(FileNotFoundError):
        create_workspace(dest, source=source)
    assert not dest.exists()
