# Rastreador de Mounjaro KwikPen

Revisa 3 veces al día el precio de la **pluma KwikPen de Mounjaro (2.5 mg y 5 mg)** en
Farmacias del Ahorro, Benavides, San Pablo, Guadalajara y YZA; detecta promociones que
solo aparecen **dentro de imágenes** (banners del home y fotos del producto), calcula
**dónde conviene comprar** y te avisa por correo cuando cambia algo.

- **Dashboard:** https://forozco.github.io/mounjaro-tracker/
- **Zona:** CDMX, Narvarte Oriente (C.P. 03023)
- **Costo:** $0 — GitHub Actions, GitHub Pages, Gmail y OCR con Tesseract.

## Qué hace en cada revisión

1. **Busca en cada farmacia** "mounjaro" y "mounjaro kwikpen", igual que si escribieras en
   su buscador. Donde hay API pública (Ahorro y Benavides usan GraphQL; San Pablo su API
   interna) se usa la API; en Guadalajara y YZA se usa un navegador real, porque bloquean
   las peticiones automáticas.
2. **Abre la página del producto** y lee el precio, la existencia y los bloques de
   promociones, ignorando los carruseles de productos recomendados.
3. **Lee las imágenes con OCR** (galería del producto y banners del home). Aquí aparecen
   promos que no están en el texto, por ejemplo el escalonado de Benavides:
   1ª compra 20%, 2ª 25%, 3ª 30%, 4ª 35%.
4. **Calcula el mejor valor** (ver abajo) y arma la recomendación por dosis.
5. **Guarda el historial** y **manda correo** solo si hay novedades.

## El algoritmo de "mejor valor"

No compara solo el precio de hoy. Por cada oferta arma escenarios de compra y elige el mejor:

| Tipo de promo | Cómo se evalúa |
|---|---|
| Descuento directo o con tarjeta | precio × (1 − %) |
| Escalonado por compra (20% → 35%) | precio distinto en cada una de las plumas del tratamiento |
| "Acumula N y el siguiente gratis" | se reparte el costo entre N+1 plumas |
| 2x1, 3x2 | se paga solo por las piezas que marca la promo |
| Monedero electrónico | vale 90% de un descuento directo (`MONEDERO_WEIGHT`) |
| Regalos (agujas) | se resta su valor estimado (`NEEDLES_VALUE`) |
| Precio leído en una imagen | se usa si es creíble (no más de 60% abajo del precio de lista) |

Las promos **no se suman entre sí**, porque en general no son acumulables: se toma el
mejor escenario. El resultado son dos números por farmacia:

- **Precio hoy**: lo que pagas por una pluma en tu próxima compra.
- **Por pluma**: costo promedio si compras `HORIZON_PENS` plumas (4 por defecto, ≈ 4 meses).
  Aquí es donde ganan las promos escalonadas o de acumulación.

También reporta **cómo conviene comprar** (en línea, en la app, en sucursal o recoger en
tienda), qué condición pide la promo (tarjeta de lealtad, etc.) y si hay límite de piezas.

## Receta médica

Una vez por semana agrega la pluma al carrito y avanza hasta el carrito/checkout para ver
si piden datos de receta o del médico. **Nunca completa una compra ni captura datos de
pago**, y al terminar vacía el carrito. Lo que ya sabes (San Pablo y Ahorro no la pidieron)
está anotado en `RECETA_KNOWN` dentro de `tracker/config.py` y tiene prioridad.

## Configuración

Todo lo ajustable está en [`tracker/config.py`](tracker/config.py): dosis, número de plumas
del tratamiento, valor de los regalos, umbrales de alerta y la lista de farmacias.

### Secrets para el correo (en GitHub)

1. Activa la verificación en 2 pasos en tu cuenta de Google.
2. Crea una contraseña de aplicación en https://myaccount.google.com/apppasswords
3. En el repo: **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Valor |
|---|---|
| `GMAIL_USER` | tu correo de Gmail |
| `GMAIL_APP_PASSWORD` | la contraseña de aplicación de 16 letras |
| `EMAIL_TO` | (opcional) a dónde mandar el aviso; si falta, se manda a `GMAIL_USER` |

### Activar el dashboard

**Settings → Pages → Source: Deploy from a branch → rama `main`, carpeta `/docs`.**

## Correr en tu Mac

```bash
brew install tesseract                     # OCR
uv venv -p 3.12 .venv && uv pip install --python .venv -r requirements.txt
.venv/bin/playwright install chrome
# diccionario de español para el OCR (si tesseract no lo trae)
mkdir -p tessdata && curl -sL -o tessdata/spa.traineddata \
  https://github.com/tesseract-ocr/tessdata_fast/raw/main/spa.traineddata

DRY_RUN=1 .venv/bin/python -m tracker      # sin mandar correo
open data/last_email.html                  # así se vería el correo
```

Variables útiles: `ONLY=benavides,yza` (solo ciertas farmacias), `SKIP_RECETA=1`,
`CHECK_RECETA=1` (forzar la prueba del carrito), `HEADLESS=1`, `OCR_WORKERS=4`.

## Lo que no cubre (por ahora)

- **Precios que solo se ven con la sesión iniciada** en cada farmacia. Sí se capturan los
  descuentos de socio que publican abiertamente (Benavides Recompensas, Monedero del Ahorro,
  Club Salud, Cuídate Mucho), pero no el saldo de tu monedero ni precios exclusivos de tu cuenta.
  Se puede agregar después guardando usuario y contraseña como secrets; implica el riesgo de
  captcha, verificación en 2 pasos y de que la farmacia marque la cuenta.
- **Promociones exclusivas de la app** que no aparecen en el sitio web.
- **Precios de tienda física**, que suelen ser distintos a los de línea.

## Avisos

Los datos salen de las páginas públicas de cada farmacia y las promos leídas de imágenes
pueden tener errores de OCR. **Verifica en la farmacia antes de comprar.** Mounjaro es un
medicamento que requiere supervisión médica; este proyecto solo compara precios.
