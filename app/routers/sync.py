"""Lighthouse-mode API: receive pushes from Helm instances."""
import hashlib
import json
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from ..config import get_config
from ..db import get_db
from ..services.issue_index import upsert_issue
from ..services.issue_store import read_issue

router = APIRouter(prefix="/api/sync")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _check_auth(request: Request, db, provided_site_id: str = "") -> dict:
    """Verify Bearer token, return instance row or raise 401.

    If the instance has no site_id yet and the caller provides one,
    it is stored now — this happens on first contact from a Helm instance.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Missing token")
    token = auth.removeprefix("Bearer ").strip()
    token_hash = _hash_token(token)
    async with db.execute(
        "SELECT * FROM sync_instances WHERE token_hash = ?", (token_hash,)
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(401, "Unknown token")
    if row["revoked"]:
        raise HTTPException(401, "Token revoked")

    instance = dict(row)

    # Persist site_id on first contact, or reject mismatches
    if provided_site_id:
        if not instance["site_id"]:
            await db.execute(
                "UPDATE sync_instances SET site_id = ? WHERE site_name = ?",
                (provided_site_id, instance["site_name"]),
            )
            instance["site_id"] = provided_site_id
        elif instance["site_id"] != provided_site_id:
            raise HTTPException(403, "site_id mismatch")

    await db.execute(
        "UPDATE sync_instances SET last_seen = ? WHERE site_name = ?",
        (_now_iso(), instance["site_name"]),
    )
    await db.commit()
    return instance


# ── Instance management ───────────────────────────────────────────────────────

@router.post("/register")
async def register_instance(
    site_name: str = Form(...),
    url: str = Form(""),
    read_only: str = Form("false"),
):
    """Pre-register a Helm instance; returns a one-time token."""
    db = await get_db()
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    ro = 1 if read_only.lower() in ("true", "1", "on") else 0
    await db.execute(
        """
        INSERT INTO sync_instances (site_name, url, token_hash, created, last_seen, revoked, read_only)
        VALUES (?, ?, ?, ?, NULL, 0, ?)
        ON CONFLICT(site_name) DO UPDATE SET
            url=excluded.url, token_hash=excluded.token_hash,
            created=excluded.created, revoked=0, read_only=excluded.read_only
        """,
        (site_name, url, token_hash, _now_iso(), ro),
    )
    await db.commit()
    return {"site_name": site_name, "token": token}


@router.get("/instances")
async def list_instances():
    db = await get_db()
    async with db.execute(
        "SELECT site_name, url, created, last_seen, revoked FROM sync_instances ORDER BY created"
    ) as cur:
        rows = await cur.fetchall()
    cfg = get_config()
    result = []
    for r in rows:
        d = dict(r)
        # count issues from this instance
        async with db.execute(
            "SELECT COUNT(*) as cnt FROM issues WHERE origin_site = ?", (d["site_name"],)
        ) as cur2:
            cnt_row = await cur2.fetchone()
        d["issue_count"] = cnt_row["cnt"] if cnt_row else 0
        result.append(d)
    return result


@router.post("/instances/{site_name}/revoke")
async def revoke_instance(site_name: str):
    db = await get_db()
    await db.execute(
        "UPDATE sync_instances SET revoked = 1 WHERE site_name = ?", (site_name,)
    )
    await db.commit()
    return {"status": "revoked"}


@router.post("/instances/{site_name}/regenerate")
async def regenerate_token(site_name: str):
    db = await get_db()
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    await db.execute(
        "UPDATE sync_instances SET token_hash = ?, revoked = 0 WHERE site_name = ?",
        (token_hash, site_name),
    )
    await db.commit()
    return {"site_name": site_name, "token": token}


# ── Issue sync ────────────────────────────────────────────────────────────────

@router.post("/issues")
async def receive_issue(
    request: Request,
    zip_file: UploadFile = File(...),
    site_id: str = Form(...),
):
    """Helm pushes a ZIP; Lighthouse stores it tagged with origin_site (= site_id)."""
    db = await get_db()
    instance = await _check_auth(request, db, provided_site_id=site_id)
    if instance["site_id"] != site_id:
        raise HTTPException(403, "site_id mismatch")

    cfg = get_config()
    data = await zip_file.read()

    # Parse meta from ZIP to get origin_id
    import io, zipfile as zf_mod
    with zf_mod.ZipFile(io.BytesIO(data)) as zf:
        raw = zf.read("issue.md").decode("utf-8")
    from ..services.issue_store import _parse_issue_md
    meta, body = _parse_issue_md(raw)
    if not meta.get("id"):
        raise HTTPException(400, "Invalid issue ZIP")

    origin_id = meta["id"]
    # Assign new local UUID for Lighthouse's own issues dir
    local_id = str(uuid.uuid4())
    meta["origin_site"] = site_id
    meta["origin_id"] = origin_id
    meta["id"] = local_id

    # Check if we already have this (by origin_site + origin_id)
    async with db.execute(
        "SELECT id FROM issues WHERE origin_site = ? AND origin_id = ?",
        (site_id, origin_id),
    ) as cur:
        existing = await cur.fetchone()
    if existing:
        local_id = existing["id"]
        meta["id"] = local_id

    # Write updated ZIP with new frontmatter
    import zipfile as zf_mod, yaml as yaml_mod
    orig_files: dict[str, bytes] = {}
    with zf_mod.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            if name != "issue.md":
                orig_files[name] = zf.read(name)

    import io as io_mod
    buf = io_mod.BytesIO()
    with zf_mod.ZipFile(buf, "w", zf_mod.ZIP_DEFLATED) as zf:
        fm = "---\n" + yaml_mod.dump(meta, allow_unicode=True, sort_keys=False) + "---\n\n" + body
        zf.writestr("issue.md", fm.encode("utf-8"))
        for name, d in orig_files.items():
            zf.writestr(name, d)
    buf.seek(0)

    issues_dir = Path(cfg.issues_dir)
    zip_path = issues_dir / f"issue-{local_id}.zip"
    zip_path.write_bytes(buf.read())

    await upsert_issue(db, meta, str(zip_path))
    await db.commit()

    # Chain: forward to all upstream Lighthouses (preserving original site_name)
    if cfg.lighthouses:
        import asyncio as _asyncio
        from ..services.lighthouse_client import push_issue as _push
        _asyncio.create_task(_push(cfg, zip_path))

    return {"status": "ok", "local_id": local_id}


@router.delete("/issues/{origin_id}")
async def archive_issue(request: Request, origin_id: str, site: str = ""):
    """Helm notified that an issue was archived — archive it on Lighthouse too."""
    db = await get_db()
    instance = await _check_auth(request, db, provided_site_id=site or "")
    site_id = site or instance["site_id"]

    async with db.execute(
        "SELECT id, zip_path FROM issues WHERE origin_site = ? AND origin_id = ?",
        (site_id, origin_id),
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
    instance = await _check_auth(request, db, provided_site_id=site or "")
    # read_only instances: Lighthouse never pushes back to them
    if instance.get("read_only"):
        return []
    site_id = site or instance["site_id"]
    cfg = get_config()

    async with db.execute(
        "SELECT id, origin_id, modified, zip_path FROM issues WHERE origin_site = ? AND modified > ?",
        (site_id, since),
    ) as cur:
        rows = await cur.fetchall()

    base = cfg.notifications.base_url.rstrip("/")
    result = []
    for r in rows:
        result.append({
            # For helm-originated issues: origin_id is helm's UUID.
            # For lighthouse-created issues assigned to this site: origin_id is empty,
            # so we use the lighthouse local id as the stable identifier.
            "id": r["origin_id"] if r["origin_id"] else r["id"],
            "local_id": r["id"],
            "modified": r["modified"],
            "zip_url": f"{base}/api/sync/issues/{r['id']}/zip",
        })
    return result


@router.post("/dashboard")
async def receive_dashboard(
    request: Request,
    site_id: str = Form(...),
    content: str = Form(...),
):
    """Helm pushes its dashboard.yaml content; Lighthouse stores it as a backup."""
    db = await get_db()
    instance = await _check_auth(request, db, provided_site_id=site_id)
    if instance["site_id"] != site_id:
        raise HTTPException(403, "site_id mismatch")

    cfg = get_config()
    backup_dir = Path(cfg.dashboard_file).parent / "dashboards"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{site_id}.yaml"
    backup_path.write_text(content, encoding="utf-8")

    return {"status": "ok"}


@router.get("/dashboard/{site_id}")
async def download_dashboard_backup(site_id: str):
    """Serve a Helm instance's dashboard backup YAML (no auth — already behind Basic Auth)."""
    cfg = get_config()
    backup_path = Path(cfg.dashboard_file).parent / "dashboards" / f"{site_id}.yaml"
    if not backup_path.exists():
        raise HTTPException(404, "No dashboard backup for this instance")
    db = await get_db()
    async with db.execute(
        "SELECT site_name FROM sync_instances WHERE site_id = ?", (site_id,)
    ) as cur:
        row = await cur.fetchone()
    site_name = row["site_name"] if row else site_id
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in site_name).strip() or site_id
    return FileResponse(
        str(backup_path),
        media_type="application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="dashboard-{safe}.yaml"'},
    )


@router.get("/issues/{local_id}/zip")
async def download_issue_zip(request: Request, local_id: str):
    """Serve issue ZIP for bidirectional pull."""
    db = await get_db()
    await _check_auth(request, db)
    async with db.execute("SELECT zip_path FROM issues WHERE id = ?", (local_id,)) as cur:
        row = await cur.fetchone()
    if not row or not Path(row["zip_path"]).exists():
        raise HTTPException(404)
    return FileResponse(row["zip_path"], media_type="application/zip")
