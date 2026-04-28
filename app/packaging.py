from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import re
import struct
import zlib
import zipfile
from collections.abc import Callable
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError

from app.repositories import (
    AssetNotFoundError,
    AssetRepository,
    CharacterRepository,
    LorebookRepository,
    StoredAsset,
    StoredCharacter,
)


PACKAGE_FORMAT = "aichat.character"
PACKAGE_VERSION = 1
MANIFEST_FILENAME = "manifest.json"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_MANIFEST_KEY = "aichat_manifest"


class CharacterPackageError(ValueError):
    pass


@dataclass(frozen=True)
class CharacterPackageImportResult:
    character: StoredCharacter
    imported_lorebooks: int
    package_version: int


class _PackageCharacterSchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    description: str = Field(default="", max_length=2000)
    system_prompt: str = Field(default="", max_length=8000)
    first_message: str = Field(default="", max_length=2000)
    avatar_url: str | None = Field(default=None, max_length=2048)
    avatar_asset_path: str | None = Field(default=None, max_length=512)


class _PackageLorebookSchema(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=120)
    insert_text: str = Field(..., min_length=1, max_length=4000)
    sort_order: int = Field(default=100, ge=0, le=10000)
    enabled: bool = True


class _PackageAssetSchema(BaseModel):
    kind: str = Field(..., min_length=1, max_length=32)
    original_filename: str = Field(..., min_length=1, max_length=255)
    content_type: str = Field(..., min_length=1, max_length=255)
    stored_filename: str = Field(..., min_length=1, max_length=255)
    package_path: str = Field(..., min_length=1, max_length=512)


class _CharacterPackageSchema(BaseModel):
    format: str
    version: int = Field(..., ge=1)
    exported_at: datetime
    character: _PackageCharacterSchema
    lorebooks: list[_PackageLorebookSchema] = Field(default_factory=list)
    assets: list[_PackageAssetSchema] = Field(default_factory=list)


class CharacterPackageService:
    def __init__(
        self,
        *,
        character_repository: CharacterRepository,
        lorebook_repository: LorebookRepository,
        asset_repository: AssetRepository | None = None,
        asset_dir: Path | None = None,
    ) -> None:
        self._character_repository = character_repository
        self._lorebook_repository = lorebook_repository
        self._asset_repository = asset_repository
        self._asset_dir = asset_dir
        if self._asset_dir is not None:
            self._asset_dir.mkdir(parents=True, exist_ok=True)

    def export_character_package(self, character_id: str) -> tuple[bytes, str]:
        manifest, character_name, packaged_assets = self._build_manifest(
            character_id,
            include_assets=True,
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(MANIFEST_FILENAME, json.dumps(manifest, ensure_ascii=False, indent=2))
            for package_path, payload in packaged_assets:
                zf.writestr(package_path, payload)

        filename = f"character-{self._slugify_filename(character_name)}.aichat"
        return buffer.getvalue(), filename

    def export_character_png_package(self, character_id: str) -> tuple[bytes, str]:
        manifest, character_name, _ = self._build_manifest(
            character_id,
            include_assets=False,
        )
        manifest_json = json.dumps(manifest, ensure_ascii=True, separators=(",", ":"))
        png_bytes = self._build_png_with_text_chunk(PNG_MANIFEST_KEY, manifest_json)
        filename = f"character-{self._slugify_filename(character_name)}.png"
        return png_bytes, filename

    def import_character_package(self, package_bytes: bytes) -> CharacterPackageImportResult:
        if not package_bytes:
            raise CharacterPackageError("Package payload is empty.")
        try:
            with zipfile.ZipFile(io.BytesIO(package_bytes), mode="r") as zf:
                if MANIFEST_FILENAME not in zf.namelist():
                    raise CharacterPackageError("Invalid package: manifest.json is missing.")
                raw_manifest = zf.read(MANIFEST_FILENAME)
                try:
                    payload = json.loads(raw_manifest.decode("utf-8"))
                except UnicodeDecodeError as exc:
                    raise CharacterPackageError(
                        "Invalid package: manifest encoding must be UTF-8."
                    ) from exc
                except json.JSONDecodeError as exc:
                    raise CharacterPackageError("Invalid package: manifest JSON is malformed.") from exc
                if not isinstance(payload, dict):
                    raise CharacterPackageError(
                        "Invalid package: manifest root must be a JSON object."
                    )

                def read_asset(package_path: str) -> bytes:
                    normalized = self._normalize_package_path(package_path)
                    try:
                        return zf.read(normalized)
                    except KeyError as exc:
                        raise CharacterPackageError(
                            f"Invalid package: asset file is missing ({normalized})."
                        ) from exc

                return self._import_from_manifest(payload, read_asset_file=read_asset)
        except zipfile.BadZipFile as exc:
            raise CharacterPackageError("Invalid package: not a valid .aichat zip file.") from exc
        except OSError as exc:
            raise CharacterPackageError("Invalid package: failed to read package data.") from exc

    def import_character_png_package(self, png_bytes: bytes) -> CharacterPackageImportResult:
        if not png_bytes:
            raise CharacterPackageError("Image package payload is empty.")
        manifest_json = self._read_manifest_json_from_png(png_bytes)
        try:
            manifest = json.loads(manifest_json)
        except json.JSONDecodeError as exc:
            raise CharacterPackageError("Invalid image package: manifest JSON is malformed.") from exc
        if not isinstance(manifest, dict):
            raise CharacterPackageError("Invalid image package: manifest root must be a JSON object.")
        return self._import_from_manifest(manifest, read_asset_file=None)

    def _build_manifest(
        self,
        character_id: str,
        *,
        include_assets: bool,
    ) -> tuple[dict[str, object], str, list[tuple[str, bytes]]]:
        character = self._character_repository.get_character(character_id)
        lorebooks = self._lorebook_repository.list_lorebooks(
            character_id=character_id,
            enabled=None,
        )
        assets_manifest: list[dict[str, object]] = []
        packaged_assets: list[tuple[str, bytes]] = []

        avatar_asset_path = None
        if include_assets:
            avatar_asset = self._resolve_avatar_asset(character.avatar_url)
            if avatar_asset is not None:
                package_path = f"assets/{avatar_asset.stored_filename}"
                payload = self._read_asset_payload(avatar_asset)
                if payload is not None:
                    avatar_asset_path = package_path
                    assets_manifest.append(
                        {
                            "kind": "avatar",
                            "original_filename": avatar_asset.original_filename,
                            "content_type": avatar_asset.content_type,
                            "stored_filename": avatar_asset.stored_filename,
                            "package_path": package_path,
                        }
                    )
                    packaged_assets.append((package_path, payload))

        manifest = {
            "format": PACKAGE_FORMAT,
            "version": PACKAGE_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "character": {
                "name": character.name,
                "description": character.description,
                "system_prompt": character.system_prompt,
                "first_message": character.first_message,
                "avatar_url": character.avatar_url,
                "avatar_asset_path": avatar_asset_path,
            },
            "lorebooks": [
                {
                    "keyword": item.keyword,
                    "insert_text": item.insert_text,
                    "sort_order": item.sort_order,
                    "enabled": item.enabled,
                }
                for item in lorebooks
            ],
            "assets": assets_manifest,
        }
        return manifest, character.name, packaged_assets

    def _import_from_manifest(
        self,
        manifest: dict[str, object],
        *,
        read_asset_file: Callable[[str], bytes] | None,
    ) -> CharacterPackageImportResult:
        package = self._validate_manifest(manifest)

        if package.format != PACKAGE_FORMAT:
            raise CharacterPackageError("Unsupported package format.")
        if package.version != PACKAGE_VERSION:
            raise CharacterPackageError(
                f"Unsupported package version: {package.version}. Expected {PACKAGE_VERSION}."
            )

        avatar_url = package.character.avatar_url.strip() if package.character.avatar_url else None
        avatar_asset_path = (
            package.character.avatar_asset_path.strip()
            if package.character.avatar_asset_path
            else None
        )
        if avatar_asset_path:
            if read_asset_file is None:
                raise CharacterPackageError(
                    "Image package does not support bundled asset payloads."
                )
            imported_avatar_url = self._import_asset_from_package(
                package=package,
                package_path=avatar_asset_path,
                read_asset_file=read_asset_file,
            )
            if imported_avatar_url:
                avatar_url = imported_avatar_url

        created_character = self._character_repository.create_character(
            name=package.character.name.strip(),
            description=package.character.description.strip(),
            system_prompt=package.character.system_prompt.strip(),
            first_message=package.character.first_message.strip(),
            avatar_url=avatar_url,
        )

        imported_lorebooks = 0
        for item in package.lorebooks:
            self._lorebook_repository.create_lorebook(
                character_id=created_character.character_id,
                keyword=item.keyword.strip(),
                insert_text=item.insert_text.strip(),
                sort_order=item.sort_order,
                enabled=item.enabled,
            )
            imported_lorebooks += 1

        return CharacterPackageImportResult(
            character=created_character,
            imported_lorebooks=imported_lorebooks,
            package_version=package.version,
        )

    def _import_asset_from_package(
        self,
        *,
        package: _CharacterPackageSchema,
        package_path: str,
        read_asset_file: Callable[[str], bytes],
    ) -> str | None:
        if self._asset_repository is None or self._asset_dir is None:
            return None

        normalized_package_path = self._normalize_package_path(package_path)
        matched_asset = next(
            (item for item in package.assets if item.package_path == normalized_package_path),
            None,
        )
        if matched_asset is None:
            raise CharacterPackageError(
                f"Invalid package: avatar asset metadata is missing ({normalized_package_path})."
            )

        payload = read_asset_file(normalized_package_path)
        if not payload:
            raise CharacterPackageError(
                f"Invalid package: avatar asset file is empty ({normalized_package_path})."
            )

        suffix = Path(matched_asset.stored_filename).suffix.lower() or Path(
            matched_asset.original_filename
        ).suffix.lower()
        if not suffix:
            suffix = ".bin"

        asset_id = str(uuid4())
        stored_filename = f"{asset_id}{suffix}"
        target_path = self._asset_dir / stored_filename
        target_path.write_bytes(payload)

        try:
            self._asset_repository.create_asset(
                asset_id=asset_id,
                original_filename=matched_asset.original_filename,
                content_type=matched_asset.content_type,
                size_bytes=len(payload),
                stored_filename=stored_filename,
            )
        except Exception:
            try:
                target_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

        return f"/assets/{stored_filename}"

    def _read_manifest_json_from_png(self, png_bytes: bytes) -> str:
        if len(png_bytes) < len(PNG_SIGNATURE) or png_bytes[:8] != PNG_SIGNATURE:
            raise CharacterPackageError("Invalid image package: not a PNG file.")

        offset = 8
        payload_len = len(png_bytes)
        while offset + 12 <= payload_len:
            length = struct.unpack(">I", png_bytes[offset : offset + 4])[0]
            chunk_type = png_bytes[offset + 4 : offset + 8]
            data_start = offset + 8
            data_end = data_start + length
            crc_end = data_end + 4
            if crc_end > payload_len:
                raise CharacterPackageError("Invalid image package: PNG chunk is truncated.")

            chunk_data = png_bytes[data_start:data_end]
            if chunk_type == b"tEXt":
                sep_idx = chunk_data.find(b"\x00")
                if sep_idx > 0:
                    key = chunk_data[:sep_idx].decode("latin-1", errors="ignore")
                    value = chunk_data[sep_idx + 1 :].decode("latin-1", errors="ignore")
                    if key == PNG_MANIFEST_KEY:
                        return value
            if chunk_type == b"IEND":
                break
            offset = crc_end

        raise CharacterPackageError(
            "Invalid image package: metadata payload is missing."
        )

    @staticmethod
    def _normalize_package_path(raw_path: str) -> str:
        normalized = raw_path.replace("\\", "/").strip()
        if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
            raise CharacterPackageError("Invalid package: unsafe asset path.")
        return normalized

    def _resolve_avatar_asset(self, avatar_url: str | None) -> StoredAsset | None:
        if not avatar_url or self._asset_repository is None:
            return None
        if not avatar_url.startswith("/assets/"):
            return None
        stored_filename = avatar_url[len("/assets/") :].strip()
        if not stored_filename or "/" in stored_filename or "\\" in stored_filename:
            return None
        try:
            return self._asset_repository.get_asset_by_stored_filename(stored_filename)
        except AssetNotFoundError:
            return None

    def _read_asset_payload(self, asset: StoredAsset) -> bytes | None:
        if self._asset_dir is None:
            return None
        file_path = self._asset_dir / asset.stored_filename
        if not file_path.exists() or not file_path.is_file():
            return None
        try:
            return file_path.read_bytes()
        except OSError:
            return None

    @staticmethod
    def _build_png_with_text_chunk(keyword: str, text: str) -> bytes:
        if not keyword:
            raise CharacterPackageError("Invalid image package keyword.")

        ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
        # scanline: filter=0 + RGBA(0,0,0,0)
        idat_raw = b"\x00\x00\x00\x00\x00"
        idat_data = zlib.compress(idat_raw, level=9)
        text_data = keyword.encode("latin-1") + b"\x00" + text.encode("latin-1")

        chunks = [
            CharacterPackageService._build_png_chunk(b"IHDR", ihdr_data),
            CharacterPackageService._build_png_chunk(b"IDAT", idat_data),
            CharacterPackageService._build_png_chunk(b"tEXt", text_data),
            CharacterPackageService._build_png_chunk(b"IEND", b""),
        ]
        return PNG_SIGNATURE + b"".join(chunks)

    @staticmethod
    def _build_png_chunk(chunk_type: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return (
            struct.pack(">I", len(data))
            + chunk_type
            + data
            + struct.pack(">I", crc)
        )

    @staticmethod
    def _validate_manifest(manifest: dict[str, object]) -> _CharacterPackageSchema:
        try:
            return _CharacterPackageSchema.model_validate(manifest)
        except ValidationError as exc:
            raise CharacterPackageError(f"Invalid package manifest fields: {exc}") from exc

    @staticmethod
    def _slugify_filename(value: str) -> str:
        lowered = value.strip().lower()
        slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
        return slug or "character"
