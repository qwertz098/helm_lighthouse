"""Filesystem operations for the document store."""
import shutil
import zipfile
from pathlib import Path


def _safe_path(base: Path, rel: str) -> Path:
    """Resolve rel relative to base, raise ValueError on traversal."""
    target = (base / rel).resolve()
    if not target.is_relative_to(base.resolve()):
        raise ValueError("Path traversal detected")
    return target


def list_dir(base: Path, rel: str = "") -> dict:
    target = _safe_path(base, rel)
    if not target.exists() or not target.is_dir():
        raise FileNotFoundError(f"Not a directory: {rel!r}")

    dirs = []
    files = []
    for item in sorted(target.iterdir()):
        if item.is_dir():
            dirs.append(item.name)
        else:
            files.append({"name": item.name, "size": item.stat().st_size})

    rel_path = str(target.relative_to(base.resolve())).replace("\\", "/")
    if rel_path == ".":
        rel_path = ""

    # Build breadcrumbs
    crumbs = [{"name": "Files", "path": ""}]
    parts = rel_path.split("/") if rel_path else []
    for i, part in enumerate(parts):
        crumbs.append({"name": part, "path": "/".join(parts[: i + 1])})

    return {
        "path": rel_path,
        "dirs": dirs,
        "files": files,
        "breadcrumbs": crumbs,
    }


def save_file(base: Path, rel_dir: str, filename: str, data: bytes):
    target_dir = _safe_path(base, rel_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = _safe_path(base, f"{rel_dir}/{filename}" if rel_dir else filename)
    dest.write_bytes(data)


def extract_zip(base: Path, rel_dir: str, zip_data: bytes):
    target_dir = _safe_path(base, rel_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    import io
    with zipfile.ZipFile(io.BytesIO(zip_data), "r") as zf:
        for member in zf.infolist():
            # Security: skip absolute paths and traversal
            member_path = Path(member.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                continue
            dest = target_dir / member_path
            if member.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(member.filename))


def get_file(base: Path, rel: str) -> tuple[bytes, str]:
    target = _safe_path(base, rel)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(rel)
    suffix = target.suffix.lower()
    mime_map = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".md": "text/markdown; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
    }
    mime = mime_map.get(suffix, "application/octet-stream")
    return target.read_bytes(), mime


def delete_path(base: Path, rel: str):
    target = _safe_path(base, rel)
    if target == base.resolve():
        raise ValueError("Refusing to delete the document root")
    if not target.exists():
        raise FileNotFoundError(rel)
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()


def create_folder(base: Path, rel_dir: str, name: str):
    new_dir = _safe_path(base, f"{rel_dir}/{name}" if rel_dir else name)
    new_dir.mkdir(parents=True, exist_ok=True)
