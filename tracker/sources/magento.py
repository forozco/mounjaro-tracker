"""Farmacias del Ahorro y Benavides (Magento): usan la misma API GraphQL que su buscador."""
import requests

from ..browser import UA
from ..products import Product

QUERY = """query($q: String!) {
  products(search: $q, pageSize: 60) {
    items {
      name sku url_key url_suffix stock_status
      media_gallery { url position disabled }
      price_range { minimum_price { regular_price { value } final_price { value } } }
    }
  }
}"""

BASES = {"ahorro": "https://www.fahorro.com", "benavides": "https://www.benavides.com.mx"}


def search(pharmacy: str, terms=("mounjaro", "mounjaro kwikpen", "tirzepatida")) -> list[Product]:
    base = BASES[pharmacy]
    found: dict[str, Product] = {}
    for q in terms:
        r = requests.post(f"{base}/graphql", json={"query": QUERY, "variables": {"q": q}},
                          headers={"User-Agent": UA, "Content-Type": "application/json", "Store": "default"}, timeout=45)
        r.raise_for_status()
        data = r.json()
        if data.get("errors"):
            raise RuntimeError(data["errors"][0].get("message"))
        for it in data["data"]["products"]["items"]:
            if it["sku"] in found:
                continue
            pr = it["price_range"]["minimum_price"]
            gallery = sorted((m for m in it.get("media_gallery") or [] if not m.get("disabled")),
                             key=lambda m: m.get("position") or 0)
            found[it["sku"]] = Product(
                pharmacy=pharmacy,
                sku=it["sku"],
                name=it["name"],
                url=f"{base}/{it['url_key']}{it.get('url_suffix') or ''}",
                online_price=pr["final_price"]["value"],
                list_price=pr["regular_price"]["value"],
                in_stock=it["stock_status"] == "IN_STOCK",
                images=[m["url"] for m in gallery],
                image_tokens=[it["sku"]],
            )
    return list(found.values())
