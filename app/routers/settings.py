from ..templates import templates
import os
from pathlib import Path

import yaml
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from ..config import get_config, load_config
from ..db import get_db
from ..services.issue_index import sync_index

router = APIRouter(prefix="/settings")


def _cfg_path() -> Path:
    return Path(os.environ.get("APP_CONFIG", "config.yaml"))


def _save(data: dict) -> None:
    path = _cfg_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False), encoding="utf-8")
    os.replace(tmp, path)
    load_config()  # reload singleton


def _current_yaml() -> dict:
    path = _cfg_path()
    if path.exists():
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {}


@router.post("/sync", response_class=HTMLResponse)
async def manual_sync(request: Request):
    cfg = get_config()
    db = await get_db()
    added, removed = await sync_index(db, cfg.issues_dir)
    await db.commit()
    return HTMLResponse(f'<span class="save-ok">✓ Sync complete — {added} added, {removed} removed</span>')


def _archive_dir() -> Path:
    return Path(get_config().issues_dir) / "archive"


@router.get("/archive", response_class=HTMLResponse)
async def list_archive(request: Request):
    archive = _archive_dir()
    items = []
    if archive.exists():
        from ..services.issue_store import read_issue
        for zp in sorted(archive.glob("issue-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                meta, _ = read_issue(zp)
                items.append({"id": meta.get("id", zp.stem), "title": meta.get("title") or "(no title)",
                               "modified": (meta.get("modified") or "")[:10], "filename": zp.name})
            except Exception:
                items.append({"id": zp.stem, "title": zp.name, "modified": "", "filename": zp.name})
    return templates.TemplateResponse(request, "settings/_archive.html", {"items": items})


@router.post("/archive/{filename}/restore", response_class=HTMLResponse)
async def restore_issue(request: Request, filename: str):
    archive = _archive_dir()
    src = archive / filename
    if not src.exists():
        return HTMLResponse('<span style="color:#dc2626">File not found</span>')
    dst = Path(get_config().issues_dir) / filename
    src.rename(dst)
    # Re-index the restored issue
    from ..services.issue_store import read_issue
    db = await get_db()
    meta, _ = read_issue(dst)
    if meta.get("id"):
        await sync_index(db, Path(get_config().issues_dir))
        await db.commit()
    return await list_archive(request)


@router.get("", response_class=HTMLResponse)
async def settings_page(request: Request):
    cfg = get_config()
    return templates.TemplateResponse(request, "settings/settings.html", {"cfg": cfg})


# ── General ──────────────────────────────────────────────────────────────────

@router.post("/general", response_class=HTMLResponse)
async def save_general(
    request: Request,
    site_name: str = Form("Helm"),
    host: str = Form("0.0.0.0"),
    port: int = Form(8081),
    issues_dir: str = Form("./data/issues"),
    docs_dir: str = Form("./data/docs"),
    db_path: str = Form("./data/Helm.db"),
):
    data = _current_yaml()
    data.update(site_name=site_name, host=host, port=port, issues_dir=issues_dir, docs_dir=docs_dir, db_path=db_path)
    _save(data)
    return HTMLResponse('<span class="save-ok">✓ Saved — restart to apply path changes</span>')


# ── SMTP ─────────────────────────────────────────────────────────────────────

@router.post("/smtp", response_class=HTMLResponse)
async def save_smtp(
    request: Request,
    enabled: str = Form("off"),
    host: str = Form(""),
    port: int = Form(587),
    tls: str = Form("off"),
    username: str = Form(""),
    password: str = Form(""),
    from_address: str = Form(""),
    to_addresses: str = Form(""),
):
    data = _current_yaml()
    data.setdefault("smtp", {})
    data["smtp"] = {
        "enabled": enabled == "on",
        "host": host,
        "port": port,
        "tls": tls == "on",
        "username": username,
        "password": password,
        "from_address": from_address,
        "to_addresses": [a.strip() for a in to_addresses.splitlines() if a.strip()],
    }
    _save(data)
    return HTMLResponse('<span class="save-ok">✓ Saved</span>')


@router.post("/smtp/test", response_class=HTMLResponse)
async def test_smtp(request: Request):
    cfg = get_config()
    smtp = cfg.smtp
    if not smtp.enabled:
        return HTMLResponse('<span style="color:#dc2626">SMTP is disabled — save first</span>')
    try:
        import aiosmtplib
        from email.mime.text import MIMEText
        msg = MIMEText("This is a test email from Helm.", "plain", "utf-8")
        msg["Subject"] = "[Helm] Test email"
        msg["From"] = smtp.from_address
        msg["To"] = ", ".join(smtp.to_addresses)
        await aiosmtplib.send(
            msg,
            hostname=smtp.host,
            port=smtp.port,
            username=smtp.username,
            password=smtp.password,
            start_tls=smtp.tls,
        )
        return HTMLResponse('<span class="save-ok">✓ Test email sent</span>')
    except Exception as e:
        return HTMLResponse(f'<span style="color:#dc2626">✗ {e}</span>')


# ── Notifications ─────────────────────────────────────────────────────────────

@router.post("/notifications", response_class=HTMLResponse)
async def save_notifications(
    request: Request,
    base_url: str = Form("http://localhost:8081"),
    trigger_hour: int = Form(7),
    due_tomorrow: str = Form("off"),
    digest_daily: str = Form("off"),
    digest_weekly: str = Form("off"),
    digest_monthly: str = Form("off"),
    digest_yearly: str = Form("off"),
):
    data = _current_yaml()
    data["notifications"] = {
        "base_url": base_url,
        "trigger_hour": trigger_hour,
        "due_tomorrow": due_tomorrow == "on",
        "digest_daily": digest_daily == "on",
        "digest_weekly": digest_weekly == "on",
        "digest_monthly": digest_monthly == "on",
        "digest_yearly": digest_yearly == "on",
    }
    _save(data)
    return HTMLResponse('<span class="save-ok">✓ Saved</span>')


# ── Security ─────────────────────────────────────────────────────────────────

@router.post("/security", response_class=HTMLResponse)
async def save_security(
    request: Request,
    admin_user: str = Form(""),
    admin_password: str = Form(""),
):
    data = _current_yaml()
    data.update(admin_user=admin_user, admin_password=admin_password)
    _save(data)
    return HTMLResponse('<span class="save-ok">✓ Saved</span>')


# ── Lighthouse ────────────────────────────────────────────────────────────────

@router.post("/lighthouse", response_class=HTMLResponse)
async def save_lighthouse(
    request: Request,
    disable_notifications: str = Form("off"),
    lh_name: list[str] = Form(default=[]),
    lh_url: list[str] = Form(default=[]),
    lh_token: list[str] = Form(default=[]),
):
    data = _current_yaml()
    lighthouses = [
        {"name": n, "url": u, "token": t}
        for n, u, t in zip(lh_name, lh_url, lh_token)
        if u.strip()
    ]
    data.update(
        disable_notifications=(disable_notifications == "on"),
        lighthouses=lighthouses,
    )
    # Remove legacy single-instance keys
    data.pop("lighthouse_url", None)
    data.pop("lighthouse_token", None)
    _save(data)
    return HTMLResponse('<span class="save-ok">✓ Saved — restart to apply mode change</span>')


@router.get("/lighthouse/instances", response_class=HTMLResponse)
async def lighthouse_instances(request: Request):
    db = await get_db()
    async with db.execute(
        "SELECT site_name, url, created, last_seen, revoked FROM sync_instances ORDER BY created"
    ) as cur:
        rows = await cur.fetchall()
    items = []
    for r in rows:
        d = dict(r)
        async with db.execute(
            "SELECT COUNT(*) as cnt FROM issues WHERE origin_site = ?", (d["site_name"],)
        ) as cur2:
            cnt = await cur2.fetchone()
        d["issue_count"] = cnt["cnt"] if cnt else 0
        items.append(d)
    return templates.TemplateResponse(request, "settings/_instances.html", {"items": items})


@router.post("/lighthouse/register", response_class=HTMLResponse)
async def register_instance(
    request: Request,
    site_name: str = Form(...),
    url: str = Form(""),
    read_only: str = Form("off"),
):
    import secrets, hashlib
    from datetime import datetime, timezone
    db = await get_db()
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ro = 1 if read_only == "on" else 0
    await db.execute(
        """INSERT INTO sync_instances (site_name, url, token_hash, created, last_seen, revoked, read_only)
           VALUES (?, ?, ?, ?, NULL, 0, ?)
           ON CONFLICT(site_name) DO UPDATE SET url=excluded.url, token_hash=excluded.token_hash,
           created=excluded.created, revoked=0, read_only=excluded.read_only""",
        (site_name, url, token_hash, now, ro),
    )
    await db.commit()
    return templates.TemplateResponse(
        request, "settings/_instance_token.html",
        {"site_name": site_name, "token": token},
    )


@router.post("/lighthouse/instances/{site_name}/revoke", response_class=HTMLResponse)
async def revoke_instance(request: Request, site_name: str):
    db = await get_db()
    await db.execute("UPDATE sync_instances SET revoked = 1 WHERE site_name = ?", (site_name,))
    await db.commit()
    return await lighthouse_instances(request)


@router.get("/report/templates", response_class=HTMLResponse)
async def report_templates(request: Request):
    from ..services.report_store import load_templates
    cfg = get_config()
    tpls = load_templates(cfg.report_templates_file)
    return templates.TemplateResponse(request, "settings/_report_templates.html", {"templates": tpls})


@router.post("/report/templates", response_class=HTMLResponse)
async def create_report_template(
    request: Request,
    name: str = Form(""),
    body: str = Form(""),
    tags: str = Form(""),
    priority: str = Form("medium"),
):
    from ..services.report_store import add_template
    cfg = get_config()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    tpls = add_template(cfg.report_templates_file, name or "Vorlage", body, tag_list, priority)
    return templates.TemplateResponse(request, "settings/_report_templates.html", {"templates": tpls})


@router.post("/report/templates/{template_id}", response_class=HTMLResponse)
async def update_report_template(
    request: Request,
    template_id: str,
    name: str = Form(""),
    body: str = Form(""),
    tags: str = Form(""),
    priority: str = Form("medium"),
):
    from ..services.report_store import update_template
    cfg = get_config()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    tpls = update_template(cfg.report_templates_file, template_id, name or "Vorlage", body, tag_list, priority)
    return templates.TemplateResponse(request, "settings/_report_templates.html", {"templates": tpls})


@router.delete("/report/templates/{template_id}", response_class=HTMLResponse)
async def delete_report_template(request: Request, template_id: str):
    from ..services.report_store import delete_template
    cfg = get_config()
    tpls = delete_template(cfg.report_templates_file, template_id)
    return templates.TemplateResponse(request, "settings/_report_templates.html", {"templates": tpls})


@router.post("/lighthouse/instances/{site_name}/regenerate", response_class=HTMLResponse)
async def regenerate_token(request: Request, site_name: str):
    import secrets, hashlib
    db = await get_db()
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    await db.execute(
        "UPDATE sync_instances SET token_hash = ?, revoked = 0 WHERE site_name = ?",
        (token_hash, site_name),
    )
    await db.commit()
    return templates.TemplateResponse(
        request, "settings/_instance_token.html",
        {"site_name": site_name, "token": token},
    )


