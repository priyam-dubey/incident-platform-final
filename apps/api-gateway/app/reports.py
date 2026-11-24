from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

COLUMNS = ["severity", "status", "tool", "rule_id", "category", "title", "file_path", "start_line", "cwe", "package_name",
           "package_version", "fixed_version", "first_seen_commit", "last_seen_commit"]


def _cell(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s       # spreadsheet formula-injection guard


def findings_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(COLUMNS)
    for r in rows:
        w.writerow([_cell(r.get(c)) for c in COLUMNS])
    return buf.getvalue()


def findings_pdf(repository: str, summary: dict, rows: list[dict]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf, st = io.BytesIO(), getSampleStyleSheet()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), title=f"Code findings - {repository}")
    esc = lambda s: str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    sev = summary.get("by_severity", {})
    parts = [Paragraph(f"Code findings - {esc(repository)}", st["Title"]),
             Paragraph(f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. Open findings: " +
                       ", ".join(f"{k}: {sev.get(k, 0)}" for k in ("critical", "high", "medium", "low", "info")), st["Normal"]), Spacer(1, 12)]
    data = [["Severity", "Tool", "Rule", "Title", "Location", "Status"]] + [
        [r["severity"], r["tool"], esc(r["rule_id"])[:30], Paragraph(esc(r["title"])[:140], st["BodyText"]),
         f"{esc(r.get('file_path') or '')}:{r.get('start_line') or ''}"[:60], r["status"]] for r in rows[:500]]
    t = Table(data, repeatRows=1, colWidths=[55, 60, 120, 300, 200, 70])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    parts.append(t)
    if len(rows) > 500:
        parts.append(Paragraph(f"Showing 500 of {len(rows)} findings. Use the CSV export for the full list.", st["Italic"]))
    doc.build(parts)
    return buf.getvalue()
