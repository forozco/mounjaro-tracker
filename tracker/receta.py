"""¿La farmacia pide datos de receta o del médico al cerrar la compra?

Agrega la pluma al carrito, avanza hasta el carrito/checkout, busca avisos o campos de
receta y luego vacía el carrito. Nunca completa una compra ni captura datos de pago.
Se corre cada RECETA_CHECK_DAYS días porque es lento.
"""
import re

from .browser import Browser

CARTS = {
    "ahorro": ["https://www.fahorro.com/checkout/cart/"],
    "benavides": ["https://www.benavides.com.mx/checkout/cart/"],
    "sanpablo": ["https://www.farmaciasanpablo.com.mx/cart"],
    "guadalajara": ["https://www.farmaciasguadalajara.com/carrito", "https://www.farmaciasguadalajara.com/cart"],
    "yza": ["https://www.yza.mx/carrito", "https://www.yza.mx/cart"],
}

ASK = re.compile(r"receta|prescripci[oó]n|c[eé]dula|nombre del m[eé]dico|datos del m[eé]dico|folio.{0,20}receta", re.I)
HARD = re.compile(r"(sube|subir|adjunta|carga|captura|ingresa|proporciona)[^.]{0,40}(receta|c[eé]dula|m[eé]dico)|"
                  r"(receta|c[eé]dula)[^.]{0,30}(obligatori|requerid|necesari|indispensable)", re.I)

ADD_JS = r"""
() => {
  const btns = [...document.querySelectorAll('button,a,input[type=submit]')];
  const b = btns.find(x => /agregar al carrito|añadir al carrito|agregar a mi carrito|agregar$/i.test((x.innerText || x.value || '').trim()) && !x.disabled);
  if (b) { b.click(); return (b.innerText || b.value || '').trim(); }
  return null;
}
"""

SCAN_JS = r"""
() => {
  const text = document.body.innerText;
  const fields = [...document.querySelectorAll('input,select,textarea,label')]
    .map(e => (e.placeholder || e.name || e.innerText || '').trim()).filter(Boolean);
  return { text: text.slice(0, 15000), fields: [...new Set(fields)].slice(0, 120), url: location.href };
}
"""

EMPTY_JS = r"""
() => {
  const b = [...document.querySelectorAll('button,a')].find(x => /eliminar|quitar|borrar|remover/i.test((x.innerText || x.title || x.ariaLabel || '')));
  if (b) { b.click(); return true; } return false;
}
"""


async def check(br: Browser, pharmacy: str, product_url: str) -> dict:
    page = await br.page()
    out = {"pharmacy": pharmacy, "resultado": "no se pudo verificar", "evidencia": [], "url_revisada": None}
    try:
        await br.goto(page, product_url, 6000)
        clicked = await page.evaluate(ADD_JS)
        if not clicked:
            out["resultado"] = "no se pudo agregar al carrito (botón no encontrado)"
            return out
        await page.wait_for_timeout(6000)
        seen = []
        for url in CARTS.get(pharmacy, []):
            try:
                resp = await br.goto(page, url, 5000)
                if resp and resp.status >= 400:
                    continue
                scan = await page.evaluate(SCAN_JS)
                out["url_revisada"] = scan["url"]
                seen.append(scan)
                # intentar avanzar un paso del checkout
                try:
                    btn = page.get_by_role("button", name=re.compile(r"proceder|continuar|pagar|finalizar|checkout", re.I)).first
                    if await btn.count():
                        await btn.click(timeout=8000)
                        await page.wait_for_timeout(7000)
                        seen.append(await page.evaluate(SCAN_JS))
                except Exception:
                    pass
                break
            except Exception:
                continue
        hits, hard = [], False
        for scan in seen:
            for line in scan["text"].split("\n"):
                line = " ".join(line.split())
                if line and ASK.search(line) and len(line) < 220:
                    hits.append(line)
                    hard = hard or bool(HARD.search(line))
            for f in scan["fields"]:
                if ASK.search(f):
                    hits.append(f"[campo] {f}")
                    hard = True
        out["evidencia"] = list(dict.fromkeys(hits))[:8]
        if not seen:
            out["resultado"] = "no se pudo abrir el carrito"
        elif hard:
            out["resultado"] = "Sí pide datos de receta/médico"
        elif hits:
            out["resultado"] = "Menciona receta, pero sin pedir datos"
        else:
            out["resultado"] = "No pidió receta hasta el carrito"
        # dejar el carrito vacío
        try:
            await page.evaluate(EMPTY_JS)
            await page.wait_for_timeout(2500)
        except Exception:
            pass
        return out
    except Exception as e:
        out["resultado"] = f"error: {type(e).__name__}"
        return out
    finally:
        await page.close()
