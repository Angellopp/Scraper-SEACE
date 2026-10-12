"""Avisos de licitaciones nuevas. Todo es opcional: se activa solo si hay variables de entorno.

Telegram:  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
Email:     SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASS, MAIL_TO
"""
import json
import os
import smtplib
import urllib.parse
import urllib.request
from email.message import EmailMessage


def _resumen(lics: list[dict]) -> str:
    lineas = [f"Nuevas licitaciones de fotocopiadoras ({len(lics)}):", ""]
    for l in lics[:15]:
        vr = f"{l['moneda'] or ''} {l['valor_referencial']:,.2f}" if l.get("valor_referencial") else "VR no indicado"
        cierre = f" | cierra {l['cierre_propuestas']}" if l.get("cierre_propuestas") else ""
        lineas.append(f"- {l['entidad']} | {l['nomenclatura']} | {vr}{cierre}")
        lineas.append(f"  {l['descripcion'][:140]}")
    if len(lics) > 15:
        lineas.append(f"... y {len(lics) - 15} mas")
    return "\n".join(lineas)


def enviar(lics: list[dict], log=print):
    if not lics:
        return
    texto = _resumen(lics)
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if tok and chat:
        try:
            data = urllib.parse.urlencode({"chat_id": chat, "text": texto[:4000]}).encode()
            urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data, timeout=20)
            log("Aviso enviado por Telegram")
        except Exception as e:  # noqa: BLE001
            log(f"Telegram fallo: {e}")
    host, to = os.getenv("SMTP_HOST"), os.getenv("MAIL_TO")
    if host and to:
        try:
            m = EmailMessage()
            m["Subject"] = f"[SEACE] {len(lics)} licitaciones nuevas de fotocopiadoras"
            m["From"] = os.getenv("SMTP_USER", to)
            m["To"] = to
            m.set_content(texto)
            with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=30) as s:
                s.starttls()
                if os.getenv("SMTP_USER"):
                    s.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS", ""))
                s.send_message(m)
            log("Aviso enviado por email")
        except Exception as e:  # noqa: BLE001
            log(f"Email fallo: {e}")
