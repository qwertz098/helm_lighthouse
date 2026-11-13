"""Download remote images, downscale, and cache them on disk.

Used for dashboard link-tile background images: the user supplies a URL,
we fetch it once, shrink it to a sane size, and serve the local copy.
Pictures uploaded for a tile are stored the same way (see save_upload).
"""
import hashlib
import io
import re
import ssl
import time
import urllib.request
import uuid
from pathlib import Path

from PIL import Image

MAX_WIDTH = 800          # downscale anything wider than this
MAX_BYTES = 8 * 1024 * 1024   # refuse to download more than 8 MB
JPEG_QUALITY = 80
PREVIEW_MIN = 96         # smaller images (favicons) make no preview; the tile shows its area icon
PREVIEW_CANVAS = (480, 270)   # same shape as the tile's preview area


def _cache_dir() -> Path:
    from ..config import get_config
    d = get_config().dashboard_file.parent / "tile_bg"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]


def cached_path_for(url: str) -> Path:
    return _cache_dir() / f"{_key(url)}.jpg"


def _preview_path(url: str) -> Path:
    # own key space: previews made by older versions (cropped logos) are not reused
    return _cache_dir() / f"{_key('preview2:' + url)}.png"


UPLOAD_PREFIX = "/dashboard/bg/"     # bg_image value of an uploaded picture
_UPLOAD_NAME = re.compile(r"^[0-9a-f]{32}\.jpg$")


def _uploads_dir() -> Path:
    from ..config import get_config
    d = get_config().dashboard_file.parent / "tile_uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _to_jpeg(img: Image.Image, background=(255, 255, 255)) -> Image.Image:
    """Flatten transparency / palette onto a solid colour."""
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, background)
        rgba = img.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    return img.convert("RGB")


def save_upload(data: bytes) -> str:
    """Store an uploaded tile background (downscaled JPEG); returns its bg_image value.

    Raises ValueError for files that are too big or not an image.
    """
    if len(data) > MAX_BYTES:
        raise ValueError("Bild ist größer als 8 MB")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        raise ValueError("Datei ist kein Bild")
    img = _to_jpeg(img)
    if img.width > MAX_WIDTH:
        img = img.resize((MAX_WIDTH, round(img.height * MAX_WIDTH / img.width)), Image.LANCZOS)
    name = f"{uuid.uuid4().hex}.jpg"
    img.save(_uploads_dir() / name, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return UPLOAD_PREFIX + name


def upload_path(name: str) -> Path | None:
    """Path of an uploaded picture, or None for anything that is not one of ours."""
    p = _uploads_dir() / name
    return p if _UPLOAD_NAME.match(name) and p.is_file() else None


def delete_upload(bg_image: str) -> None:
    """Remove the file behind an uploaded bg_image value; other values are ignored."""
    if (bg_image or "").startswith(UPLOAD_PREFIX):
        if p := upload_path(bg_image[len(UPLOAD_PREFIX):]):
            p.unlink(missing_ok=True)


def get_or_fetch(url: str) -> Path | None:
    """Return the local cached (resized) copy of a tile background image, downloading if needed."""
    # urllib would also open file:// and ftp:// URLs
    if not url or not url.lower().startswith(("http://", "https://")):
        return None
    dest = cached_path_for(url)
    if dest.exists():
        return dest
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Helm/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = resp.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            return None
        img = Image.open(io.BytesIO(data))
        img.load()
        img = _to_jpeg(img)
        if img.width > MAX_WIDTH:
            img = img.resize((MAX_WIDTH, round(img.height * MAX_WIDTH / img.width)), Image.LANCZOS)
        img.save(dest, "JPEG", quality=JPEG_QUALITY, optimize=True)
        return dest
    except Exception:
        return None


def get_preview(url: str) -> Path | None:
    """Automatic link-tile preview from a device image, cached for a day.

    Devices often use self-signed certificates. A screenshot-like picture (landscape,
    at least 400 px wide) fills the tile; anything else is a logo or icon and is
    fitted whole onto a transparent canvas, so nothing is cropped and the tile's own
    colour shows around it. Images under PREVIEW_MIN px make no preview.
    """
    if not url or not url.lower().startswith(("http://", "https://")):
        return None
    dest = _preview_path(url)
    if dest.exists() and time.time() - dest.stat().st_mtime < 24 * 3600:
        return dest
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Helm/1.0"})
        with urllib.request.urlopen(req, timeout=8, context=ssl._create_unverified_context()) as resp:
            data = resp.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            return None
        img = Image.open(io.BytesIO(data))
        img.load()
        if img.width < PREVIEW_MIN or img.height < PREVIEW_MIN // 2:
            return None
        img = img.convert("RGBA")
        cw, ch = PREVIEW_CANVAS
        if img.width >= 400 and 1.5 <= img.width / img.height <= 2.2:
            img = img.resize((cw, round(img.height * cw / img.width)), Image.LANCZOS)
        else:
            # logo: fit inside the canvas with a margin, never enlarge more than 2x
            scale = min((cw - 80) / img.width, (ch - 70) / img.height, 2.0)
            logo = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
            img = Image.new("RGBA", PREVIEW_CANVAS, (0, 0, 0, 0))
            img.paste(logo, ((cw - logo.width) // 2, (ch - logo.height) // 2), logo)
        img.save(dest, "PNG", optimize=True)
        return dest
    except Exception:
        return None


def invalidate(url: str) -> None:
    try:
        p = cached_path_for(url)
        if p.exists():
            p.unlink()
    except Exception:
        pass
