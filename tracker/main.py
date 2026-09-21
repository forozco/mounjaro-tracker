"""Corrida completa: buscar → leer páginas e imágenes → evaluar valor → guardar → avisar."""
import asyncio
import hashlib
import io
import json
import os
import random
import re
import time
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config, notify, receta
from .browser import BANNERS_JS, PDP_JS, Browser
from PIL import Image

from .ocr import ocr_bytes
from .products import Product, classify
from .promos import Promo, canal_of, condition_of, dedupe, parse_image, parse_text
from .sources import magento, sanpablo, sfcc
from .value import evaluate, recommend

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS_DATA = ROOT / "docs" / "data"
DOCS_IMG = ROOT / "docs" / "img"
TZ = ZoneInfo("America/Mexico_City")
MAX_IMAGES_PER_PRODUCT = 8
OCR_CACHE_MAX = 600
# "Condición de Venta: Farmacia Receta No Obligatoria" es el dato bueno de la ficha;
# se revisa antes que cualquier otra mención de receta.
_RECETA_NO = re.compile(
    r"receta\s+no\s+obligatoria|no\s+requiere[^.]{0,20}receta|sin\s+receta|"
    r"venta\s+libre|no\s+necesitas[^.]{0,20}receta", re.I)
_RECETA_REQ = re.compile(
    r"receta\s+(m[eé]dica\s+)?(obligatoria|requerida|retenida|indispensable)|"
    r"(requiere|necesita|obligatoria|indispensable|sube|subir|adjunta|carga|presenta)[^.]{0,30}receta|"
    r"con\s+receta\s+m[eé]dica", re.I)


def log(*a):
    print(datetime.now(TZ).strftime("%H:%M:%S"), *a, flush=True)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def save_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1))


def _img_key(url: str) -> str:
    return re.sub(r"Fsp\d+Wx\d+H_", "", url.split("?")[0])


_IS_IMG = re.compile(r"\.(jpe?g|png|webp|avif|gif)(\?|$)|/image|/media/|demandware\.static|/dw/image", re.I)


def _normalize_img(pharmacy: str, url: str) -> str:
    if pharmacy == "guadalajara":
        return url.split("?")[0]  # sin ?w=80&h=80 → imagen completa
    return url


class Runner:
    def __init__(self):
        self.state = load_json(DATA / "state.json", {})
        self.ocr_cache: dict = self.state.setdefault("ocr_cache", {})
        self.errors: dict[str, str] = {}
        self.ocr_sem = asyncio.Semaphore(int(os.environ.get("OCR_WORKERS", "3")))
        self.visitadas: set[str] = set()  # farmacias cuyo home/buscador ya se visitó
        self.img_bytes: dict[str, bytes] = {}  # imágenes ya descargadas en esta corrida
        self.thumbs_usados: set[str] = set()

    async def ocr_url(self, br: Browser, url: str, quick: bool = False, referer: str | None = None) -> dict | None:
        key = _img_key(url) + ("#q" if quick else "")
        if key in self.ocr_cache:
            self.ocr_cache[key]["t"] = time.time()
            return self.ocr_cache[key]["r"]
        try:
            async with self.ocr_sem:  # limita descargas simultáneas: nada de ráfagas
                data = await br.fetch_bytes(url, referer)
                if not data:
                    return None
                if len(data) < 4_000_000:
                    self.img_bytes[_img_key(url)] = data
                res = await asyncio.to_thread(ocr_bytes, data, quick)
        except Exception as e:
            log("  OCR falló", url[:80], e)
            return None
        self.ocr_cache[key] = {"t": time.time(), "r": res}
        return res

    async def guardar_miniatura(self, br: Browser, url: str, referer: str | None = None) -> str | None:
        """Guarda la imagen en docs/img para que el dashboard no dependa de la farmacia:
        Guadalajara y San Pablo bloquean que sus imágenes se muestren desde otro sitio."""
        key = hashlib.sha1(_img_key(url).encode()).hexdigest()[:12]
        destino = DOCS_IMG / f"{key}.jpg"
        self.thumbs_usados.add(destino.name)
        rel = f"img/{key}.jpg"
        if destino.exists():
            return rel
        data = self.img_bytes.get(_img_key(url)) or await br.fetch_bytes(url, referer)
        if not data:
            return None
        try:
            def _guardar():
                im = Image.open(io.BytesIO(data))
                im = im.convert("RGB")
                im.thumbnail((640, 640))
                DOCS_IMG.mkdir(parents=True, exist_ok=True)
                im.save(destino, "JPEG", quality=78, optimize=True)
            await asyncio.to_thread(_guardar)
            return rel
        except Exception as e:
            log(f"  no se pudo guardar miniatura: {type(e).__name__}")
            return None

    def limpiar_miniaturas(self):
        """Borra las miniaturas que ya nadie usa."""
        if not DOCS_IMG.exists():
            return
        for f in DOCS_IMG.glob("*.jpg"):
            if f.name not in self.thumbs_usados:
                f.unlink(missing_ok=True)

    # ---------- productos ----------
    async def collect(self, br: Browser) -> list[Product]:
        products: list[Product] = []
        tasks = {
            "ahorro": lambda: asyncio.to_thread(magento.search, "ahorro"),
            "benavides": lambda: asyncio.to_thread(magento.search, "benavides"),
            "sanpablo": lambda: sanpablo.search(br),
            "guadalajara": lambda: sfcc.search(br, "guadalajara"),
            "yza": lambda: sfcc.search(br, "yza"),
        }
        only = [x for x in os.environ.get("ONLY", "").split(",") if x]
        orden = list(tasks.items())
        random.shuffle(orden)  # no visitar siempre en el mismo orden
        for ph, fn in orden:
            if only and ph not in only:
                continue
            for attempt in (1, 2):
                try:
                    found = await fn()
                    kept = []
                    for p in found:
                        dose = classify(p.name, p.url)
                        if dose in config.DOSES:
                            p.dose = dose
                            kept.append(p)
                    log(f"{ph}: {len(found)} resultados, {len(kept)} KwikPen de interés")
                    if not kept:
                        raise RuntimeError("no se encontró Mounjaro KwikPen en el buscador")
                    products += kept
                    self.errors.pop(ph, None)
                    break
                except Exception as e:
                    self.errors[ph] = f"{type(e).__name__}: {e}"
                    log(f"{ph}: ERROR intento {attempt}: {e}")
                    if attempt == 1:
                        await asyncio.sleep(5)
        return products

    async def entrar_al_sitio(self, br: Browser, pharmacy: str) -> str | None:
        """Pasa por el home y el buscador antes de la ficha: así la visita tiene cookies
        y referer, como la de una persona, y no la de un enlace directo."""
        if pharmacy in self.visitadas:
            return config.BUSCADORES.get(pharmacy)
        self.visitadas.add(pharmacy)
        buscador = config.BUSCADORES.get(pharmacy)
        page = await br.page()
        try:
            _, bloqueado = await br.goto_ok(page, config.PHARMACIES[pharmacy]["home"], 4000)
            if not bloqueado:
                await br.read_like_human(page)
            if buscador:
                await br.goto_ok(page, buscador, 5000, referer=config.PHARMACIES[pharmacy]["home"])
                await br.read_like_human(page)
        except Exception as e:
            log(f"  no se pudo entrar a {pharmacy} por el buscador: {type(e).__name__}")
        finally:
            await page.close()
        return buscador

    async def enrich(self, br: Browser, p: Product) -> dict:
        p.referer = await self.entrar_al_sitio(br, p.pharmacy)
        page = await br.page()
        pdp = {"promo": [], "receta": [], "images": [], "agotado": False, "addDisabled": None}
        bloqueado = False
        try:
            # se llega a la ficha "desde el buscador" de la farmacia, como lo haría una persona
            _, bloqueado = await br.goto_ok(page, p.url, 6000, referer=p.referer)
            if bloqueado:
                log(f"  {p.pharmacy}: la página del producto vino bloqueada o con error")
                self.errors[p.pharmacy] = "la página del producto respondió bloqueo o error; los datos pueden estar incompletos"
            else:
                await br.read_like_human(page)
                pdp = await page.evaluate(PDP_JS, p.image_tokens or [p.sku])
        except Exception as e:
            log(f"  página de producto falló {p.url}: {e}")
        finally:
            await page.close()

        # promos de texto
        promos: list[Promo] = parse_text(pdp["promo"], "página") + parse_text(p.listing_text, "buscador")

        # imágenes de la galería (API + página)
        imgs = [_normalize_img(p.pharmacy, u) for u in p.images + pdp["images"] if _IS_IMG.search(u)]
        imgs = list(dict.fromkeys(imgs))
        uniq, seen = [], set()
        for u in imgs:
            k = _img_key(u)
            if k not in seen:
                seen.add(k)
                uniq.append(u)
        image_results = []
        targets = uniq[:MAX_IMAGES_PER_PRODUCT]
        for url, res in zip(targets, await asyncio.gather(*[self.ocr_url(br, u, referer=p.url) for u in targets])):
            if not res:
                continue
            found = parse_image(res, p.online_price)
            promos += found
            if found:
                image_results.append({"url": url, "promos": [f.label for f in found],
                                      "texto": res["text"][:400],
                                      "thumb": await self.guardar_miniatura(br, url, p.url)})

        # Si una imagen ya dio el escalonado completo, los precios sueltos de otras
        # imágenes son esos mismos precios: usarlos como "precio de hoy" sería falso.
        if any(x.kind == "tiers" for x in promos):
            promos = [x for x in promos if x.kind not in ("image_price", "tier_at")]
        # El cupón leído del texto de la página manda sobre el leído de una imagen,
        # porque el OCR se equivoca con las letras.
        cupon_texto = next((x.raw for x in promos if x.kind == "cupon" and x.source == "página"), None)
        if cupon_texto:
            for x in promos:
                if (x.condition or "").startswith("Cupón") and x.condition != f"Cupón {cupon_texto}":
                    x.condition = f"Cupón {cupon_texto}"
                    x.label = re.sub(r"con cupón \S+", f"con cupón {cupon_texto}", x.label)
        promos = dedupe(promos)
        in_stock = p.in_stock
        if in_stock is None:
            in_stock = not (pdp.get("agotado") or pdp.get("addDisabled") is True)

        receta_lines = pdp.get("receta", [])[:6]
        known = config.RECETA_KNOWN.get(p.pharmacy)
        if known:
            receta = {"si": "Sí", "no": "No"}[known] + " (según tu experiencia)"
        elif any(_RECETA_NO.search(l) for l in receta_lines):
            receta = "No la pide la ficha"
        elif any(_RECETA_REQ.search(l) for l in receta_lines):
            receta = "Sí (lo indica la página)"
        else:
            receta = "No indicado en la página"

        valor = evaluate(p.online_price, promos) if p.online_price else None
        return {
            "id": f"{p.pharmacy}:{p.sku}",
            "pharmacy": p.pharmacy,
            "pharmacy_name": config.PHARMACIES[p.pharmacy]["name"],
            "dose": p.dose,
            "name": p.name,
            "url": p.url,
            "sku": p.sku,
            "precio_lista": p.list_price,
            "precio_linea": p.online_price,
            "in_stock": in_stock,
            "promos": [x.to_dict() for x in promos],
            "imagenes_promo": image_results,
            "imagenes": uniq[:MAX_IMAGES_PER_PRODUCT],
            "receta": receta,
            "receta_texto": receta_lines,
            "pagina_bloqueada": bloqueado,
            "valor": valor,
        }

    # ---------- banners ----------
    async def banners(self, br: Browser) -> list[dict]:
        hits = []
        kw = re.compile(config.BANNER_KEYWORDS, re.I)
        farmacias = list(config.PHARMACIES.items())
        random.shuffle(farmacias)
        for ph, cfg in farmacias:
            for url in [cfg["home"], *cfg.get("promo_pages", [])]:
                await asyncio.sleep(random.uniform(*config.PAUSA_ENTRE_PAGINAS))
                page = await br.page()
                try:
                    _, bloqueado = await br.goto_ok(page, url, 6000)
                    if bloqueado:
                        log(f"banners {ph}: página bloqueada o con error, se omite")
                        continue
                    await br.read_like_human(page)
                    items = await page.evaluate(BANNERS_JS)
                except Exception as e:
                    log(f"banners {ph} falló: {e}")
                    items = []
                finally:
                    await page.close()
                items = items[:16]
                # pasada rápida: solo se analiza a fondo lo que menciona Mounjaro
                quick = await asyncio.gather(*[self.ocr_url(br, b["src"], quick=True, referer=url) for b in items])
                for b, q in zip(items, quick):
                    meta = f"{b['alt']} {b['href']} {b['src']}"
                    if not (kw.search(meta) or kw.search((q or {}).get("text", ""))):
                        continue
                    res = await self.ocr_url(br, b["src"], referer=url)
                    text = (res or {}).get("text", "")
                    promos = dedupe((parse_image(res, None) if res else []) + parse_text([b["alt"]], "imagen"))
                    hits.append({
                        "pharmacy": ph, "pharmacy_name": cfg["name"], "pagina": url,
                        "src": b["src"], "link": b["href"], "alt": b["alt"],
                        "texto": text[:500], "promos": [p.label for p in promos],
                        "condicion": condition_of(text + " " + b["alt"]),
                        "canal": canal_of(text + " " + b["alt"]),
                        "hash": hashlib.sha1(_img_key(b["src"]).encode()).hexdigest()[:12],
                        "thumb": await self.guardar_miniatura(br, b["src"], url),
                    })
        log(f"banners con Mounjaro: {len(hits)}")
        return hits

    async def check_receta(self, br: Browser, offers: list[dict]):
        """Prueba el carrito/checkout de cada farmacia (cada RECETA_CHECK_DAYS días)."""
        store = self.state.setdefault("receta", {})
        if os.environ.get("SKIP_RECETA") == "1":
            for o in offers:
                if prev := store.get(o["pharmacy"]):
                    o["receta_checkout"] = prev["r"]
            return
        force = os.environ.get("CHECK_RECETA") == "1"
        for o in offers:
            prev = store.get(o["pharmacy"])
            fresh = prev and (time.time() - prev.get("t", 0)) < config.RECETA_CHECK_DAYS * 86400
            if fresh and not force:
                o["receta_checkout"] = prev["r"]
                continue
            if any(x.get("pharmacy") == o["pharmacy"] and x.get("_done") for x in offers):
                continue
            log(f"probando carrito en {o['pharmacy']}…")
            res = await receta.check(br, o["pharmacy"], o["url"])
            store[o["pharmacy"]] = {"t": time.time(), "r": res}
            o["receta_checkout"] = res
            o["_done"] = True
        for o in offers:
            o.pop("_done", None)
            if "receta_checkout" not in o and (prev := store.get(o["pharmacy"])):
                o["receta_checkout"] = prev["r"]

    async def run(self):
        started = datetime.now(TZ)
        async with Browser() as br:
            # primero el home y sus promociones (como llega una persona), luego los productos
            banners = await self.banners(br)
            products = await self.collect(br)
            offers = []
            for p in products:
                log(f"leyendo {p.pharmacy} {p.dose}mg: {p.name}")
                offers.append(await self.enrich(br, p))
                await asyncio.sleep(random.uniform(*config.PAUSA_ENTRE_PAGINAS))
            await self.check_receta(br, offers)
            for o in offers:
                # lo que pasa al cerrar la compra manda sobre el aviso de la ficha
                chk = (o.get("receta_checkout") or {}).get("resultado", "")
                if chk.startswith(("Sí", "Menciona", "No pidió")):
                    o["receta"] = chk

        # si una farmacia tiene 2+ productos para la misma dosis, conservar el de mejor valor
        best: dict[tuple, dict] = {}
        for o in offers:
            k = (o["pharmacy"], o["dose"])
            if o["valor"] and (k not in best or o["valor"]["promedio_por_pluma"] < best[k]["valor"]["promedio_por_pluma"]):
                best[k] = o
        offers = sorted(best.values(), key=lambda o: (float(o["dose"]), o["valor"]["promedio_por_pluma"]))

        latest = {
            "generado": started.isoformat(timespec="minutes"),
            "zona": config.ZONE, "cp": config.POSTAL_CODE,
            "horizonte_plumas": config.HORIZON_PENS,
            "dosis": config.DOSES,
            "ofertas": offers,
            "recomendacion": recommend(offers),
            "banners": banners,
            "errores": self.errors,
            "farmacias": {k: v["name"] for k, v in config.PHARMACIES.items()},
            "notas_farmacia": config.NOTAS_FARMACIA,
        }
        self.limpiar_miniaturas()
        self.persist(latest)
        notify.maybe_send(latest, self.state, started)
        self.trim_cache()
        save_json(DATA / "state.json", self.state)
        log("listo")
        return latest

    def persist(self, latest: dict):
        save_json(DATA / "latest.json", latest)
        public = json.loads(json.dumps(latest))
        save_json(DOCS_DATA / "latest.json", public)
        hist = load_json(DOCS_DATA / "history.json", [])
        hist.append({
            "t": latest["generado"],
            "o": [{"p": o["pharmacy"], "d": o["dose"], "l": o["precio_linea"],
                   "h": o["valor"]["precio_hoy"], "a": o["valor"]["promedio_por_pluma"]} for o in latest["ofertas"]],
        })
        save_json(DOCS_DATA / "history.json", hist[-1500:])

    def trim_cache(self):
        if len(self.ocr_cache) > OCR_CACHE_MAX:
            keep = sorted(self.ocr_cache.items(), key=lambda kv: kv[1].get("t", 0), reverse=True)[:OCR_CACHE_MAX]
            self.state["ocr_cache"] = dict(keep)


def main():
    try:
        asyncio.run(Runner().run())
    except Exception:
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
