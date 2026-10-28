"""Monta o texto do WhatsApp e o HTML do e-mail."""
from __future__ import annotations

import html

from .janela import Janela


def _hora(n, tz) -> str:
    return n.publicada.astimezone(tz).strftime("%H:%M")


def _limpo(texto: str) -> str:
    # evita que * _ ~ do título quebrem a formatação do WhatsApp
    return texto.replace("*", "").replace("_", " ").replace("~", "")


def total(resultado: list[dict]) -> int:
    return sum(len(t["noticias"]) for t in resultado)


def assunto(janela: Janela, resultado: list[dict]) -> str:
    return f"📰 Notícias · {janela.edicao} · {janela.descricao} · {total(resultado)} itens"


# ---------------------------------------------------------------- WhatsApp
def texto_whatsapp(janela: Janela, resultado: list[dict], max_por_topico: int = 6,
                   incluir_links: bool = False, erros: list[str] | None = None) -> str:
    tz = janela.fim.tzinfo
    linhas = [f"📰 *RESUMO DE NOTÍCIAS — {janela.edicao.upper()}*", f"🗓️ {janela.descricao}"]
    for t in resultado:
        if not t["noticias"]:
            continue
        linhas += ["", f"{t['emoji']} *{t['nome'].upper()}* ({len(t['noticias'])})"]
        for n in t["noticias"][:max_por_topico]:
            linhas.append(f"• {_limpo(n.titulo)} — _{_limpo(n.fonte)}_ ({_hora(n, tz)})")
            if incluir_links and n.link:
                linhas.append(f"  {n.link}")
        resto = len(t["noticias"]) - max_por_topico
        if resto > 0:
            linhas.append(f"  _+{resto} no e-mail_")
    if total(resultado) == 0:
        linhas += ["", "Nenhuma notícia encontrada nesta janela."]
    if erros:
        linhas += ["", f"⚠️ {len(erros)} fonte(s) com falha na coleta."]
    linhas += ["", f"_Total: {total(resultado)} notícias · lista completa com links no e-mail_"]
    return "\n".join(linhas)


def dividir(texto: str, limite: int) -> list[str]:
    """Quebra em partes ≤ limite, preferindo cortar entre tópicos."""
    if len(texto) <= limite:
        return [texto]
    blocos = texto.split("\n\n")
    partes, atual = [], ""
    for bloco in blocos:
        while len(bloco) > limite:  # bloco gigante: corta por linhas
            corte = bloco.rfind("\n", 0, limite)
            corte = corte if corte > 0 else limite
            if atual:
                partes.append(atual)
                atual = ""
            partes.append(bloco[:corte])
            bloco = bloco[corte:].lstrip("\n")
        candidato = f"{atual}\n\n{bloco}" if atual else bloco
        if len(candidato) <= limite:
            atual = candidato
        else:
            partes.append(atual)
            atual = bloco
    if atual:
        partes.append(atual)
    if len(partes) > 1:
        partes = [f"({i}/{len(partes)})\n{p}" for i, p in enumerate(partes, 1)]
    return partes


# ------------------------------------------------------------------ e-mail
def texto_email(janela: Janela, resultado: list[dict], erros: list[str] | None = None) -> str:
    tz = janela.fim.tzinfo
    linhas = [f"RESUMO DE NOTÍCIAS — {janela.edicao.upper()}", janela.descricao]
    for t in resultado:
        if not t["noticias"]:
            continue
        linhas += ["", f"== {t['nome'].upper()} ({len(t['noticias'])}) =="]
        for n in t["noticias"]:
            linhas.append(f"- [{_hora(n, tz)}] {n.titulo} ({n.fonte})\n  {n.link}")
    if erros:
        linhas += ["", "Falhas na coleta:"] + [f"- {e}" for e in erros]
    return "\n".join(linhas)


def html_email(janela: Janela, resultado: list[dict], erros: list[str] | None = None) -> str:
    tz = janela.fim.tzinfo
    e = html.escape
    indice = " · ".join(
        f'<a href="#t{i}" style="color:#1d4ed8;text-decoration:none">{e(t["emoji"])} {e(t["nome"])} ({len(t["noticias"])})</a>'
        for i, t in enumerate(resultado) if t["noticias"]
    )
    secoes = []
    for i, t in enumerate(resultado):
        if not t["noticias"]:
            continue
        itens = "".join(
            f'<tr><td style="padding:8px 0;border-bottom:1px solid #eef0f3">'
            f'<a href="{e(n.link)}" style="color:#111827;font-weight:600;text-decoration:none;font-size:15px;line-height:1.35">{e(n.titulo)}</a>'
            f'<div style="color:#6b7280;font-size:12px;margin-top:3px">{e(n.fonte)} · {_hora(n, tz)}</div></td></tr>'
            for n in t["noticias"]
        )
        secoes.append(
            f'<h2 id="t{i}" style="font-size:17px;margin:28px 0 6px;padding-bottom:6px;border-bottom:2px solid #1d4ed8;color:#1d4ed8">'
            f'{e(t["emoji"])} {e(t["nome"])} <span style="color:#9ca3af;font-weight:400">({len(t["noticias"])})</span></h2>'
            f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0">{itens}</table>'
        )
    if not secoes:
        secoes.append('<p style="color:#6b7280">Nenhuma notícia encontrada nesta janela.</p>')
    aviso = ""
    if erros:
        lista = "".join(f"<li>{e(x)}</li>" for x in erros)
        aviso = (f'<div style="background:#fef3c7;border:1px solid #f59e0b;border-radius:6px;padding:10px 14px;'
                 f'margin-top:24px;font-size:13px"><b>⚠️ Falhas na coleta</b><ul style="margin:6px 0 0 18px;padding:0">{lista}</ul></div>')
    return f"""<!doctype html><html lang="pt-BR"><body style="margin:0;background:#f3f4f6;font-family:Segoe UI,Arial,sans-serif">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center" style="padding:20px 10px">
<table role="presentation" width="640" style="max-width:640px;width:100%;background:#fff;border-radius:10px" cellspacing="0" cellpadding="0"><tr><td style="padding:24px 28px">
<div style="font-size:12px;letter-spacing:.08em;color:#6b7280;text-transform:uppercase">{e(janela.edicao)}</div>
<h1 style="margin:4px 0 2px;font-size:24px;color:#111827">Resumo de Notícias</h1>
<div style="color:#374151;font-size:14px">{e(janela.descricao)} · <b>{total(resultado)}</b> notícias</div>
<div style="margin-top:14px;font-size:13px;line-height:1.9">{indice}</div>
{''.join(secoes)}{aviso}
<p style="color:#9ca3af;font-size:11px;margin-top:28px">Enviado automaticamente pelo Robô de Notícias.</p>
</td></tr></table></td></tr></table></body></html>"""
