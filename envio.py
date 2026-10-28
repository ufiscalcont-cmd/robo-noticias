"""Envio por e-mail (SMTP) e WhatsApp (CallMeBot, Z-API ou Evolution API)."""
from __future__ import annotations

import json
import logging
import smtplib
import ssl
import time
import urllib.parse
import urllib.request
from email.message import EmailMessage

log = logging.getLogger(__name__)


def _com_tentativas(acao, descricao: str, tentativas: int = 4):
    for n in range(1, tentativas + 1):
        try:
            return acao()
        except Exception as e:
            log.warning("%s falhou (%s/%s): %s", descricao, n, tentativas, e)
            if n == tentativas:
                raise
            time.sleep(5 * n)


def _exigir(env: dict, *chaves: str) -> None:
    faltando = [c for c in chaves if not env.get(c)]
    if faltando:
        raise RuntimeError(f"Configuração ausente: {', '.join(faltando)}")


# ------------------------------------------------------------------ e-mail
def enviar_email(env: dict, assunto: str, texto: str, html: str) -> None:
    _exigir(env, "SMTP_USUARIO", "SMTP_SENHA", "EMAIL_DESTINO")
    host = (env.get("SMTP_HOST") or "smtp.gmail.com")
    porta = int((env.get("SMTP_PORTA") or "465"))
    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = env.get("EMAIL_REMETENTE") or env["SMTP_USUARIO"]
    msg["To"] = env["EMAIL_DESTINO"]
    msg.set_content(texto)
    msg.add_alternative(html, subtype="html")

    def _enviar():
        ctx = ssl.create_default_context()
        if porta == 465:
            with smtplib.SMTP_SSL(host, porta, context=ctx, timeout=60) as s:
                s.login(env["SMTP_USUARIO"], env["SMTP_SENHA"])
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, porta, timeout=60) as s:
                s.starttls(context=ctx)
                s.login(env["SMTP_USUARIO"], env["SMTP_SENHA"])
                s.send_message(msg)

    _com_tentativas(_enviar, "E-mail")
    log.info("E-mail enviado para %s", env["EMAIL_DESTINO"])


# ---------------------------------------------------------------- WhatsApp
LIMITE_PADRAO = {"callmebot": 1500, "zapi": 3500, "evolution": 3500}


def _http(url: str, dados: dict | None = None, headers: dict | None = None) -> str:
    corpo = json.dumps(dados).encode() if dados is not None else None
    h = {"User-Agent": "RoboNoticias/1.0", **(headers or {})}
    if corpo is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=corpo, headers=h, method="POST" if corpo else "GET")
    with urllib.request.urlopen(req, timeout=60) as resp:
        resposta = resp.read().decode(errors="replace")
        if resp.status >= 300:
            raise RuntimeError(f"HTTP {resp.status}: {resposta[:300]}")
        return resposta


def _enviar_parte(env: dict, provedor: str, texto: str) -> None:
    if provedor == "callmebot":
        _exigir(env, "WHATSAPP_NUMERO", "CALLMEBOT_APIKEY")
        q = urllib.parse.urlencode({"phone": env["WHATSAPP_NUMERO"], "text": texto,
                                    "apikey": env["CALLMEBOT_APIKEY"]})
        resp = _http(f"https://api.callmebot.com/whatsapp.php?{q}")
        if "error" in resp.lower() and "queued" not in resp.lower():
            raise RuntimeError(f"CallMeBot recusou: {resp[:300]}")
    elif provedor == "zapi":
        _exigir(env, "WHATSAPP_NUMERO", "ZAPI_INSTANCIA", "ZAPI_TOKEN")
        url = f"https://api.z-api.io/instances/{env['ZAPI_INSTANCIA']}/token/{env['ZAPI_TOKEN']}/send-text"
        headers = {"Client-Token": env["ZAPI_CLIENT_TOKEN"]} if env.get("ZAPI_CLIENT_TOKEN") else {}
        _http(url, {"phone": env["WHATSAPP_NUMERO"], "message": texto}, headers)
    elif provedor == "evolution":
        _exigir(env, "WHATSAPP_NUMERO", "EVOLUTION_URL", "EVOLUTION_INSTANCIA", "EVOLUTION_APIKEY")
        url = f"{env['EVOLUTION_URL'].rstrip('/')}/message/sendText/{env['EVOLUTION_INSTANCIA']}"
        _http(url, {"number": env["WHATSAPP_NUMERO"], "text": texto},
              {"apikey": env["EVOLUTION_APIKEY"]})
    else:
        raise RuntimeError(f"WHATSAPP_PROVEDOR inválido: {provedor}")


def limite_whatsapp(env: dict) -> int:
    provedor = (env.get("WHATSAPP_PROVEDOR") or "callmebot").lower()
    return int(env.get("WHATSAPP_MAX_CARACTERES") or LIMITE_PADRAO.get(provedor, 1500))


def enviar_whatsapp(env: dict, partes: list[str]) -> None:
    provedor = (env.get("WHATSAPP_PROVEDOR") or "callmebot").lower()
    for i, parte in enumerate(partes, 1):
        _com_tentativas(lambda p=parte: _enviar_parte(env, provedor, p), f"WhatsApp parte {i}")
        if i < len(partes):
            time.sleep(4 if provedor == "callmebot" else 1.5)  # respeita limites de taxa
    log.info("WhatsApp enviado (%s parte(s), via %s)", len(partes), provedor)
