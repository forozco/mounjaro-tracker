"""Pruebas de la lectura de promos y del algoritmo de valor.

Se corren sin pytest:  python tests/test_logic.py
Los casos vienen de textos e imágenes reales de las farmacias.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tracker import config
from tracker.products import classify
from tracker.promos import parse_image, parse_text
from tracker.value import evaluate

fallos = []


def check(nombre, cond, detalle=""):
    print(("  ok  " if cond else "FALLA ") + nombre + (f"  → {detalle}" if not cond and detalle else ""))
    if not cond:
        fallos.append(nombre)


# --- identificar el producto: solo KwikPen ---
check("KwikPen de Benavides", classify("5 mg Tirzepatida/0.6 ml Solución", "/mounjaro-5-mg-...") == "5")
check("KwikPen de Ahorro", classify("Mounjaro Kwikpen 2.5Mg/0.6Ml 3 ml", "") == "2.5")
check("KwikPen de San Pablo", classify("Mounjaro 5.0 MG 2.4 ML Solución Caja", "") == "5")
check("KwikPen de Guadalajara", classify("Mounjaro KwikPen 2.5mg/0.6ml Solución Inyectable Pluma Precargada, 2.4 ml.", "") == "2.5")
check("el frasco se descarta", classify("Mounjaro 2.5 mg/0.5 ml 1 Frasco", "") is None)
check("el vial de Benavides se descarta", classify("2.5 mg/0.5 ml Tirzepatida Solución Inyectable", "mounjaro-...-frasco-ampula") is None)
check("otro medicamento se descarta", classify("Abasaglar Kwikpen 100U/ml 1 Pen", "") is None)

# --- promos en texto ---
p = parse_text(["Agujas gratis", "Límite de compra: 2 piezas de Mounjaro por cliente al mes."], "página")
check("agujas de regalo", any(x.kind == "gift" for x in p))
check("límite de piezas", any(x.kind == "limit" and x.n == 2 for x in p))

p = parse_text(["Programa Club Salud: Acumula 4 y el 5º es GRATIS."], "página")
check("acumula N y el siguiente gratis", any(x.kind == "buy_n_get_1" and x.n == 4 for x in p))
check("condición Club Salud", p[0].condition == "Club Salud San Pablo")

p = parse_text(["Promociones con tu tarjeta", "Benavides Recompensas", "20% de desc"], "página")
check("descuento con tarjeta", any(x.kind == "pct" and x.pct == 20 for x in p))

p = parse_text(["Promoción válida del 1 al 30 de septiembre 2026."], "imagen")
check("vigencia", any(x.kind == "vigencia" for x in p))

# --- promos leídas de imágenes ---
ocr = {"text": "Exclusivo con benavides recompensas\n1ERA COMPRA\n4TA COMPRA\nEXCLUSIVO EN LINEA Y APP",
       "boxes": ["Precio final 20% 54,778", "Precio final 25% $4,480", "30% $4,181", "35% $3,882"],
       "prices": [4778.0, 4480.0, 4181.0, 3882.0], "percents": [20, 25, 30, 35]}
p = parse_image(ocr, 5974.0)
tiers = next((x for x in p if x.kind == "tiers"), None)
check("escalonado deducido de los precios", tiers and tiers.tiers == [20.0, 25.0, 30.0, 35.0], tiers and tiers.tiers)
check("canal en línea y app", tiers and tiers.canal == "En línea y app", tiers and tiers.canal)

ocr = {"text": "a 4a COMPRA $3,520", "boxes": [], "prices": [3520.0], "percents": []}
p = parse_image(ocr, 5862.0)
check("un precio suelto de escalonado no es el precio de hoy", any(x.kind == "tier_at" and x.n == 4 for x in p))

ocr = {"text": "A SOLO $3,709.01\nCUPON MOUNJARO40", "boxes": [], "prices": [3709.0], "percents": []}
p = parse_image(ocr, 6310.0)
check("cupón detectado", any("MOUNJARO40" in (x.condition or "") for x in p))

ocr = {"text": "A SOLO $3,709.01\nIngresa el cupón correspondiente en tu carrito de compra: MOUNJARO40",
       "boxes": [], "prices": [3709.0], "percents": []}
p = parse_image(ocr, 6310.0)
check("el cupón es el código, no la palabra de la frase",
      any((x.condition or "").endswith("MOUNJARO40") for x in p), [x.condition for x in p])

ocr = {"text": "4TA COMPRA 35% $3,882", "boxes": [], "prices": [3882.0], "percents": [35]}
p = parse_image(ocr, 5974.0)
check("ordinal escrito como 4TA", any(x.kind == "tier_at" and x.n == 4 for x in p))

from tracker.promos import buscar_cupon  # noqa: E402
check("cupón con la M comida por el OCR", buscar_cupon("CUPON OUNJARO40") == "MOUNJARO40")
check("un código de producto no es cupón", buscar_cupon("HP3455 mounjaro tirzepatida") is None)
check("cupón en el texto de la página",
      any(x.kind == "cupon" for x in parse_text(["Ingresa el cupón MOUNJARO40 en tu carrito"], "página")))

# El OCR pega el "$" como dígito: "$5,159.24" se lee 35159 y saldría más caro que la lista
ocr = {"text": "A SÓLO\n$35,159\nMOUNJARO20\nIngresa el cupón correspondiente en tu carrito",
       "boxes": [], "prices": [35159.0], "percents": []}
p = parse_image(ocr, 6500.0)
check("precio con el signo de pesos mal leído se repara",
      any(x.kind == "image_price" and x.price == 5159 for x in p), [(x.kind, x.price) for x in p])
check("un precio imposible sin reparación posible se ignora",
      parse_image({"text": "$99,999 promo", "boxes": [], "prices": [99999.0], "percents": []}, 6500.0) == [])

ocr = {"text": "mounjaro tirzepatida 2.5 mg/0.6 mL", "boxes": [], "prices": [], "percents": []}
check("una foto de la caja no inventa promos", parse_image(ocr, 6310.0) == [])

# --- algoritmo de valor ---
v = evaluate(5974.0, parse_text(["Benavides Recompensas", "20% de desc"], "página"))
check("descuento simple aplica hoy", v["precio_hoy"] == 4779.2, v["precio_hoy"])

ocr = {"text": "1ERA COMPRA 4TA COMPRA", "boxes": ["20% 54,778", "25% $4,480", "30% $4,181", "35% $3,882"],
       "prices": [4778.0, 4480.0, 4181.0, 3882.0], "percents": []}
v = evaluate(5974.0, parse_image(ocr, 5974.0))
check("escalonado: hoy paga la 1ª compra", v["precio_hoy"] == 4779.2, v["precio_hoy"])
check("escalonado: promedio del tratamiento", 4300 < v["promedio_por_pluma"] < 4400, v["promedio_por_pluma"])

v = evaluate(5862.0, parse_image({"text": "4a COMPRA $3,520", "boxes": [], "prices": [3520.0], "percents": []}, 5862.0))
check("precio de 4ª compra no baja el precio de hoy", v["precio_hoy"] == 5862.0, v["precio_hoy"])
check("pero sí mejora el promedio", v["promedio_por_pluma"] < 5862.0, v["promedio_por_pluma"])

v = evaluate(3590.0, parse_text(["Agujas gratis"], "página"))
check("el regalo se descuenta del costo", v["precio_hoy"] == 3590.0 - config.NEEDLES_VALUE, v["precio_hoy"])

v = evaluate(6000.0, parse_text(["Acumula 3 y el 4º es GRATIS"], "página"))
check("acumulación reparte el costo", v["promedio_por_pluma"] == 4500.0, v["promedio_por_pluma"])

v = evaluate(6000.0, parse_image({"text": "90% de descuento", "boxes": [], "prices": [], "percents": [90]}, 6000.0))
check("un descuento absurdo se ignora", v["precio_hoy"] == 6000.0, v["precio_hoy"])

# --- avisos por correo (aquí tronó en la primera corrida real) ---
from datetime import datetime  # noqa: E402

from tracker import notify  # noqa: E402

def _latest():
    pick = {"precio": 4331.0, "pharmacy": "benavides", "pharmacy_name": "Farmacias Benavides",
            "url": "u", "escenario": "Escalonado", "condiciones": [], "canal": "En línea",
            "receta": "No", "requiere_cuenta": True}
    return {"recomendacion": {"5": {"tratamiento": dict(pick), "hoy": dict(pick)}},
            "ofertas": [], "banners": [], "errores": {}, "dosis": ["5"], "horizonte_plumas": 4,
            "generado": "2026-09-21T14:00", "zona": "CDMX", "cp": "03023", "farmacias": {}}

tarde = datetime(2026, 9, 21, 14, 0)
motivos, _ = notify.decide(_latest(), {"best": {"5": {"precio": 4331.0, "ph": "benavides"}}}, tarde)
check("sin cambios no manda correo", motivos == [], motivos)
motivos, _ = notify.decide(_latest(), {"best": {"5": {"precio": 4331.0, "ph": "yza"}}}, tarde)
check("avisa si cambia la farmacia que conviene", any("Cambió" in m for m in motivos), motivos)
motivos, _ = notify.decide(_latest(), {"best": {"5": {"precio": 5000.0, "ph": "benavides"}}}, tarde)
check("avisa si baja el precio", any("Bajó" in m for m in motivos), motivos)
motivos, _ = notify.decide(_latest(), {}, datetime(2026, 9, 21, 7, 0))
check("resumen diario en la corrida de la mañana", any("Resumen" in m for m in motivos), motivos)

print()
# --- Enlace Lilly escrito en la ficha de San Pablo (un párrafo partido en frases) ---
p = parse_text([
    'Este producto es parte del programa de laboratorio "Enlace Eli-Lilly", el cual determina la mecánica para proporcionar sus beneficios.',
    "En la 4ª compra recibirás hasta un 35% de descuento.",
    "1ª compra hasta un 20%, 2ª compra hasta un 25%, 3ª compra hasta un 30%.",
    "Obtén este descuento con tu tarjeta del programa.",
    "Válido en máximo 2 piezas cada 30 días y en compras realizadas desde el 05 mayo del 2026.",
], "página")
t = [x for x in p if x.kind == "tiers"]
check("escalonado de Enlace en texto", len(t) == 1 and t[0].tiers == [20, 25, 30, 35], [x.label for x in p])
check("el 35% de la 4ª compra no se toma como descuento de hoy", not any(x.kind == "pct" for x in p), [x.label for x in p])
check("condición Enlace Lilly", t and t[0].condition == "Tarjeta Enlace Lilly", t and t[0].condition)
check("límite de Enlace", any(x.kind == "limit" and x.n == 2 for x in p))
v = evaluate(5964, p)
check("promedio con Enlace en San Pablo", abs(v["promedio_por_pluma"] - 4323.9) < 1, v["promedio_por_pluma"])
check("primera compra con Enlace", abs(v["desglose_tratamiento"][0] - 4771.2) < 1, v["desglose_tratamiento"])

# --- cambios en las reglas publicadas ---
from tracker.terminos import diferencias
quito, puso = diferencias("El máximo se otorga con la 4ª compra. Compra dentro de los 35 días; si no, se reinicia.",
                          "El máximo se otorga con la 4ª compra. Compra dentro de los 30 días; si no, se reinicia.")
check("detecta la frase que cambió en las reglas", quito == ["Compra dentro de los 35 días;"] and puso == ["Compra dentro de los 30 días;"], (quito, puso))

if fallos:
    print(f"{len(fallos)} prueba(s) fallaron: {', '.join(fallos)}")
    sys.exit(1)
print("todas las pruebas pasaron")
