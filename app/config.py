import os
from pathlib import Path

import yaml
from pydantic import BaseModel


class SmtpConfig(BaseModel):
    enabled: bool = False
    host: str = "mail.gmx.net"
    port: int = 587
    tls: bool = True
    username: str = ""
    password: str = ""
    from_address: str = ""
    to_addresses: list[str] = []


class NotificationsConfig(BaseModel):
    base_url: str = "http://localhost:8081"
    trigger_hour: int = 7          # hour of day (0-23) to send emails
    due_tomorrow: bool = True      # alert for issues due the next day
    digest_daily: bool = False
    digest_weekly: bool = False
    digest_monthly: bool = False
    digest_yearly: bool = False


class LighthouseTarget(BaseModel):
    name: str = ""
    url: str = ""
    token: str = ""


class Config(BaseModel):
    site_name: str = "Helm"
    site_id: str = ""                         # stable UUID, auto-generated on first run
    mode: str = "helm"                       # "helm" | "lighthouse"
    lighthouses: list[LighthouseTarget] = [] # Helm-side: connected Lighthouse instances
    # legacy single-lighthouse fields (migrated on load)
    lighthouse_url: str = ""
    lighthouse_token: str = ""
    disable_notifications: bool = False
    # Web UI basic auth (empty = disabled)
    admin_user: str = ""
    admin_password: str = ""
    issues_dir: Path = Path("./data/issues")
    docs_dir: Path = Path("./data/docs")
    db_path: Path = Path("./data/Helm.db")
    dashboard_file: Path = Path("./data/dashboard.yaml")
    report_templates_file: Path = Path("./data/report_templates.yaml")
    host: str = "0.0.0.0"
    port: int = 8080
    smtp: SmtpConfig = SmtpConfig()
    notifications: NotificationsConfig = NotificationsConfig()


_config: Config | None = None

_DEFAULT_CONFIG = """\
# Helm configuration
# Edit this file and restart the app to apply changes.

issues_dir: /data/issues
docs_dir: /data/docs
db_path: /data/Helm.db
dashboard_file: /data/dashboard.yaml
host: 0.0.0.0
port: 8080

smtp:
  enabled: false
  host: mail.gmx.net
  port: 587
  tls: true
  username: user@example.com
  # password can also be set via SMTP_PASSWORD environment variable
  password: ""
  from_address: user@example.com
  to_addresses:
    - recipient@example.com

notifications:
  base_url: http://localhost:8081   # used in email links
  trigger_hour: 7                   # hour of day to send emails (0-23)
  due_tomorrow: true                # alert for issues due the next day
  digest_daily: false
  digest_weekly: false
  digest_monthly: false
  digest_yearly: false
"""


def load_config(path: str | None = None) -> "Config":
    global _config

    # Docker: config path from env, fallback to local
    cfg_path = path or os.environ.get("APP_CONFIG", "config.yaml")

    if not Path(cfg_path).exists():
        # Auto-create default config (useful for first Docker run)
        Path(cfg_path).parent.mkdir(parents=True, exist_ok=True)
        Path(cfg_path).write_text(_DEFAULT_CONFIG, encoding="utf-8")

    with open(cfg_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # ── Environment variable overrides ──────────────────────────────────────
    env = os.environ

    # General
    if v := env.get("HELM_SITE_NAME"):   data["site_name"] = v
    if v := env.get("HELM_MODE"):        data["mode"] = v
    if v := env.get("HELM_ADMIN_USER"):  data["admin_user"] = v
    if v := env.get("HELM_ADMIN_PASSWORD"): data["admin_password"] = v
    if v := env.get("HELM_DISABLE_NOTIFICATIONS"): data["disable_notifications"] = v.lower() in ("1", "true", "yes")

    # SMTP
    if v := env.get("SMTP_PASSWORD"):    data.setdefault("smtp", {})["password"] = v
    if v := env.get("SMTP_HOST"):        data.setdefault("smtp", {})["host"] = v
    if v := env.get("SMTP_PORT"):        data.setdefault("smtp", {})["port"] = int(v)
    if v := env.get("SMTP_TLS"):         data.setdefault("smtp", {})["tls"] = v.lower() in ("1", "true", "yes")
    if v := env.get("SMTP_USERNAME"):    data.setdefault("smtp", {})["username"] = v
    if v := env.get("SMTP_FROM"):        data.setdefault("smtp", {})["from_address"] = v
    if v := env.get("SMTP_TO"):          data.setdefault("smtp", {})["to_addresses"] = [a.strip() for a in v.split(",") if a.strip()]
    if v := env.get("SMTP_ENABLED"):     data.setdefault("smtp", {})["enabled"] = v.lower() in ("1", "true", "yes")

    # Lighthouses (JSON array or single-instance shorthand)
    # JSON: LIGHTHOUSES=[{"name":"x","url":"http://...","token":"abc"}]
    # Single: LIGHTHOUSE_URL + LIGHTHOUSE_TOKEN (+ optional LIGHTHOUSE_NAME)
    if v := env.get("LIGHTHOUSES"):
        import json as _json
        data["lighthouses"] = _json.loads(v)
    elif env.get("LIGHTHOUSE_URL"):
        data["lighthouses"] = [{
            "name": env.get("LIGHTHOUSE_NAME", "Lighthouse"),
            "url": env["LIGHTHOUSE_URL"],
            "token": env.get("LIGHTHOUSE_TOKEN", ""),
        }]

    # Migrate legacy single lighthouse_url (YAML) → lighthouses list
    if data.get("lighthouse_url") and not data.get("lighthouses"):
        data["lighthouses"] = [{"name": "Lighthouse", "url": data["lighthouse_url"], "token": data.get("lighthouse_token", "")}]

    _config = Config(**data)

    # Auto-generate site_id if missing and persist it back to config.yaml
    if not _config.site_id:
        import uuid as _uuid
        _config.site_id = str(_uuid.uuid4())
        cfg_file = Path(cfg_path)
        raw_text = cfg_file.read_text(encoding="utf-8")
        raw_text += f"\nsite_id: {_config.site_id}\n"
        cfg_file.write_text(raw_text, encoding="utf-8")

    for d in [_config.issues_dir, _config.docs_dir, _config.db_path.parent, _config.dashboard_file.parent]:
        Path(d).mkdir(parents=True, exist_ok=True)

    return _config


def get_config() -> "Config":
    if _config is None:
        raise RuntimeError("Config not loaded")
    return _config

