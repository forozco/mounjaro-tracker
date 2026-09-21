"""Farmacias Guadalajara y YZA (Salesforce Commerce Cloud): se usa su buscador en el navegador."""
from urllib.parse import quote_plus

from ..browser import SFCC_TILES_JS, Browser
from ..products import Product

SITES = {
    "guadalajara": "https://www.farmaciasguadalajara.com/buscar/?q={q}",
    "yza": "https://www.yza.mx/busqueda?q={q}",
}


def _tokens(pharmacy: str, pid: str) -> list[str]:
    if pharmacy == "yza":
        return [pid.split("_")[-1]]  # MXYZ_7501082243727 -> EAN en el nombre de la imagen
    return [f"/{pid}_", f"{pid}_"]


async def search(br: Browser, pharmacy: str, terms=("mounjaro kwikpen", "mounjaro")) -> list[Product]:
    page = await br.page()
    found: dict[str, Product] = {}
    try:
        for q in terms:
            _, bloqueado = await br.goto_ok(page, SITES[pharmacy].format(q=quote_plus(q)), 7000)
            if bloqueado:
                raise RuntimeError("el buscador respondió con bloqueo o página de error")
            for t in await page.evaluate(SFCC_TILES_JS):
                if not t.get("pid") or t["pid"] in found or not t.get("href"):
                    continue
                vals = t.get("values") or []
                found[t["pid"]] = Product(
                    pharmacy=pharmacy,
                    sku=t["pid"],
                    name=" ".join(t["name"].split()),
                    url=t["href"],
                    online_price=min(vals) if vals else None,
                    list_price=max(vals) if vals else None,
                    listing_text=t.get("text") or [],
                    image_tokens=_tokens(pharmacy, t["pid"]),
                )
        return list(found.values())
    finally:
        await page.close()
