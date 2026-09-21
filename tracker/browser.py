"""Navegador real (Chrome) con Playwright. San Pablo y Guadalajara bloquean navegadores
"headless", así que se usa Chrome con ventana; en GitHub Actions corre dentro de xvfb."""
import os

from playwright.async_api import BrowserContext, Page, async_playwright

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")


class Browser:
    async def __aenter__(self):
        self._pw = await async_playwright().start()
        headless = os.environ.get("HEADLESS") == "1"
        args = ["--disable-blink-features=AutomationControlled", "--window-size=1366,900"]
        try:
            self.browser = await self._pw.chromium.launch(
                headless=headless, channel=os.environ.get("BROWSER_CHANNEL", "chrome"), args=args)
        except Exception as e:  # sin Chrome instalado: Chromium, aunque bloquea más
            print(f"Chrome no disponible ({e}); se usa Chromium")
            self.browser = await self._pw.chromium.launch(headless=headless, args=args)
        self.ctx: BrowserContext = await self.browser.new_context(
            locale="es-MX", timezone_id="America/Mexico_City", viewport={"width": 1366, "height": 900},
            geolocation={"latitude": 19.3955, "longitude": -99.1560}, permissions=["geolocation"],
        )
        return self

    async def __aexit__(self, *exc):
        await self.browser.close()
        await self._pw.stop()

    async def page(self) -> Page:
        return await self.ctx.new_page()

    async def goto(self, page: Page, url: str, wait_ms: int = 6000):
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(wait_ms)
        return resp

    async def fetch_bytes(self, url: str) -> bytes | None:
        try:
            r = await self.ctx.request.get(url, timeout=45000, headers={"User-Agent": UA})
            if r.ok:
                return await r.body()
        except Exception:
            pass
        return None


# Extrae de la página de producto: texto de promos del producto (sin carruseles de
# recomendados), avisos de receta, imágenes de la galería y existencia.
PDP_JS = r"""
async (tokens) => {
  const NOISE = 'header,footer,nav,script,style,noscript,[class*=recommend],[class*=related],[class*=upsell],' +
    '[class*=crosssell],[class*=cross-sell],[class*=frequent],[class*=swiper],[class*=slider],[class*=product-tile],' +
    '[class*=product-item],[class*=similar],[class*=bought],cx-carousel,[class*=pdpBanner],[class*=modal],' +
    '[role=dialog],[class*=cookie],[class*=newsletter],[class*=breadcrumb],[class*=minicart],[class*=menu]';
  // abrir "Ver más" de bloques de promociones
  for (const el of document.querySelectorAll('button,[role=button],.action,span,div')) {
    if (el.children.length < 3 && /^\s*ver m[aá]s\s*$/i.test(el.textContent || '') && !el.closest('a[href]') && !el.closest(NOISE)) {
      try { el.click(); } catch (e) {}
    }
  }
  await new Promise(r => setTimeout(r, 1200));
  const hidden = [];
  const h1 = document.querySelector('h1');
  for (const el of document.querySelectorAll(NOISE)) {
    if (el === document.body || el === document.documentElement || (h1 && el.contains(h1))) continue;
    if (el.closest('[class*="gallery"],[class*="primary-images"],[class*="product-media"],[class*="product.media"]')) continue;
    hidden.push([el, el.style.display]); el.style.display = 'none';
  }
  const text = document.body.innerText;
  for (const [el, d] of hidden) el.style.display = d;

  const lines = [...new Set(text.split('\n').map(s => s.replace(/\s+/g, ' ').trim()).filter(s => s && s.length <= 220))];
  const promo = lines.filter(s => /(%|compra|gratis|2x1|3x2|recompensa|monedero|precio final|promoci|descuento|dcto|acumula|l[ií]mite|meses sin|oferta|antes|ahorra|club)/i.test(s));
  const receta = lines.filter(s => /receta/i.test(s));
  const imgs = new Set();
  for (const img of document.querySelectorAll('img,source')) {
    const cands = [img.currentSrc, img.src, img.getAttribute('data-src'), img.getAttribute('data-zoom-image'),
      ...(img.getAttribute('srcset') || '').split(',').map(s => s.trim().split(' ')[0])].filter(Boolean);
    for (const c of cands) if (tokens.some(t => c.includes(t))) imgs.add(new URL(c, location.href).href);
  }
  const add = [...document.querySelectorAll('button')].find(b => /agregar|añadir|comprar/i.test(b.innerText || ''));
  const agotado = /agotado|sin existencia|no disponible en l[ií]nea|fuera de stock/i.test(text.slice(0, 20000));
  return { promo, receta, images: [...imgs], agotado, addDisabled: add ? add.disabled : null, title: document.title };
}
"""

# Banners del home: imágenes grandes o dentro de carruseles, con su alt y el link.
BANNERS_JS = r"""
() => {
  const out = [];
  for (const img of document.querySelectorAll('img')) {
    const src = img.currentSrc || img.src; if (!src || src.startsWith('data:')) continue;
    const inBanner = img.closest('[class*=banner],[class*=carousel],[class*=slider],[class*=swiper],[class*=hero],[class*=slick],[class*=promo],[class*=pdpBanner]');
    if (img.closest('footer')) continue;
    const big = img.naturalWidth >= 700 || (inBanner && img.naturalWidth >= 400);
    if (!big) continue;
    const a = img.closest('a[href]');
    out.push({ src: new URL(src, location.href).href, alt: img.alt || '', href: a ? a.href : '', w: img.naturalWidth });
  }
  const seen = new Set();
  return out.filter(b => !seen.has(b.src) && seen.add(b.src)).slice(0, 40);
}
"""

# Tarjetas de producto de los buscadores Salesforce Commerce Cloud (Guadalajara, YZA)
SFCC_TILES_JS = r"""
() => [...document.querySelectorAll('.product-tile')].map(t => {
  const holder = t.closest('[data-pid]') || t;
  const a = t.querySelector('.pdp-link a, a.link, a[href*=".html"]');
  return {
    pid: holder.getAttribute('data-pid') || (t.querySelector('[data-pid]') || {}).dataset?.pid,
    name: (t.querySelector('.pdp-link') || a || {}).innerText || '',
    href: a ? a.href : '',
    values: [...t.querySelectorAll('.value[content]')].map(e => parseFloat(e.getAttribute('content'))).filter(v => v > 0),
    text: t.innerText.split('\n').map(s => s.trim()).filter(Boolean),
  };
})
"""
