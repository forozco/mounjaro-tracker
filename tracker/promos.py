"""Convierte texto de promociones (página, buscador, OCR de imágenes) en promos estructuradas."""
import re
from dataclasses import asdict, dataclass

from . import config
from .ocr import parse_percents, parse_prices


@dataclass
class Promo:
    kind: str  # pct | tiers | buy_n_get_1 | nxm | monedero | gift | image_price | limit | msi
    label: str
    source: str  # página | buscador | imagen
    pct: float | None = None
    tiers: list[float] | None = None
    n: int | None = None
    m: int | None = None
    price: float | None = None
    condition: str | None = None
    canal: str | None = None  # dónde aplica la promo: en línea, app, tienda física…
    raw: str = ""

    def to_dict(self):
        return {k: v for k, v in asdict(self).items() if v not in (None, "", [])}


_CONDITIONS = [
    (re.compile(r"enlace\s*(eli[\s-]*)?lilly|tarjeta del programa", re.I), "Tarjeta Enlace Lilly"),
    (re.compile(r"recompensa", re.I), "Tarjeta Benavides Recompensas"),
    (re.compile(r"monedero", re.I), "Monedero de la farmacia"),
    (re.compile(r"club\s*salud", re.I), "Club Salud San Pablo"),
    (re.compile(r"cu[ií]date\s*mucho", re.I), "Tarjeta Cuídate Mucho (YZA)"),
    (re.compile(r"tarjeta|lealtad|socio", re.I), "Tarjeta de lealtad de la farmacia"),
    (re.compile(r"cup[oó]n|c[oó]digo", re.I), "Cupón / código"),
    (re.compile(r"\bapp\b|aplicaci[oó]n|en l[ií]nea", re.I), "Compra en línea / app"),
]

_CANALES = [
    (re.compile(r"(exclusiv|s[oó]lo|solo|[uú]nicamente)[^.]{0,25}(l[ií]nea|web|sitio)[^.]{0,15}(y|e|\+|/)[^.]{0,8}app", re.I), "En línea y app"),
    (re.compile(r"(exclusiv|s[oó]lo|solo|[uú]nicamente)[^.]{0,25}\bapp\b", re.I), "Solo en la app"),
    (re.compile(r"(exclusiv|s[oó]lo|solo|[uú]nicamente)[^.]{0,25}(l[ií]nea|tienda en l[ií]nea|web)", re.I), "Solo en línea"),
    (re.compile(r"(s[oó]lo|solo|[uú]nicamente|exclusiv)[^.]{0,25}(tienda f[ií]sica|sucursal|mostrador)", re.I), "Solo en sucursal"),
    (re.compile(r"recoge|recolecta|pickup|pick\s*up|click\s*(and|&|y)\s*collect|smart\s*(and|&)\s*collect", re.I), "Recoger en sucursal"),
    (re.compile(r"en l[ií]nea y app|l[ií]nea\s*/\s*app", re.I), "En línea y app"),
    # el OCR a veces solo alcanza "EXCLUSIVO EN…" del sello; se marca para revisar
    (re.compile(r"exclusiv\w*\s+en\b(?!\s*(sucursal|tienda))", re.I), "En línea/app (por confirmar en la imagen)"),
]


def canal_of(text: str) -> str | None:
    flat = " ".join(text.split())  # el OCR parte las frases en varias líneas
    for rx, label in _CANALES:
        if rx.search(flat):
            return label
    return None


_ACUMULA = re.compile(r"acumula\s*(\d+)\s*(?:piezas?\s*)?y\s*(?:el|la|ll[eé]vate|lleva|recibe|obt[eé]n)?\s*(?:\d+\s*(?:[°ºo]|er|ra|ta|va)?\s*)?(?:pieza\s*)?(?:es\s*)?gratis", re.I)
_NXM = re.compile(r"(?<![\d.,])([2-6])\s*[xX×]\s*([1-5])(?![\d.,]|\s*m[lg])")
_PCT_DISC = re.compile(r"(\d{1,2})\s?%\s*(?:de\s*)?(?:desc|dcto|dto|descuento|off|menos|ahorro)", re.I)
_PCT_MONEDERO = re.compile(r"(\d{1,2})\s?%\s*(?:de\s*)?(?:en\s*)?(?:monedero|bonificaci|cashback|puntos)", re.I)
_GIFT = re.compile(r"agujas?[^.\n]{0,60}gratis|gratis[^.\n]{0,60}agujas?", re.I)
_LIMIT = re.compile(r"(?:l[ií]mite|m[aá]ximo)[^.\n]{0,30}?(\d+)\s*piezas?", re.I)
_MSI = re.compile(r"(\d{1,2})\s*(?:meses\s*sin\s*intereses|msi)", re.I)
_COMPRA = re.compile(r"compra", re.I)
_ORDINAL_COMPRA = re.compile(r"(\d)\s*[a-zº°]{0,3}\s*compra", re.I)
# "1ª compra hasta un 20%, 2ª compra hasta un 25%…": escalonado escrito en texto
_TIER_TXT = re.compile(r"(\d)\s*[ªaº°]?\s*compra[^%.\d]{0,30}?(\d{1,2})\s?%", re.I)
_VIGENCIA = re.compile(r"(?:v[aá]lid[ao]s?|vigencia|promoci[oó]n v[aá]lida)[^.\n]{0,15}?(del?\s*\d{1,2}[^.\n]{0,40}?(?:al|hasta)\s*(?:el\s*)?\d{1,2}[^.\n]{0,25})", re.I)
# Un código de cupón trae letras Y dígitos (MOUNJARO40); así no se confunde con
# palabras de la frase ("cupón correspondiente…").
_CUPON = re.compile(r"\b([A-Z]{3,15}\d{1,3})\b")
_CUPON_CTX = re.compile(r"cup[oó]n|c[oó]digo", re.I)


def condition_of(text: str) -> str | None:
    for rx, label in _CONDITIONS:
        if rx.search(text):
            return label
    return None


def buscar_cupon(text: str) -> str | None:
    """Código de cupón (MOUNJARO40). Pide contexto de 'cupón/código' para no confundirse."""
    if not _CUPON_CTX.search(text):
        return None
    for m in _CUPON.finditer(text):
        code = m.group(1)
        if code.startswith("HP") or code in ("MXN",):
            continue
        # el OCR a veces se come la primera letra: OUNJARO40 → MOUNJARO40
        if "UNJARO" in code and not code.startswith("MOUNJARO"):
            code = "MOUNJARO" + code.split("UNJARO")[-1]
        return code
    return None


def parse_text(lines: list[str], source: str) -> list[Promo]:
    promos: list[Promo] = []
    joined = "\n".join(lines)
    context_cond = condition_of(joined)
    context_canal = canal_of(joined)
    for line in lines:
        cond = condition_of(line) or (context_cond if source != "buscador" else None)
        canal = canal_of(line) or context_canal
        if m := _ACUMULA.search(line):
            n = int(m.group(1))
            promos.append(Promo("buy_n_get_1", f"Acumula {n} y el siguiente gratis", source, n=n, condition=cond, canal=canal, raw=line))
        for a, b in _NXM.findall(line):
            if int(a) > int(b):
                promos.append(Promo("nxm", f"{a}x{b}", source, n=int(a), m=int(b), condition=cond, canal=canal, raw=line))
        if m := _PCT_MONEDERO.search(line):
            promos.append(Promo("monedero", f"{m.group(1)}% en monedero", source, pct=float(m.group(1)), condition=cond, canal=canal, raw=line))
        elif m := _PCT_DISC.search(line):
            promos.append(Promo("pct", f"{m.group(1)}% de descuento", source, pct=float(m.group(1)), condition=cond, canal=canal, raw=line))
        if _GIFT.search(line):
            promos.append(Promo("gift", "Agujas de regalo", source, condition=cond, canal=canal, raw=line))
        if m := _LIMIT.search(line):
            promos.append(Promo("limit", f"Límite {m.group(1)} piezas", source, n=int(m.group(1)), canal=canal, raw=line))
        if m := _VIGENCIA.search(line):
            promos.append(Promo("vigencia", "Vigencia: " + " ".join(m.group(1).split())[:60], source, raw=line))
        if m := _MSI.search(line):
            promos.append(Promo("msi", f"{m.group(1)} meses sin intereses", source, n=int(m.group(1)), raw=line))
    # Escalonado escrito en el texto: manda sobre los % sueltos de esas frases, que
    # de otro modo se leerían como "35% en todas las compras".
    niveles = {}
    for n, pct in _TIER_TXT.findall(" ".join(joined.split())):
        niveles.setdefault(int(n), float(pct))
    if len(niveles) >= 2 and sorted(niveles) == list(range(1, len(niveles) + 1)):
        tiers = [niveles[k] for k in sorted(niveles)]
        if tiers == sorted(tiers):
            promos = [x for x in promos if not (x.kind == "pct" and _COMPRA.search(x.raw))]
            promos.append(Promo("tiers", "Escalonado por compra: " + " → ".join(f"{t:g}%" for t in tiers), source,
                                tiers=tiers, condition=context_cond, canal=context_canal, raw=joined[:300]))
    if cup := buscar_cupon(joined):
        promos.append(Promo("cupon", f"Cupón {cup}", source, condition=f"Cupón {cup}",
                            canal=context_canal, raw=cup))

    # Bloque tipo "Promociones con tu tarjeta / 20% de desc" en líneas separadas
    if not any(p.kind == "pct" for p in promos):
        for i, line in enumerate(lines):
            if re.fullmatch(r"\s*\d{1,2}\s?%\s*(de\s*)?desc\w*\.?\s*", line, re.I):
                pct = float(parse_percents(line)[0])
                ctx = " ".join(lines[max(0, i - 2): i + 1])
                promos.append(Promo("pct", f"{pct:g}% de descuento", source, pct=pct, condition=condition_of(ctx), canal=canal_of(ctx) or context_canal, raw=ctx))
    return promos


def _plausible_prices(prices: list[float], ref_price: float | None) -> list[float]:
    """Precios de la imagen que pueden ser el precio promocional del producto.

    El OCR suele pegar el signo "$" como un dígito ("$5,159" → 35159 o 55159) o
    juntar los centavos. Si el número sale imposible (más caro que el precio de
    lista), se intenta reparar quitando el primer dígito o los centavos.
    """
    if not ref_price:
        return []
    lo, hi = ref_price * (1 - config.MAX_SANE_DISCOUNT), ref_price * 0.995
    out = []
    for p in prices:
        if lo <= p < hi:
            out.append(p)
            continue
        if p < ref_price:
            continue
        s = str(int(p))
        for reparado in ([float(s[1:])] if len(s) >= 5 else []) + ([float(s[:-2])] if len(s) >= 6 else []):
            if lo <= reparado < hi:
                out.append(reparado)
                break
    return out


def _sane_tiers(tiers: list[float]) -> list[float]:
    """Un escalonado creíble: entre 2 y 6 niveles, crecientes y dentro de rango."""
    vals = sorted({float(t) for t in tiers if 3 <= t <= config.MAX_SANE_DISCOUNT * 100})
    return vals[:6] if len(vals) >= 2 else []


def parse_image(ocr: dict, ref_price: float | None) -> list[Promo]:
    """Promos a partir del OCR de una imagen del producto."""
    text = ocr.get("text", "")
    if not text:
        return []
    promos = parse_text([l for l in text.splitlines()], "imagen")
    cond = condition_of(text)
    canal = canal_of(text)

    # Escalonado: varios recuadros de color con % y la palabra "compra"
    box_pcts = [parse_percents(b) for b in ocr.get("boxes", [])]
    box_pcts = [p[0] for p in box_pcts if p]
    compras = len(_COMPRA.findall(text))
    prices = _plausible_prices(ocr.get("prices", []), ref_price)
    tiers = None
    if compras >= 1 and len(prices) >= 2:
        # Más confiable que leer los %: deducir el descuento de los precios impresos
        tiers = [round((1 - p / ref_price) * 100, 1) for p in sorted(set(prices), reverse=True)]
    elif len(box_pcts) >= 2 and compras >= 1:
        tiers = box_pcts
    elif compras >= 2:
        pcts = sorted(set(parse_percents(text)))
        if len(pcts) >= 2:
            tiers = pcts[: max(2, compras)]
    if tiers:
        tiers = _sane_tiers(tiers)
        if len(tiers) >= 2:
            promos = [p for p in promos if p.kind != "pct"]
            label = "Escalonado por compra: " + " → ".join(f"{t:g}%" for t in tiers)
            promos.append(Promo("tiers", label, "imagen", tiers=tiers, condition=cond, canal=canal, raw=" | ".join(ocr.get("boxes", []))))
    elif not any(p.kind in ("pct", "nxm", "buy_n_get_1", "monedero") for p in promos):
        pcts = [p for p in parse_percents(text) if p / 100 <= config.MAX_SANE_DISCOUNT]
        if pcts and re.search(r"desc|dcto|ahorra|precio|promo|oferta", text, re.I):
            promos.append(Promo("pct", f"{max(pcts)}% de descuento (imagen)", "imagen", pct=float(max(pcts)), condition=cond, canal=canal, raw=text[:200]))

    cupon = buscar_cupon(text)
    if cupon:
        cond = f"Cupón {cupon}"
        for pr in promos:
            if pr.kind in ("pct", "tiers", "image_price") and pr.condition in (None, "Cupón / código"):
                pr.condition = cond

    # Un solo precio dentro de una imagen de escalonado: aplica hasta esa compra,
    # no hoy. Ej.: "4a COMPRA … $3,520".
    ordinales = [int(n) for n in _ORDINAL_COMPRA.findall(text) if 1 < int(n) <= 6]
    if prices and not tiers and ordinales:
        n = max(ordinales)
        promos.append(Promo("tier_at", f"{n}ª compra: ${min(prices):,.0f}", "imagen", n=n, price=min(prices),
                            condition=cond, canal=canal, raw=", ".join(f"${c:,.0f}" for c in sorted(set(prices)))))
        prices = []

    # Precios escritos en la imagen que sean menores al precio en línea
    if prices and not tiers:
        promos.append(Promo("image_price", f"Precio en imagen desde ${min(prices):,.0f}" + (f" con cupón {cupon}" if cupon else ""), "imagen",
                            price=min(prices), condition=cond, canal=canal,
                            raw=", ".join(f"${c:,.0f}" for c in sorted(set(prices)))))
    return promos


def dedupe(promos: list[Promo]) -> list[Promo]:
    seen, out = set(), []
    for p in promos:
        key = (p.kind, p.pct, tuple(p.tiers or []), p.n, p.m, p.price and round(p.price), p.condition, p.canal)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out
