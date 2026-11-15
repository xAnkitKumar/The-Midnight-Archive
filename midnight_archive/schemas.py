"""Export the JSON Schemas that agents use to author handoff files."""

from __future__ import annotations

from pathlib import Path

from midnight_archive.config import Settings
from midnight_archive.models import (
    AssetManifest,
    Idea,
    IdeaSession,
    NarrationMetadata,
    QualityReport,
    RenderMetadata,
    Script,
    Storyboard,
    TechnicalReport,
)
from midnight_archive.utils import atomic_write_json

SCHEMA_MODELS = {
    "idea": Idea,
    "idea_session": IdeaSession,
    "script": Script,
    "storyboard": Storyboard,
    "quality_report": QualityReport,
    "narration_metadata": NarrationMetadata,
    "technical_report": TechnicalReport,
    "render_metadata": RenderMetadata,
    "asset_manifest": AssetManifest,
}


def export_schemas(settings: Settings) -> list[Path]:
    folder = settings.root / "schemas"
    folder.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, model in SCHEMA_MODELS.items():
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["title"] = f"The Midnight Archive {name.replace('_', ' ').title()}"
        target = folder / f"{name}.schema.json"
        atomic_write_json(target, schema)
        written.append(target)
    return written
