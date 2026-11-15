"""Create a clean, independent studio without importing archived stories or state."""
from __future__ import annotations
import argparse
import shutil
from pathlib import Path

CODE_DIRS = ("midnight_archive", "config", "agents", "schemas", "samples", "scripts", "tests", "experiments", "licenses")
ROOT_FILES = ("README.md", "AGENTS.md", "requirements.txt", "pytest.ini", ".env.example", ".gitignore", ".gitattributes", "THIRD_PARTY_NOTICES.md")
MEDIA_DIRS = ("assets/tts", "assets/voices", "assets/fonts")
LFS_HEADER = b"version https://git-lfs.github.com/spec/v1"

def create_workspace(destination: Path, *, source: Path | None = None, skip_media: bool = False) -> Path:
    source = (source or Path(__file__).resolve().parents[1]).resolve()
    destination = destination.expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"Destination already exists; choose a new directory: {destination}")
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError("Destination must be outside the source checkout and cannot contain it.")
    for required in ("midnight_archive", "config", "agents", "schemas"):
        if not (source / required).is_dir():
            raise FileNotFoundError(f"Missing source directory: {required}")
    if not skip_media:
        for directory in MEDIA_DIRS:
            if not (source / directory).exists():
                continue
            for asset in (source / directory).rglob("*"):
                if asset.is_file() and asset.suffix.lower() in {".onnx", ".bin", ".ttf"}:
                    with asset.open("rb") as handle:
                        if handle.read(len(LFS_HEADER)) == LFS_HEADER:
                            raise ValueError(f"Unresolved Git LFS pointer: {asset.name}. Run git lfs pull first.")
    destination.mkdir(parents=True, exist_ok=False)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".env", ".env.*", ".venv")
    for directory in CODE_DIRS:
        src = source / directory
        if src.is_dir():
            shutil.copytree(src, destination / directory, ignore=ignore)
    for name in ROOT_FILES:
        if (source / name).is_file():
            shutil.copy2(source / name, destination / name)
    (destination / "docs").mkdir()
    for name in ("AGENT_START_HERE.md", "PRODUCTION_GUIDE.md", "environment-packages.json"):
        src = source / "docs" / name
        if src.is_file():
            shutil.copy2(src, destination / "docs" / name)
    if not skip_media:
        for directory in MEDIA_DIRS:
            if (source / directory).is_dir():
                shutil.copytree(source / directory, destination / directory, ignore=ignore)
    (destination / "WORKSPACE.md").write_text(
        "# New story workspace\n\n"
        "This is an independent workspace. No archived stories, database, output, credentials, "
        "virtual environment or asset registry were copied.\n\n"
        "Run scripts/setup.ps1, then read docs/AGENT_START_HERE.md. Historical example links "
        "in README.md refer to the original archive clone.\n"
        + ("\nMedia was skipped; install model/font assets before audio/rendering.\n" if skip_media else ""),
        encoding="utf-8",
    )
    return destination

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--skip-media", action="store_true", help="Create a story-writing workspace without copying voice models or fonts")
    args = parser.parse_args()
    try:
        result = create_workspace(args.destination, skip_media=args.skip_media)
    except (ValueError, OSError) as error:
        parser.exit(2, f"Workspace creation refused: {error}\n")
    print(f"Created clean workspace: {result}")
    print("Next: cd into it, run scripts/setup.ps1, then read docs/AGENT_START_HERE.md.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
