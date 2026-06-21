"""PDF report builder — turns a structured section spec into a PDF file.

Called by Dash's tool dispatch. Sections are a list of dicts with `type`
(heading, subheading, body, bullet_list, spacer) and content. Returns the
path to the generated PDF.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

OUTPUT_DIR = Path(os.environ.get("DASH_OUTPUT_DIR", "/tmp/dash_output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

_DARK = HexColor("#1B3A2D")
_ACCENT = HexColor("#2E7D32")
_GRAY = HexColor("#616161")


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle(
        "DashTitle", parent=ss["Title"],
        fontSize=22, textColor=_DARK, spaceAfter=6,
    ))
    ss.add(ParagraphStyle(
        "DashHeading", parent=ss["Heading2"],
        fontSize=16, textColor=_ACCENT, spaceBefore=14, spaceAfter=6,
    ))
    ss.add(ParagraphStyle(
        "DashSubheading", parent=ss["Heading3"],
        fontSize=13, textColor=_DARK, spaceBefore=10, spaceAfter=4,
    ))
    ss.add(ParagraphStyle(
        "DashBody", parent=ss["BodyText"],
        fontSize=11, textColor=_GRAY, spaceAfter=6, leading=15,
    ))
    ss.add(ParagraphStyle(
        "DashBullet", parent=ss["BodyText"],
        fontSize=11, textColor=_GRAY, spaceAfter=4, leading=14,
        leftIndent=16, bulletIndent=6,
    ))
    return ss


def build_pdf(sections: list[dict[str, Any]], filename: str | None = None, title: str | None = None) -> dict:
    """Build a PDF from a section spec list. Returns {"path": ..., "filename": ...}."""
    ss = _styles()
    fname = filename or f"dash_{uuid.uuid4().hex[:8]}.pdf"
    if not fname.endswith(".pdf"):
        fname += ".pdf"
    out_path = OUTPUT_DIR / fname

    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=25 * mm, bottomMargin=20 * mm,
    )
    story: list[Any] = []

    if title:
        story.append(Paragraph(title, ss["DashTitle"]))
        story.append(HRFlowable(width="100%", thickness=1, color=_ACCENT))
        story.append(Spacer(1, 10 * mm))

    for sec in sections:
        t = sec.get("type", "body")
        text = sec.get("text", "")

        if t == "heading":
            story.append(Paragraph(text, ss["DashHeading"]))
        elif t == "subheading":
            story.append(Paragraph(text, ss["DashSubheading"]))
        elif t == "body":
            for line in text.split("\n"):
                if line.strip():
                    story.append(Paragraph(line, ss["DashBody"]))
        elif t == "bullet_list":
            items = sec.get("items", [])
            if isinstance(items, str):
                items = [i.strip() for i in items.split("\n") if i.strip()]
            for item in items:
                story.append(Paragraph(f"• {item}", ss["DashBullet"]))
        elif t == "spacer":
            story.append(Spacer(1, float(sec.get("height_mm", 8)) * mm))
        elif t == "hr":
            story.append(HRFlowable(width="100%", thickness=0.5, color=_GRAY))

    doc.build(story)
    return {"path": str(out_path), "filename": fname, "sections": len(sections)}
