"""Avisos por correo (Gmail SMTP con contraseña de aplicación).

Solo manda correo cuando pasa algo: baja el mejor precio, aparece una promo o banner
nuevo, cambia la recomendación, o una farmacia lleva 2 corridas fallando.
También manda un resumen diario en la corrida de la mañana.
"""
import hashlib
import json
import os
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
            elif old["ph"] != t["ph"]:
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
                reasons.append(f"⚠️ {config.PHARMACIES[ph]['name']} lleva 2 revisiones fallando: {latest['errores'][ph][:120]}")
        else:
            fails[ph] = 0

    if config.DAILY_SUMMARY_HOUR is not None and started.hour == config.DAILY_SUMMARY_HOUR:
        reasons.append("Resumen diario")
    return reasons, urgent


def render(latest: dict, reasons: list[str]) -> str:
    rec = latest.get("recomendacion") or {}
    H = latest["horizonte_plumas"]
    css = ("body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#18181b;background:#f4f4f5;padding:16px}"
           ".c{max-width:720px;margin:auto;background:#fff;border-radius:14px;padding:20px}"
           "h1{font-size:19px;margin:0 0 4px}h2{font-size:15px;margin:22px 0 8px}"
           ".m{color:#71717a;font-size:12px}table{border-collapse:collapse;width:100%;font-size:13px}"
           "th,td{text-align:left;padding:7px 6px;border-bottom:1px solid #e4e4e7;vertical-align:top}"
           "th{color:#71717a;font-weight:600;font-size:11px;text-transform:uppercase}"
           ".b{background:#ecfdf5;border:1px solid #a7f3d0;border-radius:10px;padding:12px;margin:10px 0}"
           ".p{font-size:20px;font-weight:700}.w{color:#9a3412}img{border-radius:8px;border:1px solid #e4e4e7}"
           "a{color:#1d4ed8}ul{margin:6px 0;padding-left:18px}")
    h = [f"<html><head><meta charset='utf-8'><style>{css}</style></head><body><div class='c'>",
         f"<h1>Mounjaro KwikPen · mejores precios</h1>",
         f"<div class='m'>{latest['generado'].replace('T', ' ')} · {latest['zona']} (C.P. {latest['cp']})</div>"]
    if reasons:
        h.append("<ul>" + "".join(f"<li>{r}</li>" for r in reasons) + "</ul>")

    for dose in latest["dosis"]:
        r = rec.get(dose)
        h.append(f"<h2>{dose} mg</h2>")
        if not r:
            h.append("<p class='w'>Sin existencia o sin datos en esta corrida.</p>")
            continue
        t, hoy = r["tratamiento"], r["hoy"]
        h.append(f"<div class='b'><div class='m'>Mejor valor para tu tratamiento ({H} plumas)</div>"
                 f"<div class='p'>{t['pharmacy_name']} · {money(t['precio'])} por pluma</div>"
                 f"<div class='m'>{t['escenario']} · cómo comprarla: {t['canal']}"
                 + (f" · {', '.join(t['condiciones'])}" if t["condiciones"] else "")
                 + f" · receta: {t['receta']}</div>"
                 f"<div class='m'>Si solo compras una hoy: {hoy['pharmacy_name']} a {money(hoy['precio'])}</div>"
                 f"<div><a href='{t['url']}'>Ver producto</a></div></div>")
        h.append("<table><tr><th>Farmacia</th><th>En línea</th><th>Hoy</th><th>Por pluma</th><th>Promos</th></tr>")
        for o in latest["ofertas"]:
            if o["dose"] != dose:
                continue
            v = o["valor"] or {}
            promos = ", ".join(p["label"] for p in o["promos"][:3]) or "—"
            stock = "" if o["in_stock"] is not False else " <span class='w'>(agotado)</span>"
            h.append(f"<tr><td><a href='{o['url']}'>{o['pharmacy_name']}</a>{stock}</td>"
                     f"<td>{money(o['precio_linea'])}</td><td>{money(v.get('precio_hoy'))}</td>"
                     f"<td><b>{money(v.get('promedio_por_pluma'))}</b></td><td>{promos}</td></tr>")
        h.append("</table>")

    if latest["banners"]:
        h.append("<h2>Banners y promos detectadas</h2>")
        for b in latest["banners"][:8]:
            link = b["link"] or b["pagina"]
            h.append(f"<div style='margin:10px 0'><a href='{link}'><img src='{b['src']}' width='260'></a><br>"
                     f"<span class='m'>{b['pharmacy_name']} · {', '.join(b['promos']) or b['alt'] or 'sin texto detectado'}</span></div>")
    if latest["errores"]:
        h.append("<h2>Fallas</h2><ul>" + "".join(
            f"<li class='w'>{latest['farmacias'].get(k, k)}: {v[:150]}</li>" for k, v in latest["errores"].items()) + "</ul>")
    h.append("<p><a href='https://forozco.github.io/mounjaro-tracker/'>Ver el comparador completo →</a></p>")
    h.append("<p class='m'>Los precios y promos vienen de las páginas públicas de cada farmacia; "
             "las promos leídas de imágenes pueden tener condiciones (tarjeta de lealtad, límite de piezas). Verifica antes de comprar.</p>")
    h.append("</div></body></html>")
    return "".join(h)


def send(subject: str, html: str) -> bool:
    user, pwd = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD")
    to = os.environ.get("EMAIL_TO") or user
    if not (user and pwd and to):
        print("Sin credenciales de correo: el reporte quedó en data/last_email.html")
        return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.set_content("Tu cliente de correo no muestra HTML. Abre el dashboard para ver el reporte.")
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
    bits = [f"{d} mg: {r['tratamiento']['pharmacy_name']} {money(r['tratamiento']['precio'])}/pluma"
            for d, r in rec.items() if r]
    subject = ("💊 " if urgent else "📋 ") + " · ".join(bits or ["Mounjaro: revisión"])
    if os.environ.get("DRY_RUN") == "1":
        print("DRY_RUN:", subject, "|", "; ".join(reasons))
        return
    send(subject, html)
