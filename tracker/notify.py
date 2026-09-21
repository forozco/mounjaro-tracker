"""Avisos por correo (Gmail SMTP con contraseña de aplicación).

Solo manda correo cuando pasa algo: baja el mejor precio, aparece una promo o banner
nuevo, cambia la recomendación, o una farmacia lleva 2 corridas fallando.
También manda un resumen diario en la corrida de la mañana.
"""
import hashlib
import json
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from . import config

ROOT = Path(__file__).resolve().parent.parent


def money(v) -> str:
    return "—" if v is None else f"${v:,.0f}"


def _sig(offer: dict) -> str:
    raw = json.dumps([p.get("label") for p in offer.get("promos", [])], ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()[:10]


def decide(latest: dict, state: dict, started) -> tuple[list[str], bool]:
    """Regresa (motivos, hay_algo_urgente)."""
    reasons, urgent = [], False
    prev_best = state.get("best", {})
    best_now = {}
    for dose, rec in (latest.get("recomendacion") or {}).items():
        if not rec:
            continue
        t = rec["tratamiento"]
        best_now[dose] = {"precio": t["precio"], "ph": t["pharmacy"]}
        old = prev_best.get(dose)
        if old:
            diff = old["precio"] - t["precio"]
            if diff >= config.ALERT_DROP_MXN or (old["precio"] and diff / old["precio"] * 100 >= config.ALERT_DROP_PCT):
                reasons.append(f"Bajó el mejor precio de {dose} mg: {money(old['precio'])} → {money(t['precio'])} "
                               f"por pluma en {t['pharmacy_name']}")
                urgent = True
            elif old["ph"] != t["pharmacy"]:
                reasons.append(f"Cambió la mejor opción de {dose} mg: ahora conviene {t['pharmacy_name']} ({money(t['precio'])}/pluma)")
                urgent = True
        else:
            reasons.append(f"Primer registro de {dose} mg: mejor opción {t['pharmacy_name']} a {money(t['precio'])}/pluma")
    state["best"] = best_now

    seen_promos = state.setdefault("promo_sigs", {})
    for o in latest["ofertas"]:
        sig = _sig(o)
        if o["promos"] and seen_promos.get(o["id"]) != sig:
            if o["id"] in seen_promos:
                reasons.append(f"Promo nueva en {o['pharmacy_name']} {o['dose']} mg: " +
                               ", ".join(p["label"] for p in o["promos"][:3]))
                urgent = True
            seen_promos[o["id"]] = sig

    seen_banners = set(state.setdefault("banner_hashes", []))
    for b in latest["banners"]:
        if b["hash"] not in seen_banners:
            seen_banners.add(b["hash"])
            reasons.append(f"Banner nuevo con Mounjaro en {b['pharmacy_name']}" + (f": {b['promos'][0]}" if b["promos"] else ""))
            urgent = True
    state["banner_hashes"] = list(seen_banners)[-400:]

    fails = state.setdefault("fails", {})
    for ph in config.PHARMACIES:
        if ph in latest["errores"]:
            fails[ph] = fails.get(ph, 0) + 1
            if fails[ph] == 2:
                reasons.append(f"{config.PHARMACIES[ph]['name']} lleva 2 revisiones fallando: {latest['errores'][ph][:120]}")
        else:
            fails[ph] = 0

    if config.DAILY_SUMMARY_HOUR is not None and started.hour == config.DAILY_SUMMARY_HOUR:
        reasons.append("Resumen diario")
    return reasons, urgent


DASHBOARD = "https://forozco.github.io/mounjaro-tracker/"

# ---- lenguaje llano (el mismo del dashboard) ----
_CANAL = {"En línea": "en línea", "En línea y app": "en línea o en la app", "Solo en la app": "solo en la app",
          "Solo en línea": "solo en línea", "Solo en sucursal": "solo en sucursal",
          "Recoger en sucursal": "recogiendo en sucursal"}


def _canal(c: str | None) -> str:
    return _CANAL.get(c or "", "en línea o en la app" if "confirmar" in (c or "") else "en línea")


def _condicion(c: str) -> str | None:
    if m := re.match(r"^Cupón ([A-Z0-9]{4,})$", c or ""):
        return f"con el cupón {m.group(1)}"
    for clave, texto in (("Enlace", "con tarjeta Enlace Lilly y receta"), ("Recompensas", "con tarjeta Benavides Recompensas"), ("Cuídate", "con tarjeta Cuídate Mucho"),
                         ("Club Salud", "con Club Salud"), ("Monedero", "con Monedero del Ahorro"),
                         ("lealtad", "con la tarjeta de la farmacia"), ("código", "con un código de promoción")):
        if clave in (c or ""):
            return texto
    return None


def condiciones(o: dict, con_receta: bool = False) -> str:
    v = o.get("valor") or {}
    partes = [_canal(v.get("canal_tratamiento"))]
    partes += [x for x in map(_condicion, v.get("condiciones_tratamiento") or []) if x]
    d, e = v.get("desglose_tratamiento") or [], v.get("escenario_tratamiento") or ""
    if e.startswith("Escalonado") and len(d) > 1:
        partes.append(f"baja de {money(d[0])} a {money(d[-1])} de la 1.ª a la {len(d)}.ª compra")
    elif m := re.match(r"^(\d)ª compra", e):
        partes.append(f"llega a {money(d[-1])} en la {m.group(1)}.ª compra")
    elif e.startswith("Acumula"):
        partes.append(e[0].lower() + e[1:])
    if v.get("regalo_valor"):
        partes.append("incluye agujas")
    if v.get("limite"):
        partes.append(f"máximo {v['limite']} al mes")
    enlace = any("Enlace" in (c or "") for c in v.get("condiciones_tratamiento") or [])
    if con_receta and not enlace and (o.get("receta") or "").startswith("No"):
        partes.append("no piden receta")
    texto = " · ".join(dict.fromkeys(partes))
    return texto[:1].upper() + texto[1:]


def _resumen(latest: dict):
    """Por dosis: (dosis, ganadora, oferta ganadora, resto ordenado, recomendación)."""
    for dose in latest["dosis"]:
        rec = (latest.get("recomendacion") or {}).get(dose)
        ofertas = sorted([o for o in latest["ofertas"] if o["dose"] == dose and o.get("valor")],
                         key=lambda o: o["valor"]["promedio_por_pluma"])
        if not rec or not ofertas:
            yield dose, None, None, [], None
            continue
        t = rec["tratamiento"]
        mejor = next((o for o in ofertas if o["id"] == t["id"]), ofertas[0])
        yield dose, t, mejor, [o for o in ofertas if o is not mejor], rec


def _cambios(reasons: list[str]) -> list[str]:
    return [r for r in reasons if not r.startswith(("Resumen diario", "Primer registro"))]


def render_text(latest: dict, reasons: list[str]) -> str:
    L = []
    cambios = _cambios(reasons)
    if cambios:
        L += ["Qué cambió:"] + [f"- {c}" for c in cambios] + [""]
    for dose, t, mejor, resto, rec in _resumen(latest):
        if not t:
            L += [f"{dose} mg: no se encontró en esta revisión.", ""]
            continue
        L.append(f"{dose} mg: conviene en {t['pharmacy_name']}, a {money(t['precio'])} por pluma.")
        L.append(condiciones(mejor, True) + ".")
        if rec["hoy"]["id"] != t["id"]:
            L.append(f"Si solo compras una, hoy sale más barata en {rec['hoy']['pharmacy_name']}: {money(rec['hoy']['precio'])}.")
        L.append(t["url"])
        L += [f"  {o['pharmacy_name']}: {money(o['valor']['promedio_por_pluma'])}" for o in resto] + [""]
    if latest.get("errores"):
        L += ["No se pudo leer bien: " + ", ".join(latest["farmacias"].get(k, k) for k in latest["errores"]) + ".", ""]
    L += [f"Todas las farmacias: {DASHBOARD}", "",
          "Precio por pluma = promedio si compras cuatro, una al mes. Confirma el precio antes de pagar."]
    return "\n".join(L)


def render(latest: dict, reasons: list[str]) -> str:
    INK, MUTED, FAINT, RULE, ACC = "#1a1d1c", "#666c69", "#9aa09c", "#e2e3de", "#0e6a52"
    font = "-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif"
    p = f"margin:0;font-family:{font};"
    h = [f"<!DOCTYPE html><html lang='es'><head><meta charset='utf-8'>"
         f"<meta name='viewport' content='width=device-width,initial-scale=1'></head>"
         f"<body style='margin:0;padding:0;background:#f7f7f4;'>"
         f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0' style='background:#f7f7f4;'>"
         f"<tr><td align='center' style='padding:32px 20px 40px;'>"
         f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0' style='max-width:560px;'>"]

    cambios = _cambios(reasons)
    if cambios:
        items = "".join(f"<div style='{p}font-size:15px;line-height:1.5;color:{INK};'>{c}</div>" for c in cambios)
        h.append(f"<tr><td style='padding:0 0 28px;'>{items}</td></tr>")

    for dose, t, mejor, resto, rec in _resumen(latest):
        h.append(f"<tr><td style='padding:0 0 6px;'><div style='{p}font-size:13px;color:{MUTED};'>{dose} mg</div></td></tr>")
        if not t:
            h.append(f"<tr><td style='padding:0 0 32px;'><div style='{p}font-size:17px;color:{INK};'>"
                     f"No se encontró en esta revisión.</div></td></tr>")
            continue
        otra = ""
        if rec["hoy"]["id"] != t["id"]:
            otra = (f"<div style='{p}font-size:14px;line-height:1.5;color:{MUTED};padding-top:4px;'>"
                    f"Si solo compras una, hoy sale más barata en {rec['hoy']['pharmacy_name']}: "
                    f"{money(rec['hoy']['precio'])}.</div>")
        h.append(
            f"<tr><td style='padding:0 0 14px;'>"
            f"<div style='{p}font-size:21px;line-height:1.3;font-weight:600;color:{INK};'>"
            f"Conviene en {t['pharmacy_name']}, a <span style='color:{ACC};'>{money(t['precio'])}</span> por pluma.</div>"
            f"<div style='{p}font-size:14px;line-height:1.5;color:{MUTED};padding-top:6px;'>{condiciones(mejor, True)}</div>"
            f"{otra}"
            f"<div style='{p}font-size:14px;padding-top:10px;'><a href='{t['url']}' style='color:{INK};'>"
            f"Ver en {t['pharmacy_name']}</a></div></td></tr>")
        if resto:
            filas = "".join(
                f"<tr><td style='{p}font-size:14px;color:{MUTED};padding:7px 0;border-top:1px solid {RULE};'>{o['pharmacy_name']}</td>"
                f"<td align='right' style='{p}font-size:14px;color:{MUTED};padding:7px 0;border-top:1px solid {RULE};'>"
                f"{money(o['valor']['promedio_por_pluma'])}</td></tr>" for o in resto)
            h.append(f"<tr><td style='padding:0 0 34px;'><table role='presentation' width='100%' cellpadding='0' "
                     f"cellspacing='0'>{filas}</table></td></tr>")

    if latest.get("errores"):
        malas = ", ".join(latest["farmacias"].get(k, k) for k in latest["errores"])
        h.append(f"<tr><td style='padding:0 0 18px;'><div style='{p}font-size:14px;color:#9a4a12;'>"
                 f"No se pudo leer bien: {malas}.</div></td></tr>")
    h.append(f"<tr><td style='padding:6px 0 0;border-top:1px solid {RULE};'>"
             f"<div style='{p}font-size:14px;padding-top:14px;'><a href='{DASHBOARD}' style='color:{INK};'>Ver todas las farmacias</a></div>"
             f"<div style='{p}font-size:12px;line-height:1.5;color:{FAINT};padding-top:10px;'>Precio por pluma: promedio si "
             f"compras cuatro, una al mes. Algunos precios se leen de imágenes; confírmalos antes de pagar.</div>"
             f"</td></tr></table></td></tr></table></body></html>")
    return "".join(h)


def send(subject: str, html: str, text: str = "") -> bool:
    user, pwd = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD")
    to = os.environ.get("EMAIL_TO") or user
    if not (user and pwd and to):
        print("Sin credenciales de correo: el reporte quedó en data/last_email.html")
        return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.set_content(text or "Abre el comparador: " + DASHBOARD)
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
        s.login(user, pwd)
        s.send_message(msg)
    print(f"Correo enviado a {to}")
    return True


def maybe_send(latest: dict, state: dict, started):
    reasons, urgent = decide(latest, state, started)
    html = render(latest, reasons)
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "last_email.html").write_text(html)
    if not reasons:
        print("Sin novedades: no se manda correo")
        return
    rec = latest.get("recomendacion") or {}
    bits = [f"{d} mg a {money(r['tratamiento']['precio'])} en {r['tratamiento']['pharmacy_name'].replace('Farmacias ', '')}"
            for d, r in rec.items() if r]
    subject = ("Bajó Mounjaro: " if urgent else "Mounjaro: ") + ", ".join(bits or ["revisión"])
    if os.environ.get("DRY_RUN") == "1":
        print("DRY_RUN:", subject, "|", "; ".join(reasons))
        return
    send(subject, html, render_text(latest, reasons))
