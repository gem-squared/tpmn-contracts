"""
generate_pdfs.py — Convert all .txt source documents in synthetic data/documents/ to PDFs.
Uses reportlab to produce realistic monospaced medical documents.
"""
import os
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER

BASE_DIR = Path(r"c:\Users\Lee023\OneDrive - National University of Singapore\Desktop\Project\tpmn-contracts\health-insurance-claim\synthetic data\documents")

HEADER_COLORS = {
    "medical_bill": colors.HexColor("#0d4f8b"),
    "discharge_summary": colors.HexColor("#2e6b3e"),
    "pre_auth_approval": colors.HexColor("#7b2d00"),
}

def txt_to_pdf(txt_path: Path, pdf_path: Path):
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=20*mm,
        rightMargin=20*mm,
        topMargin=18*mm,
        bottomMargin=18*mm,
    )

    doc_type = txt_path.stem  # e.g. "medical_bill"
    header_color = HEADER_COLORS.get(doc_type, colors.HexColor("#1a1a2e"))

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "DocTitle",
        fontName="Courier-Bold",
        fontSize=11,
        textColor=colors.white,
        backColor=header_color,
        leading=18,
        spaceAfter=2*mm,
        spaceBefore=0,
        leftIndent=4*mm,
        rightIndent=4*mm,
    )

    mono_style = ParagraphStyle(
        "Mono",
        fontName="Courier",
        fontSize=8.5,
        leading=12,
        spaceAfter=0,
        spaceBefore=0,
        textColor=colors.HexColor("#1a1a1a"),
    )

    bold_style = ParagraphStyle(
        "MonoBold",
        fontName="Courier-Bold",
        fontSize=8.5,
        leading=12,
        spaceAfter=0,
        spaceBefore=0,
        textColor=colors.HexColor("#1a1a1a"),
    )

    content = txt_path.read_text(encoding="utf-8")
    lines = content.split("\n")

    story = []
    first_line = True

    for line in lines:
        stripped = line.rstrip()

        if first_line and stripped:
            # First non-empty line becomes the coloured header
            story.append(Paragraph(f"&nbsp;&nbsp;{stripped}", title_style))
            story.append(Spacer(1, 3*mm))
            first_line = False
            continue

        if set(stripped) <= {"=", "-", " "} and len(stripped) > 4:
            story.append(HRFlowable(
                width="100%",
                thickness=0.5,
                color=header_color,
                spaceAfter=1*mm,
                spaceBefore=1*mm,
            ))
            continue

        # Bold lines: lines ending with colon or all-caps short labels
        escaped = stripped.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if not escaped:
            story.append(Spacer(1, 2*mm))
        elif escaped.endswith(":") or (escaped.isupper() and len(escaped) < 40):
            story.append(Paragraph(escaped, bold_style))
        else:
            story.append(Paragraph(escaped, mono_style))

    doc.build(story)
    print(f"  [OK]  {pdf_path.relative_to(BASE_DIR.parent.parent)}")


def main():
    print(f"\nGenerating PDFs from .txt source documents in:\n  {BASE_DIR}\n")
    count = 0
    for txt_file in sorted(BASE_DIR.rglob("*.txt")):
        pdf_file = txt_file.with_suffix(".pdf")
        txt_to_pdf(txt_file, pdf_file)
        count += 1
    print(f"\nDone — {count} PDFs generated.")


if __name__ == "__main__":
    main()
