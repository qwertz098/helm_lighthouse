"""Markdown → sanitized HTML (issue bodies and docs may come from remote sites)."""
import markdown as md_lib
import nh3

_ATTRS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title", "width", "height"},
    "td": {"align"},
    "th": {"align"},
    "code": {"class"},
}


def render_markdown(text: str) -> str:
    html = md_lib.markdown(text, extensions=["fenced_code", "tables"])
    return nh3.clean(html, attributes=_ATTRS, url_schemes={"http", "https", "mailto", "data"})
