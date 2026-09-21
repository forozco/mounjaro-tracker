"""Algoritmo de "mejor valor".

Para cada oferta arma escenarios de compra (precio normal, cada promo aplicable) y calcula:
  - precio_hoy: lo que pagas por UNA pluma en tu siguiente compra
  - promedio_por_pluma: costo promedio por pluma si compras HORIZON_PENS plumas (tratamiento)
restando el valor de regalos (agujas) y del monedero. Las promos normalmente no se
acumulan entre sí, así que se toma el MEJOR escenario, no la suma.
"""
from . import config
from .promos import Promo


def _scenario(label, unit_prices, conditions, notes=None, canal=None):
    return {"label": label, "unit": [round(u, 2) for u in unit_prices], "conditions": conditions,
            "notes": notes or [], "canal": canal}


def evaluate(price: float, promos: list[Promo]) -> dict:
    H = config.HORIZON_PENS
    floor = price * (1 - config.MAX_SANE_DISCOUNT)
    scen = [_scenario("Precio en línea", [price] * H, [], canal="En línea")]

    for p in promos:
        cond = [p.condition] if p.condition else []
        canal = p.canal
        if p.kind == "pct" and p.pct:
            scen.append(_scenario(p.label, [price * (1 - p.pct / 100)] * H, cond, canal=canal))
        elif p.kind == "tiers" and p.tiers:
            unit = [price * (1 - p.tiers[min(i, len(p.tiers) - 1)] / 100) for i in range(H)]
            scen.append(_scenario(p.label, unit, cond, ["Cada compra debe hacerse dentro del plazo que marque la farmacia"], canal))
        elif p.kind == "buy_n_get_1" and p.n:
            unit = [0.0 if (i + 1) % (p.n + 1) == 0 else price for i in range(H)]
            note = [] if H >= p.n + 1 else [f"Con {H} plumas no alcanzas la gratis (necesitas {p.n + 1})"]
            scen.append(_scenario(p.label, unit, cond, note, canal))
        elif p.kind == "nxm" and p.n and p.m:
            unit = [price if (i % p.n) < p.m else 0.0 for i in range(H)]
            scen.append(_scenario(p.label, unit, cond, [f"Requiere comprar {p.n} piezas a la vez"], canal))
        elif p.kind == "monedero" and p.pct:
            unit = [price * (1 - p.pct / 100 * config.MONEDERO_WEIGHT)] * H
            scen.append(_scenario(p.label, unit, cond, ["El monedero se usa en compras futuras"], canal))
        elif p.kind == "tier_at" and p.price and p.n:
            unit = [price if i < p.n - 1 else p.price for i in range(H)]
            note = [f"Ese precio aplica hasta tu compra número {p.n}"]
            if H < p.n:
                note.append(f"Con {H} plumas no llegas a esa compra")
            scen.append(_scenario(p.label, unit, cond, note, canal))
        elif p.kind == "image_price" and p.price:
            scen.append(_scenario(p.label, [p.price] * H, cond or ["Promo vista en imagen: revisa condiciones"], canal=canal))

    # descartar escenarios absurdos (errores de lectura)
    scen = [s for s in scen if min(s["unit"]) >= floor or 0.0 in s["unit"]]

    gift = config.NEEDLES_VALUE if any(p.kind == "gift" for p in promos) else 0
    for s in scen:
        s["total"] = round(sum(s["unit"]) - gift * H, 2)
        s["avg"] = round(s["total"] / H, 2)
        s["now"] = round(s["unit"][0] - gift, 2)

    best_now = min(scen, key=lambda s: (s["now"], len(s["conditions"])))
    best_avg = min(scen, key=lambda s: (s["avg"], len(s["conditions"])))
    return {
        "precio_linea": price,
        "precio_hoy": best_now["now"],
        "precio_hoy_pagas": best_now["unit"][0],
        "escenario_hoy": best_now["label"],
        "condiciones_hoy": best_now["conditions"],
        "canal_hoy": best_now["canal"] or "En línea",
        "promedio_por_pluma": best_avg["avg"],
        "total_tratamiento": best_avg["total"],
        "escenario_tratamiento": best_avg["label"],
        "condiciones_tratamiento": best_avg["conditions"],
        "canal_tratamiento": best_avg["canal"] or "En línea",
        "notas_tratamiento": best_avg["notes"],
        "desglose_tratamiento": best_avg["unit"],
        "regalo_valor": gift,
        "ahorro_vs_linea_pct": round((1 - best_avg["avg"] / price) * 100, 1) if price else 0,
        "limite": next((p.n for p in promos if p.kind == "limit"), None),
        "msi": next((p.n for p in promos if p.kind == "msi"), None),
    }


def recommend(offers: list[dict]) -> dict:
    """offers: dicts con 'valor' y 'in_stock'. Regresa la recomendación por dosis."""
    out = {}
    for dose in config.DOSES:
        cands = [o for o in offers if o["dose"] == dose and o.get("valor") and o.get("in_stock") is not False]
        if not cands:
            out[dose] = None
            continue
        hoy = min(cands, key=lambda o: o["valor"]["precio_hoy"])
        trat = min(cands, key=lambda o: o["valor"]["promedio_por_pluma"])
        ranking = sorted(cands, key=lambda o: o["valor"]["promedio_por_pluma"])
        second = ranking[1]["valor"]["promedio_por_pluma"] if len(ranking) > 1 else None
        out[dose] = {
            "hoy": _pick(hoy, "hoy"),
            "tratamiento": _pick(trat, "tratamiento"),
            "ventaja_vs_segundo": round(second - trat["valor"]["promedio_por_pluma"], 2) if second else None,
            "ranking": [o["id"] for o in ranking],
        }
    return out


def _pick(o, mode):
    v = o["valor"]
    return {
        "id": o["id"],
        "pharmacy": o["pharmacy"],
        "pharmacy_name": o["pharmacy_name"],
        "url": o["url"],
        "precio": v["precio_hoy"] if mode == "hoy" else v["promedio_por_pluma"],
        "pagas": v["precio_hoy_pagas"] if mode == "hoy" else None,
        "escenario": v[f"escenario_{mode}"],
        "condiciones": v[f"condiciones_{mode}"],
        "canal": v.get(f"canal_{mode}") or "En línea",
        "receta": o.get("receta"),
    }
