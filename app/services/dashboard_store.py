"""
Load and save the dashboard YAML file.

File format is designed to be human- and LLM-editable.
The file contains inline comments explaining every field so an LLM
can modify it without additional context.
"""
import uuid
from pathlib import Path
from typing import Any

import yaml

_HEADER = """\
# Helm DASHBOARD — Device & Stream Links
# =========================================
# This file is managed by the Helm app but can be freely edited by hand
# or by an LLM. Copy the raw text, paste into your LLM, ask it to add or
# edit entries, then paste the result back and click "Apply".
#
# ENTRY FIELDS:
#   id        — Unique ID, do not change (auto-generated UUID)
#   type      — "link"   : web link / device UI  (opens in new tab)
#               "camera" : MJPEG or HTTP snapshot stream
#                          Use the direct stream URL, e.g.
#                          http://192.168.1.50/stream.mjpg
#                          RTSP streams are NOT supported directly in the
#                          browser — use an MJPEG proxy or snapshot URL.
#               "video"  : MP4 / HTTP video stream
#               "chart"  : Embedded iframe chart (e.g. OPC2Influx embed URL)
#               "vnc"    : noVNC web client URL — opens in fullscreen overlay
#               "rdp"    : Guacamole RDP web client URL — opens in fullscreen overlay
#   name      — Display name on the tile
#   url       — Full URL (http/https)
#   icon      — Optional: URL to a custom icon/image.
#               Leave empty to auto-fetch the site favicon.
#   bg_image  — Optional: URL of a background image for the tile preview.
#               The server fetches, resizes (max 800 px wide) and caches it.
#   username  — Optional credential hint (stored in plain text)
#   password  — Optional password (stored in plain text — trusted network only)
#   remarks     — Optional free-text notes shown in the expanded detail panel
#   group       — Optional group label for visual grouping of tiles
#   chart_views — Optional named views for chart tiles, one per line: "Label|URL"
#                 Example:  "Last 1h|http://host/chart/embed/abc/?from=now-1h"
#   enabled     — true/false — disabled tiles are hidden

"""

_EXAMPLE = """\
entries:
  # Example web link — delete or replace:
  - id: 00000000-0000-0000-0000-000000000001
    type: link
    name: Router
    url: http://192.168.1.1
    icon: ""
    username: admin
    password: ""
    remarks: Main network router
    group: Network
    enabled: true

  # Example MJPEG camera — delete or replace:
  - id: 00000000-0000-0000-0000-000000000002
    type: camera
    name: Front Door
    url: https://mjpeg.sanford.io/count.mjpeg
    icon: ""
    username: ""
    password: ""
    remarks: MJPEG stream, 640x480
    group: Cameras
    enabled: true
"""


def _default_content() -> str:
    return _HEADER + _EXAMPLE


def load(path: Path) -> tuple[list[dict[str, Any]], str]:
    """Return (entries, raw_yaml_text). Creates file with examples if missing."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_default_content(), encoding="utf-8")

    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    entries = data.get("entries") or []
    # Ensure all required fields exist
    for e in entries:
        e.setdefault("id", str(uuid.uuid4()))
        e.setdefault("type", "link")
        e.setdefault("name", "Unnamed")
        e.setdefault("url", "")
        e.setdefault("icon", "")
        e.setdefault("bg_image", "")
        e.setdefault("username", "")
        e.setdefault("password", "")
        e.setdefault("remarks", "")
        e.setdefault("group", "")
        e.setdefault("chart_views", "")
        e.setdefault("enabled", True)
    return entries, raw


def save_raw(path: Path, raw: str) -> list[dict[str, Any]]:
    """Validate and save raw YAML text. Returns parsed entries."""
    data = yaml.safe_load(raw)  # raises on invalid YAML
    entries = (data or {}).get("entries") or []
    path.write_text(raw, encoding="utf-8")
    return entries


def add_entry(path: Path, entry: dict[str, Any]) -> list[dict[str, Any]]:
    entries, raw = load(path)
    entry["id"] = str(uuid.uuid4())
    entries.append(entry)
    _write_entries(path, entries)
    return entries


def update_entry(path: Path, entry_id: str, updates: dict[str, Any]) -> list[dict[str, Any]]:
    entries, _ = load(path)
    for e in entries:
        if e["id"] == entry_id:
            e.update(updates)
    _write_entries(path, entries)
    return entries


def delete_entry(path: Path, entry_id: str) -> list[dict[str, Any]]:
    entries, _ = load(path)
    entries = [e for e in entries if e["id"] != entry_id]
    _write_entries(path, entries)
    return entries


def _write_entries(path: Path, entries: list[dict]) -> None:
    body = yaml.dump({"entries": entries}, allow_unicode=True, sort_keys=False, default_flow_style=False)
    path.write_text(_HEADER + "\n" + body, encoding="utf-8")

