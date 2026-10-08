"""PDF rendering for the single predefined certificate template."""
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


@dataclass(frozen=True)
class CertificateData:
    certificate_id: str
    recipient_name: str
    course_title: str
    issuer_name: str
    issue_date: date


def _fit_font_size(text: str, font: str, max_size: float, max_width: float, min_size: float = 12) -> float:
    """Shrink font until text fits the available width."""
    size = max_size
    while size > min_size and stringWidth(text, font, size) > max_width:
        size -= 1
    return size


def generate_certificate(data: CertificateData, output_path: Path) -> None:
    """Render a certificate PDF. Writes to a temp file then renames so a crash
    never leaves a half-written PDF at the final path."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(".pdf.tmp")

    width, height = landscape(A4)
    cx = width / 2
    c = canvas.Canvas(str(tmp_path), pagesize=(width, height))
    c.setTitle(f"Certificate - {data.recipient_name}")

    # Double border
    c.setStrokeColor(colors.HexColor("#1f3a5f"))
    c.setLineWidth(6)
    c.rect(25, 25, width - 50, height - 50)
    c.setLineWidth(1.5)
    c.rect(40, 40, width - 80, height - 80)

    usable = width - 160
    c.setFillColor(colors.HexColor("#1f3a5f"))
    c.setFont("Times-Bold", 40)
    c.drawCentredString(cx, height - 130, "CERTIFICATE OF COMPLETION")

    c.setFillColor(colors.HexColor("#555555"))
    c.setFont("Times-Italic", 16)
    c.drawCentredString(cx, height - 185, "This is to certify that")

    name_size = _fit_font_size(data.recipient_name, "Times-BoldItalic", 38, usable)
    c.setFillColor(colors.black)
    c.setFont("Times-BoldItalic", name_size)
    c.drawCentredString(cx, height - 250, data.recipient_name)
    c.setLineWidth(0.8)
    c.line(cx - usable / 3, height - 260, cx + usable / 3, height - 260)

    c.setFillColor(colors.HexColor("#555555"))
    c.setFont("Times-Italic", 16)
    c.drawCentredString(cx, height - 300, "has successfully completed")

    course_size = _fit_font_size(data.course_title, "Times-Bold", 26, usable)
    c.setFillColor(colors.HexColor("#1f3a5f"))
    c.setFont("Times-Bold", course_size)
    c.drawCentredString(cx, height - 345, data.course_title)

    # Footer: date (left), issuer (right)
    c.setFillColor(colors.black)
    c.setFont("Times-Roman", 14)
    c.drawString(90, 100, data.issue_date.strftime("%d %B %Y"))
    c.line(90, 118, 250, 118)
    c.setFont("Times-Italic", 11)
    c.drawString(90, 85, "Date of issue")

    issuer_size = _fit_font_size(data.issuer_name, "Times-Roman", 14, 250, 9)
    c.setFont("Times-Roman", issuer_size)
    c.drawRightString(width - 90, 100, data.issuer_name)
    c.line(width - 250, 118, width - 90, 118)
    c.setFont("Times-Italic", 11)
    c.drawRightString(width - 90, 85, "Issued by")

    c.setFillColor(colors.HexColor("#888888"))
    c.setFont("Helvetica", 8)
    c.drawCentredString(cx, 55, f"Certificate ID: {data.certificate_id}")

    c.showPage()
    c.save()
    os.replace(tmp_path, output_path)
