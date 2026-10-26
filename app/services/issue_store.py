"""Read and write issue ZIP files (YAML front-matter + Markdown body + assets)."""
import io
import json
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ISSUE_MD = "issue.md"
IMAGES_DIR = "images/"
ATTACHMENTS_DIR = "attachments/"
SIGNATURE_PATH = "signature/signature.png"

SEPARATOR = "---"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _build_frontmatter(meta: dict[str, Any]) -> str:
    return "---\n" + yaml.dump(meta, allow_unicode=True, sort_keys=False) + "---\n\n"


def _parse_issue_md(content: str) -> tuple[dict[str, Any], str]:
    """Split YAML front-matter and body from issue.md content."""
    if not content.startswith("---"):
        return {}, content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content
    meta = yaml.safe_load(parts[1]) or {}
    body = parts[2].lstrip("\n")
    return meta, body


def new_issue_meta(title: str = "New Issue", issue_type: str = "standard") -> dict[str, Any]:
    now = _now_iso()
    return {
        "id": str(uuid.uuid4()),
        "title": title,
        "type": issue_type,
        "status": "open",
        "priority": "medium",
        "tags": [],
        "due": None,
        "signed_at": None,
        "created": now,
        "modified": now,
    }


def create_issue_zip(issues_dir: Path, meta: dict[str, Any], body: str = "") -> Path:
    zip_path = issues_dir / f"issue-{meta['id']}.zip"
    content = _build_frontmatter(meta) + body
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(ISSUE_MD, content.encode("utf-8"))
    return zip_path


def read_issue(zip_path: Path) -> tuple[dict[str, Any], str]:
    with zipfile.ZipFile(zip_path, "r") as zf:
        raw = zf.read(ISSUE_MD).decode("utf-8")
    return _parse_issue_md(raw)


def write_issue(zip_path: Path, meta: dict[str, Any], body: str):
    """Update issue.md inside the ZIP, preserving all other files."""
    meta["modified"] = _now_iso()
    content = _build_frontmatter(meta) + body

    # Read existing files (images, attachments) to preserve them
    existing: dict[str, bytes] = {}
    if zip_path.exists():
        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in zf.namelist():
                if name != ISSUE_MD:
                    existing[name] = zf.read(name)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(ISSUE_MD, content.encode("utf-8"))
        for name, data in existing.items():
            zf.writestr(name, data)


def add_image(zip_path: Path, filename: str, data: bytes) -> str:
    """Add image to ZIP, return in-zip path."""
    in_zip = IMAGES_DIR + filename
    _append_to_zip(zip_path, in_zip, data)
    return in_zip


def add_attachment(zip_path: Path, filename: str, data: bytes) -> str:
    in_zip = ATTACHMENTS_DIR + filename
    _append_to_zip(zip_path, in_zip, data)
    return in_zip


def remove_attachment(zip_path: Path, filename: str):
    in_zip = ATTACHMENTS_DIR + filename
    _remove_from_zip(zip_path, in_zip)


def list_attachments(zip_path: Path) -> list[str]:
    if not zip_path.exists():
        return []
    with zipfile.ZipFile(zip_path, "r") as zf:
        return [
            Path(n).name
            for n in zf.namelist()
            if n.startswith(ATTACHMENTS_DIR) and not n.endswith("/")
        ]


def get_signature(zip_path: Path) -> bytes | None:
    try:
        return get_file_from_zip(zip_path, SIGNATURE_PATH)
    except Exception:
        return None


def save_signature(zip_path: Path, png_bytes: bytes):
    _append_to_zip(zip_path, SIGNATURE_PATH, png_bytes)


def get_file_from_zip(zip_path: Path, in_zip_path: str) -> bytes:
    with zipfile.ZipFile(zip_path, "r") as zf:
        return zf.read(in_zip_path)


def _append_to_zip(zip_path: Path, in_zip: str, data: bytes):
    existing: dict[str, bytes] = {}
    if zip_path.exists():
        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in zf.namelist():
                existing[name] = zf.read(name)
    existing[in_zip] = data
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, d in existing.items():
            zf.writestr(name, d)


def _remove_from_zip(zip_path: Path, in_zip: str):
    existing: dict[str, bytes] = {}
    if zip_path.exists():
        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in zf.namelist():
                if name != in_zip:
                    existing[name] = zf.read(name)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, d in existing.items():
            zf.writestr(name, d)
