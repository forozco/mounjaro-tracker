"""Farmacias San Pablo (SAP Commerce). Su API bloquea peticiones directas (Akamai), así que
se llama desde dentro de la página con el navegador real."""
from ..browser import Browser
from ..products import Product, classify

BASE = "https://www.farmaciasanpablo.com.mx"
API = "https://api.farmaciasanpablo.com.mx/rest/v2/fsp"

FETCH_JS = """async (url) => { const r = await fetch(url); return [r.status, r.ok ? await r.json() : null]; }"""


def _image_urls(obj) -> list[str]:
    """Todas las URLs de imagen en formato grande (zoom/product) dentro del JSON."""
    out = []
    if isinstance(obj, list):
        for x in obj:
            out += _image_urls(x)
    elif isinstance(obj, dict):
        if obj.get("url") and obj.get("format") in ("zoom", "superZoom", "product", None):
            out.append(obj["url"])
        for v in obj.values():
            if isinstance(v, (list, dict)):
                out += _image_urls(v)
    return out


async def search(br: Browser) -> list[Product]:
    page = await br.page()
    try:
        _, bloqueado = await br.goto_ok(page, BASE + "/", 5000)
        if bloqueado:
            raise RuntimeError("el sitio respondió con bloqueo o página de error")
        found: dict[str, Product] = {}
        for q in ("mounjaro", "tirzepatida"):
            status, data = await page.evaluate(
                FETCH_JS, f"{API}/products/search?query={q}&fields=FULL&lang=es_MX&curr=MXN&pageSize=50")
            if status != 200 or not data:
                raise RuntimeError(f"API búsqueda San Pablo respondió {status}")
            for p in data.get("products", []):
                if p["code"] in found or not classify(p["name"], p.get("url", "")):
                    continue
                code = p["code"]
                status, det = await page.evaluate(FETCH_JS, f"{API}/products/{code}?fields=FULL&lang=es_MX&curr=MXN")
                det = det or {}
                imgs = [u if u.startswith("http") else BASE + u
                        for u in _image_urls([det.get("galleryImages"), det.get("images"), det.get("extraImages"), p.get("images")])]
                stock = (det.get("stock") or {}).get("stockLevelStatus")
                price = (det.get("price") or p.get("price") or {}).get("value")
                base = (det.get("basePrice") or p.get("basePrice") or {}).get("value")
                found[code] = Product(
                    pharmacy="sanpablo",
                    sku=code,
                    name=p["name"],
                    url=BASE + p["url"],
                    online_price=price,
                    list_price=max(filter(None, [price, base]), default=None),
                    in_stock=None if stock is None else stock != "outOfStock",
                    images=list(dict.fromkeys(imgs)),
                    image_tokens=[code.lstrip("0")],
                )
        return list(found.values())
    finally:
        await page.close()
