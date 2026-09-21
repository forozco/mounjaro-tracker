"""Identificación de producto: ¿es Mounjaro KwikPen? ¿de qué dosis?"""
import re
from dataclasses import dataclass, field

_MOUNJARO = re.compile(r"mounjaro|tirzepatida", re.I)
_DOSE = re.compile(r"(\d{1,2}(?:[.,]\d)?)\s*mg", re.I)
# La KwikPen es multidosis de 0.6 ml por dosis (2.4 ml total). El frasco/vial es 0.5 ml.
_PEN = re.compile(r"kwik\s*pen|pluma|jeringa|prellenad|0[.,]6\s*ml|2[.,]4\s*ml|3\s*ml", re.I)
_VIAL = re.compile(r"frasco|[aá]mpula|vial|0[.,]5\s*ml", re.I)


@dataclass
class Product:
    pharmacy: str
    sku: str
    name: str
    url: str
    online_price: float | None
    list_price: float | None = None
    in_stock: bool | None = None
    images: list[str] = field(default_factory=list)
    listing_text: list[str] = field(default_factory=list)  # texto de la tarjeta en el buscador
    image_tokens: list[str] = field(default_factory=list)  # para reconocer imágenes de la galería en la página
    dose: str | None = None


def normalize_dose(value: str) -> str:
    v = float(value.replace(",", "."))
    return f"{v:g}"


def classify(name: str, url: str = "") -> str | None:
    """Regresa la dosis ("2.5", "5", ...) si es Mounjaro KwikPen; si no, None."""
    text = f"{name} {url.replace('-', ' ')}"
    if not _MOUNJARO.search(text):
        return None
    if _VIAL.search(name) or (not _PEN.search(text)):
        return None
    m = _DOSE.search(name)
    return normalize_dose(m.group(1)) if m else None
