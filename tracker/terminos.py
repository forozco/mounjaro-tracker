"""Vigila las reglas publicadas de los programas de descuento.

Cada revisión abre la página, recorta la sección (el título h2 y lo que sigue hasta
el siguiente h2) y compara su texto con el guardado. La captura se toma la primera
vez y cada vez que el texto cambia; así queda la evidencia de qué decía antes.
"""
import hashlib
import re
from datetime import datetime
from pathlib import Path

from .browser import Browser

VIGILADOS = [
    {
        "id": "benavides-escalonado",
        "nombre": "Benavides · Descuento Escalonado Mounjaro",
        "url": "https://www.benavides.com.mx/terminos-y-condiciones",
        "titulo": "Descuento Escalonado Mounjaro",
    },
]

SECCION_JS = r"""
(titulo) => {
  const h = [...document.querySelectorAll('h1,h2,h3')].find(e => e.textContent.trim().toLowerCase() === titulo.toLowerCase());
  if (!h) return null;
  const partes = [h];
  for (let s = h.nextElementSibling; s && !/^H[1-3]$/.test(s.tagName); s = s.nextElementSibling) partes.push(s);
  h.scrollIntoView({ block: 'center' });
  const rects = partes.map(e => e.getBoundingClientRect()).filter(r => r.width && r.height);
  const x = Math.min(...rects.map(r => r.left)), y = Math.min(...rects.map(r => r.top));
  const r = Math.max(...rects.map(r => r.right)), b = Math.max(...rects.map(r => r.bottom));
  return {
    texto: partes.slice(1).map(e => e.innerText).join('\n'),
    clip: { x: x + scrollX - 12, y: y + scrollY - 12, width: r - x + 24, height: b - y + 16 },
  };
}
"""


def _normal(t: str) -> str:
    return " ".join(t.split())


async def revisar(br: Browser, state: dict, carpeta: Path, ahora: datetime, log) -> list[dict]:
    """Regresa el estado de cada sección vigilada; marca 'cambio' si el texto es otro."""
    guardado = state.setdefault("terminos", {})
    carpeta.mkdir(parents=True, exist_ok=True)
    out = []
    for v in VIGILADOS:
        prev = guardado.get(v["id"], {})
        item = {"id": v["id"], "nombre": v["nombre"], "url": v["url"], "verificado": ahora.isoformat(timespec="minutes"),
                "cambio": False, "error": None}
        page = await br.page()
        try:
            _, bloqueado = await br.goto_ok(page, v["url"], 5000)
            sec = None if bloqueado else await page.evaluate(SECCION_JS, v["titulo"])
            if not sec or not _normal(sec["texto"]):
                item["error"] = "la página vino bloqueada" if bloqueado else "no se encontró la sección"
            else:
                texto = _normal(sec["texto"])
                h = hashlib.sha1(texto.encode()).hexdigest()[:12]
                captura = prev.get("captura")
                if h != prev.get("hash") or not captura or not (carpeta.parent.parent / captura).exists():
                    nombre = f"{v['id']}-{ahora:%Y%m%d-%H%M}.png"
                    await page.screenshot(path=str(carpeta / nombre), clip=sec["clip"], full_page=True)
                    captura = f"img/terminos/{nombre}"
                if prev.get("hash") and h != prev["hash"]:
                    item["cambio"] = True
                    item["antes"] = prev.get("texto", "")
                    item["captura_antes"] = prev.get("captura")
                    log(f"términos: CAMBIÓ {v['nombre']}")
                desde = prev.get("desde") if h == prev.get("hash") else item["verificado"]
                guardado[v["id"]] = {"hash": h, "texto": texto, "captura": captura, "desde": desde}
                item.update(texto=texto, captura=captura, desde=desde)
        except Exception as e:
            item["error"] = f"{type(e).__name__}"
        finally:
            await page.close()
        if item["error"]:
            log(f"términos: {v['nombre']}: {item['error']}")
            item.update({k: prev.get(k) for k in ("texto", "captura", "desde")})
        out.append(item)
    return out


_ORACION = re.compile(r"(?<=[.;])\s+")


def diferencias(antes: str, despues: str) -> tuple[list[str], list[str]]:
    """Frases que se quitaron y que se agregaron, para explicar el cambio en el correo."""
    a, d = _ORACION.split(antes or ""), _ORACION.split(despues or "")
    return [x for x in a if x and x not in d], [x for x in d if x and x not in a]
