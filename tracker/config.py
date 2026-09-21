"""Configuración del rastreador. Edita este archivo para ajustar el comportamiento."""

# Tu zona (se usa en el reporte y donde el sitio permite elegir ubicación)
POSTAL_CODE = "03023"
ZONE = "CDMX · Narvarte Oriente"

# Solo KwikPen, en estas dosis (mg)
DOSES = ["2.5", "5"]

# Cuántas plumas planeas comprar (≈ 1 pluma por mes). Sirve para evaluar promos
# escalonadas ("1ª compra 20%, 2ª 25%...") o de acumulación ("acumula 3 y el 4º gratis").
HORIZON_PENS = 4

# Valor estimado (MXN) de regalos que detecta en las promos
NEEDLES_VALUE = 95  # caja de agujas para pluma de regalo
# Cuánto vale $1 de monedero electrónico vs $1 de descuento directo
MONEDERO_WEIGHT = 0.9

# Descuentos mayores a esto se consideran error de OCR y se ignoran
MAX_SANE_DISCOUNT = 0.60

# Alertas por correo
ALERT_DROP_PCT = 2.0     # avisar si el mejor precio baja al menos este %
ALERT_DROP_MXN = 100     # ...o al menos esta cantidad
DAILY_SUMMARY_HOUR = 7   # hora (CDMX) en la que se manda un resumen aunque no haya cambios; None = nunca

# Lo que ya sabes de cada farmacia sobre la receta médica (tiene prioridad sobre lo detectado).
# Valores: "no" | "si" | None (desconocido → se usa lo que detecte en la página)
RECETA_KNOWN = {
    "sanpablo": "no",
    "ahorro": "no",
    "benavides": None,
    "guadalajara": None,
    "yza": None,
}

PHARMACIES = {
    "ahorro": {
        "name": "Farmacias del Ahorro",
        "home": "https://www.fahorro.com/",
        "promo_pages": ["https://www.fahorro.com/control-de-peso/mounjaro.html"],
    },
    "benavides": {
        "name": "Farmacias Benavides",
        "home": "https://www.benavides.com.mx/",
        "promo_pages": [],
    },
    "sanpablo": {
        "name": "Farmacias San Pablo",
        "home": "https://www.farmaciasanpablo.com.mx/",
        "promo_pages": [],
    },
    "guadalajara": {
        "name": "Farmacias Guadalajara",
        "home": "https://www.farmaciasguadalajara.com/",
        "promo_pages": [],
    },
    "yza": {
        "name": "Farmacias YZA",
        "home": "https://www.yza.mx/",
        "promo_pages": ["https://www.yza.mx/promociones-farmacias-yza/especiales-mounjaro/"],
    },
}

# Notas fijas que se muestran junto a cada farmacia en el dashboard
NOTAS_FARMACIA = {
    "guadalajara": "Su sitio avisa que el precio en línea puede variar según la ubicación y que es distinto al de tienda física.",
    "yza": "Cobertura en CDMX reciente: confirma que hagan envío a tu C.P. o si hay que recoger en sucursal.",
    "sanpablo": "Envío gratis a CDMX.",
}

# Palabras que marcan un banner/imagen como relevante
BANNER_KEYWORDS = r"mounjaro|tirzepat|kwik\s*pen|lilly"

# Pausa entre páginas para no disparar el anti-bot (Imperva en Ahorro, Akamai en San Pablo)
PAUSA_ENTRE_PAGINAS = 3

# Cada cuántos días se prueba el flujo de carrito/checkout para ver si piden receta
RECETA_CHECK_DAYS = 7
