"""Build the assignment report PDF from its Markdown source.

Install the optional ``docs`` dependency from pyproject.toml, then run this
script from the project root. The PDF is written to output/pdf/.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reports" / "TraceByte_Final_Report.md"
OUTPUT = ROOT / "output" / "pdf" / "TraceByte_Final_Report.pdf"

INK = colors.HexColor("#172638")
SLATE = colors.HexColor("#496276")
CYAN = colors.HexColor("#07899A")
PALE = colors.HexColor("#EAF4F6")
RULE = colors.HexColor("#D8E2E8")


def plain_ascii(value: str) -> str:
    replacements = {
        "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",
        "\u2014": "-", "\u2212": "-", "\u2022": "-", "\u00b7": "|",
        "\u2192": "->", "\u2018": "'", "\u2019": "'", "\u201c": '"',
        "\u201d": '"', "\u00a0": " ",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    return value


def inline_markup(value: str) -> str:
    value = html.escape(plain_ascii(value), quote=False)
    value = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)",
                   r'<link href="\2" color="#07899A">\1</link>', value)
    value = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"`(.+?)`", r'<font name="Courier" color="#087C8A">\1</font>', value)
    return value


def split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def build_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("ReportTitle", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=24, leading=29, textColor=INK, alignment=TA_LEFT, spaceAfter=12),
        "h1": ParagraphStyle("Section", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=16, leading=20, textColor=INK, spaceBefore=14, spaceAfter=7, keepWithNext=True),
        "h2": ParagraphStyle("Subsection", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=11.5, leading=15, textColor=CYAN, spaceBefore=10, spaceAfter=5, keepWithNext=True),
        "body": ParagraphStyle("Body", parent=base["BodyText"], fontName="Helvetica",
            fontSize=9.3, leading=13.5, textColor=INK, spaceAfter=6, alignment=TA_LEFT),
        "small": ParagraphStyle("Small", parent=base["BodyText"], fontName="Helvetica",
            fontSize=8, leading=10.5, textColor=SLATE, spaceAfter=3),
        "meta": ParagraphStyle("Meta", parent=base["BodyText"], fontName="Helvetica",
            fontSize=10, leading=15, textColor=SLATE, spaceAfter=3),
        "table_head": ParagraphStyle("TableHead", parent=base["BodyText"], fontName="Helvetica-Bold",
            fontSize=7.8, leading=10, textColor=colors.white),
        "table_cell": ParagraphStyle("TableCell", parent=base["BodyText"], fontName="Helvetica",
            fontSize=7.7, leading=10, textColor=INK),
        "quote": ParagraphStyle("Quote", parent=base["BodyText"], fontName="Helvetica-Oblique",
            fontSize=9, leading=12, textColor=SLATE, leftIndent=10, borderColor=CYAN,
            borderWidth=0, spaceAfter=6),
    }


def make_table(rows: list[list[str]], available_width: float, styles) -> Table:
    column_count = max(map(len, rows))
    widths = [available_width / column_count] * column_count
    data = []
    for row_index, row in enumerate(rows):
        row += [""] * (column_count - len(row))
        style = styles["table_head"] if row_index == 0 else styles["table_cell"]
        data.append([Paragraph(inline_markup(cell), style) for cell in row])
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
        ("GRID", (0, 0), (-1, -1), 0.35, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def parse_markdown(text: str, styles, available_width: float):
    lines = text.splitlines()
    story = []
    paragraph_buffer: list[str] = []
    index = 0
    in_code = False
    code_lines: list[str] = []

    def flush_paragraph():
        if paragraph_buffer:
            story.append(Paragraph(inline_markup(" ".join(paragraph_buffer)), styles["body"]))
            paragraph_buffer.clear()

    while index < len(lines):
        line = lines[index].rstrip()
        if line.startswith("```"):
            flush_paragraph()
            if in_code:
                text_value = "<br/>".join(html.escape(plain_ascii(x)) for x in code_lines)
                code_style = ParagraphStyle("Code", parent=styles["small"], fontName="Courier",
                    fontSize=7.5, leading=10, backColor=PALE, borderPadding=6,
                    leftIndent=6, rightIndent=6, spaceBefore=2, spaceAfter=8)
                story.append(Paragraph(text_value or " ", code_style))
                code_lines.clear()
                in_code = False
            else:
                in_code = True
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue
        if not line.strip():
            flush_paragraph()
            index += 1
            continue
        if line.startswith("|" ) and index + 1 < len(lines) and re.match(r"\s*\|?\s*:?-{3,}", lines[index + 1]):
            flush_paragraph()
            rows = [split_table_row(line)]
            index += 2
            while index < len(lines) and lines[index].lstrip().startswith("|"):
                rows.append(split_table_row(lines[index]))
                index += 1
            story.extend([make_table(rows, available_width, styles), Spacer(1, 8)])
            continue
        if line.startswith("# "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(line[2:]), styles["title"]))
        elif line.startswith("## "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(line[3:]), styles["h1"]))
        elif line.startswith("### "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(line[4:]), styles["h2"]))
        elif line.strip() == "---":
            flush_paragraph()
            story.append(HRFlowable(width="100%", thickness=0.8, color=RULE, spaceBefore=3, spaceAfter=8))
        elif line.startswith("> "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(line[2:]), styles["quote"]))
        elif re.match(r"\s*[-*] ", line):
            flush_paragraph()
            story.append(Paragraph("- " + inline_markup(re.sub(r"^\s*[-*] ", "", line)), styles["body"]))
        elif re.match(r"\s*\d+\. ", line):
            flush_paragraph()
            story.append(Paragraph(inline_markup(line.strip()), styles["body"]))
        else:
            paragraph_buffer.append(line)
        index += 1
    flush_paragraph()
    return story


def draw_page(canvas, document):
    canvas.saveState()
    width, height = A4
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.6)
    canvas.line(document.leftMargin, height - 14 * mm, width - document.rightMargin, height - 14 * mm)
    canvas.setFont("Helvetica-Bold", 7.5)
    canvas.setFillColor(SLATE)
    canvas.drawString(document.leftMargin, height - 11 * mm, "TRACEBYTE  |  DF-PBL-016  |  SAP 500119665")
    canvas.line(document.leftMargin, 13 * mm, width - document.rightMargin, 13 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(document.leftMargin, 9 * mm, "Synthetic benchmark report - verify values against saved run artifacts")
    canvas.drawRightString(width - document.rightMargin, 9 * mm, f"Page {document.page}")
    canvas.restoreState()


def main():
    source_text = SOURCE.read_text(encoding="utf-8")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    styles = build_styles()
    doc = SimpleDocTemplate(str(OUTPUT), pagesize=A4,
        rightMargin=18 * mm, leftMargin=18 * mm, topMargin=21 * mm, bottomMargin=20 * mm,
        title="TraceByte - Signature Carving Evaluation", author="Digital Forensics PBL - DF-PBL-016",
        subject="Controlled synthetic file carving experiment")
    story = parse_markdown(source_text, styles, A4[0] - 36 * mm)
    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    print(f"Created {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
