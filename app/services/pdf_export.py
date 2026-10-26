"""Render an issue/report to a PDF (pure-Python, fpdf2)."""
import io
import re
from typing import Any

from fpdf import FPDF


def _s(text: Any) -> str:
    """Sanitize text for the core (latin-1) fonts."""
    s = str(text if text is not None else "")
    s = s.replace("€", "EUR").replace("–", "-").replace("—", "-")
    s = s.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    s = s.replace("✅", "[x]").replace("☑", "[x]").replace("☐", "[ ]")
    return s.encode("latin-1", "replace").decode("latin-1")


def _strip_md(body: str) -> list[tuple[str, str]]:
    """Very small markdown → (style, text) line list for the PDF body."""
    lines: list[tuple[str, str]] = []
    for raw in (body or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            lines.append(("space", ""))
            continue
        if line.startswith("### "):
            lines.append(("h3", line[4:]))
        elif line.startswith("## "):
            lines.append(("h2", line[3:]))
        elif line.startswith("# "):
            lines.append(("h2", line[2:]))
        elif re.match(r"^- \[x\] ", line, re.I):
            lines.append(("text", "[x] " + line[6:]))
        elif line.startswith("- [ ] "):
            lines.append(("text", "[ ] " + line[6:]))
        elif line.startswith("- ") or line.startswith("* "):
            lines.append(("text", "- " + line[2:]))
        else:
            # drop inline emphasis/link syntax
            line = re.sub(r"[*_`]", "", line)
            line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
            lines.append(("text", line))
    return lines


class _PDF(FPDF):
    title_text = ""
    site_text = ""

    def footer(self):
        self.set_y(-12)
        self.set_font("helvetica", "I", 8)
        self.set_text_color(120)
        self.cell(0, 8, _s(self.site_text), align="L")
        self.cell(0, 8, f"Page {self.page_no()}", align="R")


def build_issue_pdf(meta: dict, body: str, signature_png: bytes | None, site_name: str = "") -> bytes:
    is_report = meta.get("type") == "report"
    r = meta.get("report") or {}

    pdf = _PDF()
    pdf.site_text = site_name
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()
    epw = pdf.epw  # effective page width

    # ── Header ──
    pdf.set_font("helvetica", "B", 16)
    pdf.set_text_color(20)
    pdf.multi_cell(0, 8, _s(meta.get("title") or "(Untitled)"))
    pdf.set_font("helvetica", "", 9)
    pdf.set_text_color(110)
    sub = ("Report · " if is_report else "") + f"ID {str(meta.get('id',''))[:8]}"
    if meta.get("signed_at"):
        sub += f"  ·  Signed {meta['signed_at'][:10]}"
    pdf.cell(0, 6, _s(sub))
    pdf.ln(8)
    pdf.set_draw_color(30)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + epw, pdf.get_y())
    pdf.ln(4)

    def kv_grid(pairs: list[tuple[str, str]], cols: int = 3):
        col_w = epw / cols
        for i in range(0, len(pairs), cols):
            row = pairs[i:i + cols]
            y0 = pdf.get_y()
            for j, (label, value) in enumerate(row):
                x = pdf.l_margin + j * col_w
                pdf.set_xy(x, y0)
                pdf.set_font("helvetica", "", 7)
                pdf.set_text_color(150)
                pdf.cell(col_w, 4, _s(label.upper()))
                pdf.set_xy(x, y0 + 4)
                pdf.set_font("helvetica", "B", 10)
                pdf.set_text_color(30)
                pdf.cell(col_w, 5, _s(value))
            pdf.set_y(y0 + 10)

    def heading(txt: str):
        pdf.ln(3)
        pdf.set_font("helvetica", "B", 12)
        pdf.set_text_color(20)
        pdf.cell(0, 7, _s(txt))
        pdf.ln(8)

    # ── Metadata ──
    meta_pairs = [("Status", meta.get("status", "")), ("Priority", meta.get("priority", ""))]
    if meta.get("due"):
        meta_pairs.append(("Due", meta["due"]))
    meta_pairs.append(("Created", (meta.get("created") or "")[:10]))
    meta_pairs.append(("Modified", (meta.get("modified") or "")[:10]))
    if meta.get("tags"):
        meta_pairs.append(("Tags", ", ".join(meta["tags"])))
    kv_grid(meta_pairs)

    # ── Report fields ──
    if is_report and r:
        heading("Service Report")
        rp = []
        if r.get("date"):  rp.append(("Date", r["date"]))
        if r.get("start"): rp.append(("From", r["start"]))
        if r.get("end"):   rp.append(("To", r["end"]))
        rp.append(("Break (min)", r.get("break_minutes", 0)))
        rp.append(("Distance (km)", r.get("km", 0)))
        if r.get("cost_per_km"): rp.append(("EUR/km", f"{float(r['cost_per_km']):.2f}"))
        kv_grid(rp)

        positions = r.get("positions") or []
        if positions:
            heading("Items")
            pdf.set_font("helvetica", "B", 8)
            pdf.set_text_color(120)
            pdf.cell(epw * 0.8, 6, "TASK", border="B")
            pdf.cell(epw * 0.2, 6, "HOURS", border="B", align="R")
            pdf.ln(6)
            total = 0.0
            pdf.set_text_color(30)
            for p in positions:
                total += float(p.get("hours") or 0)
                pdf.set_font("helvetica", "", 10)
                pdf.cell(epw * 0.8, 6, _s(p.get("description", "")), border="B")
                pdf.cell(epw * 0.2, 6, _s(p.get("hours", 0)), border="B", align="R")
                pdf.ln(6)
            pdf.set_font("helvetica", "B", 10)
            pdf.cell(epw * 0.8, 6, "Total")
            pdf.cell(epw * 0.2, 6, _s(f"{total:g} h"), align="R")
            pdf.ln(8)

        expense_items = r.get("expense_items") or []
        km = float(r.get("km") or 0)
        cost_per_km = float(r.get("cost_per_km") or 0)
        travel_amt = km * cost_per_km
        if expense_items or travel_amt:
            heading("Expenses")
            pdf.set_font("helvetica", "B", 8)
            pdf.set_text_color(120)
            pdf.cell(epw * 0.8, 6, "EXPENSE", border="B")
            pdf.cell(epw * 0.2, 6, "COST (EUR)", border="B", align="R")
            pdf.ln(6)
            exp_total = travel_amt
            pdf.set_text_color(80)
            pdf.set_font("helvetica", "I", 9)
            pdf.cell(epw * 0.8, 6, _s(f"Travel ({km:g} km x {cost_per_km:.2f} EUR/km)"), border="B")
            pdf.cell(epw * 0.2, 6, _s(f"{travel_amt:.2f}"), border="B", align="R")
            pdf.ln(6)
            pdf.set_text_color(30)
            for ei in expense_items:
                exp_total += float(ei.get("cost") or 0)
                pdf.set_font("helvetica", "", 10)
                pdf.cell(epw * 0.8, 6, _s(ei.get("description", "")), border="B")
                pdf.cell(epw * 0.2, 6, _s(f"{float(ei.get('cost') or 0):.2f}"), border="B", align="R")
                pdf.ln(6)
            pdf.set_font("helvetica", "B", 10)
            pdf.cell(epw * 0.8, 6, "Total")
            pdf.cell(epw * 0.2, 6, _s(f"{exp_total:.2f} EUR"), align="R")
            pdf.ln(8)

        executors = r.get("executors") or []
        if executors:
            heading("Executed by")
            pdf.set_font("helvetica", "B", 8)
            pdf.set_text_color(120)
            pdf.cell(epw * 0.5, 6, "NAME", border="B")
            pdf.cell(epw * 0.5, 6, "COMPANY", border="B")
            pdf.ln(6)
            pdf.set_text_color(30)
            pdf.set_font("helvetica", "", 10)
            for ex in executors:
                pdf.cell(epw * 0.5, 6, _s(ex.get("name", "")), border="B")
                pdf.cell(epw * 0.5, 6, _s(ex.get("company", "")), border="B")
                pdf.ln(6)
            pdf.ln(2)

    # ── Body ──
    if (body or "").strip():
        heading("Details")
        for style, txt in _strip_md(body):
            if style == "space":
                pdf.ln(2)
            elif style == "h2":
                pdf.set_font("helvetica", "B", 12)
                pdf.set_text_color(20)
                pdf.multi_cell(0, 6, _s(txt))
            elif style == "h3":
                pdf.set_font("helvetica", "B", 10)
                pdf.set_text_color(40)
                pdf.multi_cell(0, 5.5, _s(txt))
            else:
                pdf.set_font("helvetica", "", 10)
                pdf.set_text_color(40)
                pdf.multi_cell(0, 5.5, _s(txt))

    # ── Signature ──
    if is_report:
        heading("Signature")
        signer = r.get("signer") or {}
        kv_grid([("Name", signer.get("name") or "-"),
                 ("Company", signer.get("company") or "-")], cols=2)
        if signature_png:
            try:
                pdf.image(io.BytesIO(signature_png), w=70)
            except Exception:
                pass
        else:
            pdf.ln(14)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + 80, pdf.get_y())
            pdf.set_font("helvetica", "", 8)
            pdf.set_text_color(120)
            pdf.cell(0, 5, "Signature")

    out = pdf.output()
    return bytes(out)
