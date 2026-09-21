"""OCR de imágenes de producto y banners (Tesseract, gratis).

Las promos suelen ir en texto blanco sobre recuadros de color, que Tesseract lee mal
en la imagen completa. Por eso se hacen varias pasadas:
  1. imagen completa
  2. imagen invertida (texto claro → oscuro)
  3. cada recuadro de color recortado por separado (así se leen los escalonados tipo
     "1ª compra 20% $4,778")
"""
import io
import os
import re
from pathlib import Path

import numpy as np
import pytesseract
from PIL import Image, ImageOps

_local_tessdata = Path(__file__).resolve().parent.parent / "tessdata"
if (_local_tessdata / "spa.traineddata").exists() and not os.environ.get("TESSDATA_PREFIX"):
    os.environ["TESSDATA_PREFIX"] = str(_local_tessdata)

MAX_SIDE = 2600
PRICE_RE = re.compile(r"(?:\$\s?(\d{1,2}[,.]?\d{3})|(?<![\d.,$])(\d{1,2},\d{3}))(?:[.,]\d{2})?")
PCT_RE = re.compile(r"(?<!\d)(\d{1,2})\s?%")


def _tess(img: Image.Image, psm: int) -> str:
    try:
        return pytesseract.image_to_string(img, lang="spa", config=f"--psm {psm}")
    except pytesseract.TesseractError:
        return ""


def _color_boxes(im: Image.Image) -> list[Image.Image]:
    """Encuentra franjas horizontales con recuadros de color saturado."""
    a = np.asarray(im.convert("RGB")).astype(np.int16)
    sat = (a.max(axis=2) - a.min(axis=2)) > 90
    h, w = sat.shape
    row_hits = sat[:, ::4].sum(axis=1)
    on = row_hits > max(10, int(0.05 * w / 4))
    boxes, start = [], None
    for y, v in enumerate(np.append(on, False)):
        if v and start is None:
            start = y
        elif not v and start is not None:
            if y - start >= max(25, int(0.025 * h)):
                band = sat[start:y]
                cols = np.where(band.sum(axis=0) > (y - start) // 8)[0]
                if len(cols):
                    boxes.append(im.crop((int(cols.min()), start, int(cols.max()) + 1, y)))
            start = None
    return boxes[:12]


def parse_prices(text: str) -> list[float]:
    out = []
    for a, b in PRICE_RE.findall(text):
        raw = (a or b).replace(",", "").replace(".", "")
        try:
            out.append(float(raw))
        except ValueError:
            pass
    return out


def parse_percents(text: str) -> list[int]:
    return [int(p) for p in PCT_RE.findall(text) if 0 < int(p) < 100]


def ocr_bytes(data: bytes, quick: bool = False) -> dict:
    """quick=True hace solo una pasada rápida (para filtrar banners sin gastar tiempo)."""
    im = Image.open(io.BytesIO(data))
    im = im.convert("RGB")
    limit = 1100 if quick else MAX_SIDE
    if max(im.size) > limit:
        im.thumbnail((limit, limit))
    if min(im.size) < 120:
        return {"text": "", "boxes": [], "prices": [], "percents": []}

    if quick:
        t = _tess(im, 11) + "\n" + _tess(ImageOps.invert(im.convert("L")), 11)
        return {"text": "\n".join(l.strip() for l in t.splitlines() if l.strip()),
                "boxes": [], "prices": parse_prices(t), "percents": parse_percents(t), "quick": True}

    full = _tess(im, 11)
    inv = _tess(ImageOps.invert(im.convert("L")), 11)
    box_texts = []
    for box in _color_boxes(im):
        if box.width < 700:  # ampliar recuadros chicos ayuda mucho al OCR
            box = box.resize((box.width * 2, box.height * 2), Image.LANCZOS)
        g = ImageOps.invert(box.convert("L")).point(lambda v: 255 if v > 110 else 0)
        t = _tess(g, 6).strip()
        if t:
            box_texts.append(" ".join(t.split()))

    text = "\n".join([full, inv, *box_texts])
    return {
        "text": "\n".join(l.strip() for l in text.splitlines() if l.strip()),
        "boxes": box_texts,
        "prices": parse_prices(text),
        "percents": parse_percents(text),
    }
