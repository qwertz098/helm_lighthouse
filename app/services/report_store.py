"""Load and save report templates (YAML)."""
import uuid
from pathlib import Path

import yaml

_HEADER = "# Helm Report-Vorlagen\n\n"


def load_templates(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    templates = data.get("templates") or []
    for t in templates:
        t.setdefault("id", str(uuid.uuid4()))
        t.setdefault("name", "Vorlage")
        t.setdefault("body", "")
        t.setdefault("tags", [])
        t.setdefault("priority", "medium")
    return templates


def save_templates(path: Path, templates: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _HEADER + yaml.dump({"templates": templates}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def get_template(path: Path, template_id: str) -> dict | None:
    for t in load_templates(path):
        if t["id"] == template_id:
            return t
    return None


def add_template(path: Path, name: str, body: str, tags: list[str], priority: str) -> list[dict]:
    templates = load_templates(path)
    templates.append({"id": str(uuid.uuid4()), "name": name, "body": body, "tags": tags, "priority": priority})
    save_templates(path, templates)
    return templates


def update_template(path: Path, template_id: str, name: str, body: str, tags: list[str], priority: str) -> list[dict]:
    templates = load_templates(path)
    for t in templates:
        if t["id"] == template_id:
            t.update({"name": name, "body": body, "tags": tags, "priority": priority})
    save_templates(path, templates)
    return templates


def delete_template(path: Path, template_id: str) -> list[dict]:
    templates = [t for t in load_templates(path) if t["id"] != template_id]
    save_templates(path, templates)
    return templates
