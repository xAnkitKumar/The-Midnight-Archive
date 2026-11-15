"""Licence-aware asset registry and placeholder asset production."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from midnight_archive.config import Settings
from midnight_archive.database import Database
from midnight_archive.errors import ConfigError, NotFoundError
from midnight_archive.licensing import require_commercial_license
from midnight_archive.models import AssetManifest, AssetManifestEntry, Storyboard, utcnow
from midnight_archive.procedural_audio import generate_score, generate_sfx_library
from midnight_archive.utils import slugify, utcnow_iso
from midnight_archive.voiceover import voice_info
from midnight_archive.visuals import generate_storyboard_stills


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class AssetManager:
    """One registry per project; each registered asset is also tied to a video."""

    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.manifest_path = self.settings.root / str(
            self.settings.get("assets.manifest", "assets/manifest.json")
        )
        self.allow_unlicensed = bool(self.settings.get("assets.allow_unlicensed", False))

    # ------------------------------------------------------------------ manifest
    def load_manifest(self) -> AssetManifest:
        if not self.manifest_path.is_file():
            return AssetManifest()
        try:
            return AssetManifest.model_validate_json(self.manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ConfigError(f"Invalid asset manifest {self.manifest_path}: {exc}") from exc

    def _save_manifest(self, manifest: AssetManifest) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.manifest_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.manifest_path)

    # ------------------------------------------------------------------ register
    def register(
        self,
        video_id: str,
        path: Path,
        kind: str,
        *,
        source: str,
        license_name: str,
        commercial_use: bool = True,
        attribution: str | None = None,
        provider: str | None = None,
    ) -> AssetManifestEntry:
        path = path.resolve()
        if not path.is_file():
            raise NotFoundError(f"Asset file not found: {path}")
        require_commercial_license(
            license_name,
            what=f"{kind} {path.name}",
            allow_unlicensed=self.allow_unlicensed,
            commercial_use=commercial_use,
        )
        digest = sha256_file(path)
        relative = self.settings.relative(path)
        asset_id = f"{kind}-{slugify(path.stem)[:36]}-{digest[:8]}"
        entry = AssetManifestEntry(
            asset_id=asset_id,
            video_id=video_id,
            kind=kind,
            path=relative,
            provider=provider,
            source=source,
            license=license_name,
            commercial_use=commercial_use,
            attribution=attribution,
            sha256=digest,
            added_at=utcnow(),
        )
        self.db.add_asset(
            video_id,
            kind,
            relative,
            digest,
            provider=provider,
            license_name=license_name,
            source_url=source,
            commercial_use=commercial_use,
            attribution=attribution,
        )
        manifest = self.load_manifest()
        manifest.assets = [item for item in manifest.assets if item.path != relative]
        manifest.assets.append(entry)
        manifest.assets.sort(key=lambda item: (item.kind, item.path))
        manifest.generated_at = utcnow()
        self._save_manifest(manifest)
        return entry

    # ------------------------------------------------------------------- library
    def ensure_font(self, video_id: str) -> Path:
        font_rel = str(
            self.settings.get("render.subtitle.font_file", "assets/fonts/Montserrat-Bold.ttf")
        )
        font = self.settings.root / font_rel
        if not font.is_file():
            raise ConfigError(
                f"Subtitle font missing: {font}. Download Montserrat (SIL OFL 1.1) into assets/fonts/."
            )
        self.register(
            video_id,
            font,
            "font",
            source="https://github.com/JulietaUla/Montserrat",
            license_name="OFL-1.1",
            attribution="Montserrat by Julieta Ulanovsky, licensed under SIL OFL 1.1",
        )
        license_file = font.parent / "Montserrat-OFL.txt"
        if license_file.is_file():
            self.register(
                video_id,
                license_file,
                "font_license",
                source="https://github.com/JulietaUla/Montserrat",
                license_name="OFL-1.1",
            )
        return font

    def ensure_voice(self, video_id: str) -> Path:
        info = voice_info(self.settings)
        self.register(
            video_id,
            info.model_path,
            "voice_model",
            source=info.source_url or f"local {info.provider} voice",
            license_name=info.license,
            attribution=info.attribution,
            provider=info.provider,
        )
        if info.voices_path is not None:
            self.register(
                video_id,
                info.voices_path,
                "voice_pack",
                source=info.source_url or f"local {info.provider} voice pack",
                license_name=info.license,
                attribution=info.attribution,
                provider=info.provider,
            )
        if info.config_path is not None and info.config_path.is_file():
            self.register(
                video_id,
                info.config_path,
                "voice_config",
                source=info.source_url or f"local {info.provider} voice",
                license_name=info.license,
                attribution=info.attribution,
                provider=info.provider,
            )
        return info.model_path

    def ensure_music(self, video_id: str, duration: float, bpm: int) -> Path:
        path = self.settings.root / "assets/music/midnight-score.wav"
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            generate_score(path, max(duration, 30.0), bpm=bpm, seed=19)
        self.register(
            video_id,
            path,
            "music",
            source="Generated locally with NumPy; no samples or third-party recordings",
            license_name="Original",
            attribution="The Midnight Archive procedural score",
            provider="procedural",
        )
        return path

    def ensure_sfx(self, video_id: str) -> dict[str, Path]:
        library = generate_sfx_library(self.settings.root / "assets/sound_effects")
        for path in library.values():
            self.register(
                video_id,
                path,
                "sfx",
                source="Generated locally with NumPy; no samples",
                license_name="Original",
                attribution="The Midnight Archive procedural sound effects",
                provider="procedural",
            )
        return library

    def ensure_stills(self, video_id: str, storyboard: Storyboard) -> list[Path]:
        real_dir = self.settings.root / "assets/backgrounds" / video_id
        expected = [real_dir / f"scene-{scene.scene:02d}.png" for scene in storyboard.scenes]
        if all(path.is_file() for path in expected):
            licences_path = real_dir / "licences.json"
            if not licences_path.is_file():
                raise ConfigError(
                    f"Real scene images exist in {real_dir}, but licences.json is missing. "
                    "Record source, licence, commercial_use and attribution for each image."
                )
            licences = json.loads(licences_path.read_text(encoding="utf-8"))
            for path in expected:
                record = licences.get(path.name)
                if not isinstance(record, dict):
                    raise ConfigError(f"No licence record for {path.name} in {licences_path}")
                self.register(
                    video_id,
                    path,
                    "image",
                    source=str(record.get("source", "")),
                    license_name=str(record.get("license", "")),
                    commercial_use=bool(record.get("commercial_use", True)),
                    attribution=record.get("attribution"),
                )
            return expected

        draft_dir = self.settings.root / "output/drafts" / video_id / "images"
        paths = generate_storyboard_stills(storyboard, self.settings, draft_dir)
        for scene, path in zip(storyboard.scenes, paths):
            self.register(
                video_id,
                path,
                "image",
                source=(
                    "Generated locally with Pillow from the storyboard scene description. "
                    f"Placeholder composition: {scene.environment}"
                ),
                license_name="Original",
                attribution="The Midnight Archive procedural placeholder still",
                provider="pillow",
            )
        return paths

    def register_narration(self, video_id: str, path: Path, voice: str) -> Path:
        info = voice_info(self.settings, voice)
        self.register(
            video_id,
            path,
            "narration",
            source=f"{info.provider} TTS, voice {voice}",
            license_name=info.license,
            attribution=info.attribution,
            provider=info.provider,
        )
        return path

    def register_mix(self, video_id: str, path: Path) -> Path:
        self.register(
            video_id,
            path,
            "audio_mix",
            source="Mixed locally from original narration, score and SFX",
            license_name="Original",
            attribution="The Midnight Archive local audio mix",
            provider="procedural",
        )
        return path

    def register_subtitles(self, video_id: str, srt: Path, ass: Path) -> None:
        self.register(
            video_id,
            srt,
            "subtitles",
            source="faster-whisper word alignment against generated narration",
            license_name="Original",
            attribution="The Midnight Archive subtitle timing",
            provider="faster-whisper",
        )
        self.register(
            video_id,
            ass,
            "subtitle_stylesheet",
            source="Generated from aligned cues and the Montserrat OFL font",
            license_name="Original",
            attribution="The Midnight Archive subtitle timing",
            provider="pillow",
        )

    def inventory(self, video_id: str) -> list[dict[str, Any]]:
        return [
            {
                "kind": row["kind"],
                "path": row["path"],
                "license": row["license"],
                "commercial_use": bool(row["commercial_use"]),
                "attribution": row["attribution"],
            }
            for row in self.db.list_assets(video_id)
        ]
