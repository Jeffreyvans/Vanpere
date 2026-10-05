"""QR codes (PNG/SVG) and printable PDF posters. Pure functions, no Django imports."""
import io

import qrcode
import segno
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4, A5
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

INK, GOLD, GOLD_DARK, IVORY = "#1B1A2E", "#C9A24B", "#8A6A1F", "#FAF7F2"
POSTER_SIZES = {"a4": A4, "a5": A5, "table": (100 * mm, 150 * mm)}


def qr_png(url: str) -> bytes:
    """Print-quality PNG (about 1100 px) with high error correction."""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=30, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color=INK, back_color="white").save(buf, "PNG")
    return buf.getvalue()


def qr_svg(url: str) -> bytes:
    buf = io.BytesIO()
    segno.make(url, error="h").save(buf, kind="svg", scale=10, border=4, dark=INK)
    return buf.getvalue()


def _centered(c, text, y, font, size, w):
    c.setFont(font, size)
    c.drawCentredString(w / 2, y, text)


def poster_pdf(name: str, url: str, size: str) -> bytes:
    """'Share the Moment' poster. size: a4, a5 or table (100x150 mm trim, no bleed)."""
    w, h = POSTER_SIZES[size]
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(w, h))
    c.setTitle("VanPere Digital poster")
    c.setFillColor(HexColor(IVORY))
    c.rect(0, 0, w, h, fill=1, stroke=0)
    c.setFillColor(HexColor(GOLD))
    c.rect(0, h - 0.012 * h, w, 0.012 * h, fill=1, stroke=0)
    margin = 0.09 * w
    y = h - 0.085 * h
    c.setFillColor(HexColor(INK))
    _centered(c, "VanPere Digital", y, "Times-Bold", w * 0.04, w)

    fs = w * 0.075
    lines = simpleSplit(name, "Times-Bold", fs, w - 2 * margin)
    while len(lines) > 2 and fs > w * 0.04:
        fs *= 0.92
        lines = simpleSplit(name, "Times-Bold", fs, w - 2 * margin)
    y -= 0.07 * h
    for line in lines[:3]:
        _centered(c, line, y, "Times-Bold", fs, w)
        y -= fs * 1.15
    c.setFillColor(HexColor(GOLD_DARK))
    y -= w * 0.01
    _centered(c, "Share the Moment", y, "Times-Italic", w * 0.06, w)

    side = w * 0.55
    qx, qy = (w - side) / 2, y - 0.04 * h - side
    c.setFillColor(white)
    c.rect(qx, qy, side, side, fill=1, stroke=0)
    matrix = segno.make(url, error="h").matrix
    n = len(matrix)
    m = side / (n + 8)
    c.setFillColor(HexColor(INK))
    for r, row in enumerate(matrix):
        for col, bit in enumerate(row):
            if bit:
                c.rect(qx + (col + 4) * m, qy + side - (r + 5) * m, m + 0.15, m + 0.15, fill=1, stroke=0)

    y = qy - 0.05 * h
    c.setFillColor(HexColor(INK))
    for line in simpleSplit("Scan, tap Share Your Photos, done", "Helvetica", w * 0.04, w - 2 * margin):
        _centered(c, line, y, "Helvetica", w * 0.04, w)
        y -= w * 0.05
    short = url.split("://", 1)[-1]
    sfs = w * 0.034
    while c.stringWidth(short, "Helvetica-Bold", sfs) > w - 2 * margin and sfs > 6:
        sfs *= 0.95
    _centered(c, short, y - w * 0.01, "Helvetica-Bold", sfs, w)
    c.setFillColor(HexColor("#4a4860"))
    _centered(c, "VanPere Digital", 0.04 * h, "Helvetica", w * 0.028, w)
    c.showPage()
    c.save()
    return buf.getvalue()
