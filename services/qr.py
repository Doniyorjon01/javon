"""
QR codes, shelf labels and the store poster
===========================================
Plan: "Javon va vitrina uchun QR — kichik do'kon ham butun katalogini ko'rsata
oladi". Three things a store prints:

    store QR      the store's site (SVG for designers, PNG for chats)
    poster        A4: store name, a big QR, "scan to see our catalogue"
    shelf labels  A4 sticker sheet, 3 x 8 labels of 70 x 37 mm (the common
                  "24 per sheet" size): QR to the book's page, title, author, price

Links carry ?src=qr so the frontend can count QR visits later.

QR codes are made with segno (pure Python, no Pillow needed) and drawn into the
PDF as vector squares, so they stay sharp at any printer resolution. Text needs
a font with Uzbek and Russian letters: DejaVu Sans (Debian package
fonts-dejavu-core, installed in the Dockerfile; present on most Linux desktops).
Without it the PDF still builds with Helvetica, and Cyrillic shows as boxes; a
warning is logged once.

Everything here is CPU work: routes call it through asyncio.to_thread.
"""

import io
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import segno
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from config import settings
from utils.i18n import Lang
from utils.money import format_som

logger = logging.getLogger(__name__)

QR_SOURCE = "qr"
MAX_LABELS = 240  # 10 sheets per request

_FONT_DIRS = (
    "/usr/share/fonts/truetype/dejavu",  # Debian, Ubuntu (and our Docker image)
    "/usr/share/fonts/dejavu",  # Fedora
    "/usr/share/fonts/TTF",  # Arch
)


# --------------------------------------------------------------------------- #
# Links and QR images
# --------------------------------------------------------------------------- #
def store_url(slug: str) -> str:
    return settings.STOREFRONT_URL_TEMPLATE.format(slug=slug)


def book_url(slug: str, book_id: int) -> str:
    """The book's page on the store's site; the frontend serves /kitob/<book id>."""
    return f"{store_url(slug).rstrip('/')}/kitob/{book_id}"


def tracked(url: str) -> str:
    return f"{url}{'&' if '?' in url else '?'}src={QR_SOURCE}"


def qr_svg(data: str) -> bytes:
    out = io.BytesIO()
    segno.make(data, error="m").save(out, kind="svg", scale=10, border=2, xmldecl=False)
    return out.getvalue()


def qr_png(data: str) -> bytes:
    out = io.BytesIO()
    segno.make(data, error="m").save(out, kind="png", scale=10, border=2)
    return out.getvalue()


# --------------------------------------------------------------------------- #
# Fonts
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Fonts:
    regular: str
    bold: str
    unicode: bool  # False: Helvetica fallback, Latin only


@lru_cache(maxsize=1)
def fonts() -> Fonts:
    for folder in _FONT_DIRS:
        regular, bold = Path(folder, "DejaVuSans.ttf"), Path(folder, "DejaVuSans-Bold.ttf")
        if regular.is_file() and bold.is_file():
            pdfmetrics.registerFont(TTFont("DejaVuSans", str(regular)))
            pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", str(bold)))
            return Fonts("DejaVuSans", "DejaVuSans-Bold", unicode=True)
    logger.warning("DejaVu Sans not found: PDF labels fall back to Helvetica (no Cyrillic)")
    return Fonts("Helvetica", "Helvetica-Bold", unicode=False)


def _plain(value: str, f: Fonts) -> str:
    """Helvetica lacks the narrow no-break space and the Uzbek modifier apostrophes
    (U+02BB, U+02BC): swap them for plain look-alikes."""
    if f.unicode:
        return value
    return value.replace(" ", " ").replace("ʻ", "'").replace("ʼ", "'")  # noqa: RUF001


# --------------------------------------------------------------------------- #
# Drawing
# --------------------------------------------------------------------------- #
def _draw_qr(canvas: Canvas, data: str, x: float, y: float, size: float) -> None:
    """A QR code as filled squares (runs of dark modules merged per row): vector, sharp."""
    matrix = segno.make(data, error="m").matrix
    count = len(matrix)
    module = size / count
    canvas.setFillColorRGB(0, 0, 0)
    for row_index, row in enumerate(matrix):
        top = y + size - (row_index + 1) * module
        start = None
        for col_index, dark in enumerate([*row, 0]):
            if dark and start is None:
                start = col_index
            elif not dark and start is not None:
                canvas.rect(x + start * module, top, (col_index - start) * module, module, stroke=0, fill=1)
                start = None


def _lines(text: str, font: str, size: float, width: float, max_lines: int) -> list[str]:
    lines = simpleSplit(text, font, size, width) or [""]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and pdfmetrics.stringWidth(last + "…", font, size) > width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


@dataclass(frozen=True, slots=True)
class Label:
    url: str
    title: str
    authors: str
    price: int  # tiyin


LABEL_COLUMNS, LABEL_ROWS = 3, 8
LABEL_W, LABEL_H = A4[0] / LABEL_COLUMNS, A4[1] / LABEL_ROWS  # 70 x 37.1 mm
PAD = 3 * mm
QR_SIZE = LABEL_H - 2 * PAD


def labels_pdf(labels: list[Label], store_name: str, lang: Lang) -> bytes:
    f = fonts()
    out = io.BytesIO()
    canvas = Canvas(out, pagesize=A4, pageCompression=1)
    canvas.setTitle(f"{store_name} — QR")
    per_page = LABEL_COLUMNS * LABEL_ROWS
    text_x_offset = PAD + QR_SIZE + 2 * mm
    text_width = LABEL_W - text_x_offset - PAD
    for index, label in enumerate(labels):
        if index and index % per_page == 0:
            canvas.showPage()
        slot = index % per_page
        col, row = slot % LABEL_COLUMNS, slot // LABEL_COLUMNS
        x, y = col * LABEL_W, A4[1] - (row + 1) * LABEL_H
        _draw_qr(canvas, label.url, x + PAD, y + PAD, QR_SIZE)

        tx, cursor = x + text_x_offset, y + LABEL_H - PAD - 8
        canvas.setFont(f.bold, 8)
        for line in _lines(_plain(label.title, f), f.bold, 8, text_width, 3):
            canvas.drawString(tx, cursor, line)
            cursor -= 9.5
        canvas.setFont(f.regular, 6.5)
        for line in _lines(_plain(label.authors, f), f.regular, 6.5, text_width, 1):
            canvas.drawString(tx, cursor - 1, line)
        price = _plain(format_som(label.price, lang), f)
        size = 10.5
        while size > 6 and pdfmetrics.stringWidth(price, f.bold, size) > text_width:
            size -= 0.5  # "1 590 000 so'm" must stay inside the sticker
        canvas.setFont(f.bold, size)
        canvas.drawString(tx, y + PAD + 9, price)
        canvas.setFont(f.regular, 5.5)
        canvas.drawString(tx, y + PAD + 1, _lines(_plain(store_name, f), f.regular, 5.5, text_width, 1)[0])
    canvas.save()
    return out.getvalue()


POSTER_TEXT = {
    Lang.uz: (
        "Katalogimiz telefoningizda",
        "Kamerani QR kodga qarating: kitoblarni ko'ring va buyurtma bering.",
    ),
    Lang.ru: ("Наш каталог в вашем телефоне", "Наведите камеру на QR-код: смотрите книги и заказывайте."),
    Lang.en: ("Our catalogue on your phone", "Point your camera at the QR code to browse and order books."),
}


def poster_pdf(store_name: str, url: str, lang: Lang) -> bytes:
    f = fonts()
    out = io.BytesIO()
    canvas = Canvas(out, pagesize=A4, pageCompression=1)
    canvas.setTitle(store_name)
    width, height = A4
    center = width / 2
    headline, hint = POSTER_TEXT[lang]

    canvas.setFont(f.bold, 30)
    y = height - 40 * mm
    for line in _lines(_plain(store_name, f), f.bold, 30, width - 40 * mm, 2):
        canvas.drawCentredString(center, y, line)
        y -= 34
    canvas.setFont(f.regular, 17)
    canvas.drawCentredString(center, y - 6, _plain(headline, f))

    size = 120 * mm
    _draw_qr(canvas, url, center - size / 2, 72 * mm, size)

    canvas.setFont(f.regular, 11)
    for i, line in enumerate(_lines(_plain(hint, f), f.regular, 11, width - 50 * mm, 2)):
        canvas.drawCentredString(center, 60 * mm - i * 14, line)
    canvas.setFont(f.bold, 13)
    canvas.drawCentredString(center, 44 * mm, url.split("?")[0].removeprefix("https://").rstrip("/"))
    canvas.setFont(f.regular, 8)
    canvas.setFillColorRGB(0.45, 0.45, 0.45)
    canvas.drawCentredString(center, 15 * mm, "javon.uz")
    canvas.save()
    return out.getvalue()
