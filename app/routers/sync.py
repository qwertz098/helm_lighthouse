"""Lighthouse-mode API: receive pushes from Helm instances.

Every endpoint here requires a per-instance Bearer token. Instance management
(register / revoke / regenerate / dashboard backup download) lives in the
settings router, which is behind Basic Auth.
"""
import asyncio
import hashlib
import io
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from ..config import get_config
from ..db import get_db
from ..services.issue_index import upsert_issue
from ..services.issue_store import ISSUE_MD, _build_frontmatter, _parse_issue_md, is_safe_id

router = APIRouter(prefix="/api/sync")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def dashboard_backup_path(site_id: str) -> Path:
    return Path(get_config().dashboard_file).parent / "dashboards" / f"{site_id}.yaml"


async def _check_auth(request: Request, db, provided_site_id: str = "") -> dict:
    """Verify Bearer token, return instance row or raise 401.

    If the instance has no site_id yet and the caller provides one,
    it is stored now — this happens on first contact from a Helm instance.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Missing token")
    token = auth.removeprefix("Bearer ").strip()
    async with db.execute(
        "SELECT * FROM sync_instances WHERE token_hash = ?", (hash_token(token),)
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(401, "Unknown token")
    if row["revoked"]:
        raise HTTPException(401, "Token revoked")

    instance = dict(row)

    if provided_site_id:
        # site_id ends up in file names — never accept anything path-like
        if not is_safe_id(provided_site_id):
            raise HTTPException(400, "Invalid site_id")
        if not instance["site_id"]:
            await db.execute(
                "UPDATE sync_instances SET site_id = ? WHERE site_name = ?",
                (provided_site_id, instance["site_name"]),
            )
            instance["site_id"] = provided_site_id
        elif instance["site_id"] != provided_site_id:
            raise HTTPException(403, "site_id mismatch")

    if not instance["site_id"]:
        raise HTTPException(403, "Instance has no site_id yet")

    await db.execute(
        "UPDATE sync_instances SET last_seen = ? WHERE site_name = ?",
        (_now_iso(), instance["site_name"]),
    )
    await db.commit()
    return instance


# ── Issue sync ────────────────────────────────────────────────────────────────

@router.post("/issues")
async def receive_issue(
    request: Request,
    zip_file: UploadFile = File(...),
    site_id: str = Form(...),
):
    """Helm pushes a ZIP; Lighthouse stores it tagged with origin_site (= site_id)."""
    db = await get_db()
    await _check_auth(request, db, provided_site_id=site_id)

    cfg = get_config()
    data = await zip_file.read()

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            meta, body = _parse_issue_md(zf.read(ISSUE_MD).decode("utf-8"))
            other_files = {n: zf.read(n) for n in zf.namelist() if n != ISSUE_MD}
    except (zipfile.BadZipFile, KeyError, UnicodeDecodeError):
        raise HTTPException(400, "Invalid issue ZIP")

    origin_id = str(meta.get("id") or "")
    if not is_safe_id(origin_id):
        raise HTTPException(400, "Invalid issue ZIP")

    # Match by origin id, or — for issues created here and pulled by the Helm —
    # by our own local id (those rows have no origin_id).
    async with db.execute(
        """SELECT id FROM issues WHERE origin_site = ?
           AND (origin_id = ? OR (COALESCE(origin_id, '') = '' AND id = ?))""",
        (site_id, origin_id, origin_id),
    ) as cur:
        existing = await cur.fetchone()
    local_id = existing["id"] if existing else str(uuid.uuid4())

    meta["origin_site"] = site_id
    meta["origin_id"] = origin_id
    meta["id"] = local_id

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(ISSUE_MD, (_build_frontmatter(meta) + body).encode("utf-8"))
        for name, d in other_files.items():
            zf.writestr(name, d)

    zip_path = Path(cfg.issues_dir) / f"issue-{local_id}.zip"
    zip_path.write_bytes(buf.getvalue())

    await upsert_issue(db, meta, str(zip_path))
    await db.commit()

    # Chain: forward to all upstream Lighthouses
    if cfg.lighthouses:
        from ..services.lighthouse_client import push_issue
        asyncio.create_task(push_issue(cfg, zip_path))

    return {"status": "ok", "local_id": local_id}


@router.delete("/issues/{origin_id}")
async def archive_issue(request: Request, origin_id: str, site: str = ""):
    """Helm notified that an issue was archived — archive it on Lighthouse too."""
    db = await get_db()
    instance = await _check_auth(request, db, provided_site_id=site)

    async with db.execute(
        """SELECT id, zip_path FROM issues WHERE origin_site = ?
           AND (origin_id = ? OR (COALESCE(origin_id, '') = '' AND id = ?))""",
        (instance["site_id"], origin_id, origin_id),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return {"status": "not_found"}

    zip_path = Path(row["zip_path"])
    if zip_path.exists():
        archive_dir = zip_path.parent / "archive"
        archive_dir.mkdir(exist_ok=True)
        zip_path.rename(archive_dir / zip_path.name)

    await db.execute("DELETE FROM issues WHERE id = ?", (row["id"],))
    await db.commit()
    return {"status": "archived"}


@router.get("/issues")
async def get_changed_issues(request: Request, site: str = "", since: str = "1970-01-01T00:00:00+00:00"):
    """Return issues (from this site) changed since timestamp — for bidirectional pull."""
    db = await get_db()
    instance = await _check_auth(request, db, provided_site_id=site)
    # read_only instances: Lighthouse never pushes back to them
    if instance.get("read_only"):
        return []

    async with db.execute(
        "SELECT id, origin_id, modified FROM issues WHERE origin_site = ? AND modified > ?",
        (instance["site_id"], since),
    ) as cur:
        rows = await cur.fetchall()

    return [
        {
            # Helm-originated: origin_id is Helm's UUID. Lighthouse-created issues
            # assigned to this site have no origin_id, so our local id is used.
            "id": r["origin_id"] or r["id"],
            "local_id": r["id"],
            "modified": r["modified"],
        }
        for r in rows
    ]


@router.get("/issues/{local_id}/zip")
async def download_issue_zip(request: Request, local_id: str):
    """Serve issue ZIP for bidirectional pull — only to the site that owns it."""
    db = await get_db()
    instance = await _check_auth(request, db)
    if instance.get("read_only"):
        raise HTTPException(403, "Read-only instance")
    async with db.execute(
        "SELECT zip_path FROM issues WHERE id = ? AND origin_site = ?",
        (local_id, instance["site_id"]),
    ) as cur:
        row = await cur.fetchone()
    if not row or not Path(row["zip_path"]).exists():
        raise HTTPException(404)
    return FileResponse(row["zip_path"], media_type="application/zip")


@router.post("/dashboard")
async def receive_dashboard(
    request: Request,
    site_id: str = Form(...),
    content: str = Form(...),
):
    """Helm pushes its dashboard.yaml content; Lighthouse stores it as a backup."""
    db = await get_db()
    instance = await _check_auth(request, db, provided_site_id=site_id)
    path = dashboard_backup_path(instance["site_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"status": "ok"}
