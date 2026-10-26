"""
Email notifications:
- Due-tomorrow alert  (daily at 07:00)
- Digest              (daily / weekly / monthly / yearly)

Configured in config.yaml under the smtp + notifications keys.
"""
import asyncio
import base64
import logging
import re
import zipfile
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import aiosmtplib
import markdown as md_lib

from .issue_store import read_issue

log = logging.getLogger(__name__)


# ── Send helper ───────────────────────────────────────────────────────────────

async def _send(cfg, subject: str, body_html: str) -> None:
    smtp = cfg.smtp
    if not smtp.enabled or not smtp.to_addresses:
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp.from_address
    msg["To"] = ", ".join(smtp.to_addresses)
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=smtp.host,
            port=smtp.port,
            username=smtp.username,
            password=smtp.password,
            start_tls=smtp.tls,
        )
        log.info("Email sent: %s", subject)
    except Exception as e:
        log.error("Email failed: %s", e)


# ── Issue queries ─────────────────────────────────────────────────────────────

async def _get_due_tomorrow(db) -> list[dict]:
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    cursor = await db.execute(
        "SELECT id, title, status, priority, due FROM issues WHERE due = ? AND status != 'closed'",
        (tomorrow,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def _get_open_issues(db, since: date | None = None) -> list[dict]:
    if since:
        cursor = await db.execute(
            "SELECT id, title, status, priority, due FROM issues WHERE status != 'closed' AND modified >= ?",
            (since.isoformat(),),
        )
    else:
        cursor = await db.execute(
            "SELECT id, title, status, priority, due FROM issues WHERE status != 'closed'"
        )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# ── Email builders ────────────────────────────────────────────────────────────

_PRIORITY_COLOR = {"critical": "#dc2626", "high": "#ea580c", "medium": "#d97706", "low": "#16a34a"}

_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
         "gif": "image/gif", "webp": "image/webp", "svg": "image/svg+xml"}

def _embed_images(html: str, zip_path) -> str:
    """Replace /issues/.../images/filename src with inline base64 data URIs."""
    def replacer(m):
        filename = m.group(1)
        ext = Path(filename).suffix.lstrip(".").lower()
        mime = _MIME.get(ext, "image/png")
        try:
            with zipfile.ZipFile(zip_path) as zf:
                data = zf.read(f"images/{filename}")
            b64 = base64.b64encode(data).decode()
            return f'src="data:{mime};base64,{b64}"'
        except Exception:
            return m.group(0)
    return re.sub(r'src="[^"]*?/images/([^"]+)"', replacer, html)


def _render_body(zip_path, base_url: str) -> str:
    try:
        _, body = read_issue(zip_path)
        if not body.strip():
            return ""
        html = md_lib.markdown(body, extensions=["fenced_code", "tables"])
        html = _embed_images(html, zip_path)
        return html
    except Exception:
        return ""


def _issue_block(issue: dict, zip_path, base_url: str) -> str:
    color = _PRIORITY_COLOR.get(issue["priority"], "#64748b")
    due = f'<span style="color:#dc2626;font-size:12px">Due: {issue["due"]}</span>' if issue.get("due") else ""
    body_html = _render_body(zip_path, base_url)
    body_section = (
        f'<div style="margin:10px 0 0 0;padding:12px;background:#f8fafc;border-radius:6px;'
        f'font-size:13px;color:#374151;border-left:3px solid #e2e8f0">{body_html}</div>'
        if body_html else ""
    )
    return f"""
<div style="margin-bottom:24px;padding:16px;border:1px solid #e2e8f0;border-radius:8px;background:#fff">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
    <a href="{base_url}/issues/{issue['id']}"
       style="color:#2563eb;text-decoration:none;font-weight:600;font-size:15px">
      {issue['title'] or '(no title)'}
    </a>
    <span style="padding:2px 6px;border-radius:4px;background:{color};color:#fff;font-size:11px">
      {issue['priority']}
    </span>
    {due}
  </div>
  {body_section}
</div>"""


def _build_email(title: str, intro: str, issues: list[dict], zip_dir, base_url: str, site_name: str = "Helm") -> str:
    from pathlib import Path
    blocks = ""
    for issue in issues:
        zip_path = Path(zip_dir) / f"issue-{issue['id']}.zip"
        blocks += _issue_block(issue, zip_path, base_url)
    return f"""
<html><body style="font-family:system-ui,sans-serif;color:#1e293b;max-width:640px;margin:0 auto;padding:24px">
<h2 style="color:#2563eb;margin-bottom:4px">☸ {site_name} — {title}</h2>
<p style="color:#64748b;margin-top:0">{intro}</p>
{blocks}
<p style="margin-top:24px;font-size:12px;color:#94a3b8">
  <a href="{base_url}/issues" style="color:#2563eb">Open {site_name}</a>
</p>
</body></html>"""


# ── Scheduled checks ──────────────────────────────────────────────────────────

async def check_due_tomorrow(db, cfg) -> None:
    issues = await _get_due_tomorrow(db)
    if not issues:
        return
    base_url = cfg.notifications.base_url
    site = cfg.site_name
    html = _build_email(
        "Issues due tomorrow",
        f"{len(issues)} issue(s) are due tomorrow ({(date.today() + timedelta(days=1)).isoformat()}):",
        issues, cfg.issues_dir, base_url, site,
    )
    await _send(cfg, f"[{site}] {len(issues)} issue(s) due tomorrow", html)


async def send_digest(db, cfg, period: str) -> None:
    """period: daily | weekly | monthly | yearly"""
    since_map = {"daily": 1, "weekly": 7, "monthly": 30, "yearly": 365}
    days = since_map.get(period, 1)
    since = date.today() - timedelta(days=days)
    issues = await _get_open_issues(db, since=since)
    if not issues:
        return
    base_url = cfg.notifications.base_url
    site = cfg.site_name
    label = {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly", "yearly": "Yearly"}[period]
    html = _build_email(
        f"{label} Digest",
        f"{len(issues)} open issue(s) updated in the last {days} day(s):",
        issues, cfg.issues_dir, base_url, site,
    )
    await _send(cfg, f"[{site}] {label} digest — {len(issues)} open issue(s)", html)


# ── Background scheduler ──────────────────────────────────────────────────────

async def _scheduler_loop(get_db_fn, get_cfg_fn) -> None:
    """Runs forever, waking every minute to check if any job is due."""
    log.info("Notification scheduler started")
    last_run: dict[str, date] = {}

    while True:
        now = datetime.now()
        today = now.date()
        hour = now.hour
        cfg = get_cfg_fn()
        notif = cfg.notifications

        if not cfg.smtp.enabled:
            await asyncio.sleep(60)
            continue

        db = await get_db_fn()

        # Due-tomorrow alert — once per day at trigger_hour
        if notif.due_tomorrow and hour == notif.trigger_hour and last_run.get("due") != today:
            last_run["due"] = today
            await check_due_tomorrow(db, cfg)

        # Digests
        for period in ("daily", "weekly", "monthly", "yearly"):
            enabled = getattr(notif, f"digest_{period}", False)
            if not enabled:
                continue
            if hour != notif.trigger_hour:
                continue
            if period == "daily" and last_run.get("digest_daily") != today:
                last_run["digest_daily"] = today
                await send_digest(db, cfg, "daily")
            elif period == "weekly" and now.weekday() == 0 and last_run.get("digest_weekly") != today:
                last_run["digest_weekly"] = today
                await send_digest(db, cfg, "weekly")
            elif period == "monthly" and today.day == 1 and last_run.get("digest_monthly") != today:
                last_run["digest_monthly"] = today
                await send_digest(db, cfg, "monthly")
            elif period == "yearly" and today.month == 1 and today.day == 1 and last_run.get("digest_yearly") != today:
                last_run["digest_yearly"] = today
                await send_digest(db, cfg, "yearly")

        await asyncio.sleep(60)


def start_scheduler(get_db_fn, get_cfg_fn) -> asyncio.Task:
    return asyncio.create_task(_scheduler_loop(get_db_fn, get_cfg_fn))

