"""Monta o texto do WhatsApp e o HTML do e-mail."""
from __future__ import annotations

import html
import re

from .janela import Janela


def _hora(n, tz) -> str:
    return n.publicada.astimezone(tz).strftime("%H:%M")


def _limpo(texto: str) -> str:
    # evita que * _ ~ do título quebrem a formatação do WhatsApp
    return texto.replace("*", "").replace("_", " ").replace("~", "")


MARCA = "Notícias uFiscal"
SLOGAN = "Inteligência em negócios"
OURO, PRETO = "#B8962E", "#000000"

SELO = {"alto": "🔴", "atencao": "🟡", "checagem": "🔎"}
LEGENDA = ("Alertas automáticos de possível fake news, baseados na fonte, no tom do título, "
           "na confirmação por outros veículos e em agências de checagem. "
           "Não são veredito: confirme antes de compartilhar.")


def alertas(resultado: list[dict]) -> tuple[int, int]:
    todas = [n for t in resultado for n in t["noticias"]]
    return (sum(n.nivel == "alto" for n in todas), sum(n.nivel == "atencao" for n in todas))


def total(resultado: list[dict]) -> int:
    return sum(len(t["noticias"]) for t in resultado)


def assunto(janela: Janela, resultado: list[dict]) -> str:
    return f"📰 {MARCA} · {janela.edicao} · {janela.descricao} · {total(resultado)} itens"


# ---------------------------------------------------------------- WhatsApp
def texto_whatsapp(janela: Janela, resultado: list[dict], max_por_topico: int = 6,
                   incluir_links: bool = False, erros: list[str] | None = None,
                   resumo: dict | None = None) -> str:
    tz = janela.fim.tzinfo
    linhas = [f"📰 *NOTÍCIAS uFISCAL — {janela.edicao.upper()}*", f"🗓️ {janela.descricao}"]
    alto, atencao = alertas(resultado)
    if alto or atencao:
        linhas.append(f"⚠️ *Possíveis fake news:* 🔴 {alto} alto risco · 🟡 {atencao} atenção")
    if resumo:
        linhas += ["", f"✍️ *{_limpo(resumo['titulo']).upper()}*" if resumo.get("titulo") else "✍️ *PANORAMA*"]
        for par in resumo["paragrafos"]:
            linhas += ["", _limpo(par)]
        linhas += ["", "_Referências (ABNT) no e-mail._", "", "━━━━━━━━━━━━━━━"]
    for t in resultado:
        if not t["noticias"]:
            continue
        linhas += ["", f"{t['emoji']} *{t['nome'].upper()}* ({len(t['noticias'])})"]
        # notícias com alerta sempre aparecem, mesmo além do limite do tópico
        mostrar = t["noticias"][:max_por_topico]
        mostrar += [n for n in t["noticias"][max_por_topico:] if n.nivel in ("alto", "atencao")]
        for n in mostrar:
            selo = SELO.get(n.nivel, "•")
            linhas.append(f"{selo} {_limpo(n.titulo)} — _{_limpo(n.fonte)}_ ({_hora(n, tz)})")
            if n.nivel in ("alto", "atencao"):
                rotulo = "POSSÍVEL FAKE NEWS" if n.nivel == "alto" else "atenção"
                linhas.append(f"   ↳ _{rotulo}: {_limpo('; '.join(n.motivos))}_")
                if n.checagem:
                    linhas.append(f"   ↳ checagem: {n.checagem}")
            if incluir_links and n.link:
                linhas.append(f"  {n.link}")
        resto = len(t["noticias"]) - len(mostrar)
        if resto > 0:
            linhas.append(f"  _+{resto} no e-mail_")
    if total(resultado) == 0:
        linhas += ["", "Nenhuma notícia encontrada nesta janela."]
    if erros:
        linhas += ["", f"⚠️ {len(erros)} fonte(s) com falha na coleta."]
    if alto or atencao:
        linhas += ["", f"_🔴 alto risco · 🟡 atenção · 🔎 checagem — {LEGENDA}_"]
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
def texto_email(janela: Janela, resultado: list[dict], erros: list[str] | None = None,
                resumo: dict | None = None) -> str:
    tz = janela.fim.tzinfo
    linhas = [f"NOTÍCIAS uFISCAL — {janela.edicao.upper()}", janela.descricao]
    if resumo:
        linhas += ["", (resumo.get("titulo") or "Panorama").upper(), ""]
        linhas += [f"    {par}" for par in resumo["paragrafos"]]
        if resumo.get("referencias"):
            linhas += ["", "REFERÊNCIAS", ""] + [r.replace("**", "") for r in resumo["referencias"]]
    for t in resultado:
        if not t["noticias"]:
            continue
        linhas += ["", f"== {t['nome'].upper()} ({len(t['noticias'])}) =="]
        for n in t["noticias"]:
            selo = {"alto": "[POSSÍVEL FAKE NEWS] ", "atencao": "[ATENÇÃO] ", "checagem": "[CHECAGEM] "}.get(n.nivel, "")
            linhas.append(f"- [{_hora(n, tz)}] {selo}{n.titulo} ({n.fonte})\n  {n.link}")
            if n.nivel in ("alto", "atencao"):
                linhas.append(f"  Motivo: {'; '.join(n.motivos)}" + (f" | Checagem: {n.checagem}" if n.checagem else ""))
    if any(alertas(resultado)):
        linhas += ["", LEGENDA]
    if erros:
        linhas += ["", "Falhas na coleta:"] + [f"- {e}" for e in erros]
    return "\n".join(linhas)


def _item_html(n, tz) -> str:
    e = html.escape
    cores = {"alto": ("#fee2e2", "#b91c1c", "🔴 POSSÍVEL FAKE NEWS"),
             "atencao": ("#fef3c7", "#92400e", "🟡 ATENÇÃO"),
             "checagem": ("#e0f2fe", "#075985", "🔎 CHECAGEM")}
    selo = alerta = ""
    if n.nivel in cores:
        fundo, cor, rotulo = cores[n.nivel]
        selo = (f'<span style="background:{fundo};color:{cor};font-size:11px;font-weight:700;'
                f'padding:2px 6px;border-radius:4px;margin-right:6px">{rotulo}</span>')
        if n.nivel != "checagem":
            link = (f' · <a href="{e(n.checagem)}" style="color:{cor}">ver checagem</a>' if n.checagem else "")
            alerta = (f'<div style="background:{fundo};color:{cor};font-size:12px;padding:6px 8px;'
                      f'border-radius:4px;margin-top:5px">{e("; ".join(n.motivos).capitalize())}{link}</div>')
    return (f'<tr><td style="padding:8px 0;border-bottom:1px solid #eef0f3">{selo}'
            f'<a href="{e(n.link)}" style="color:#111827;font-weight:600;text-decoration:none;font-size:15px;line-height:1.35">{e(n.titulo)}</a>'
            f'<div style="color:#6b7280;font-size:12px;margin-top:3px">{e(n.fonte)} · {_hora(n, tz)}</div>{alerta}</td></tr>')


LOGO_CID = "logo-ufiscal"


def _resumo_html(resumo: dict | None) -> str:
    if not resumo:
        return ""
    e = html.escape
    pars = "".join(
        f'<p style="margin:0 0 12px;text-indent:1.25cm;text-align:justify;font:16px/1.65 Georgia,\'Times New Roman\',serif;color:#1f2937">{e(p)}</p>'
        for p in resumo["paragrafos"])
    refs = ""
    if resumo.get("referencias"):
        itens = "".join(
            '<p style="margin:0 0 8px;text-align:left;font:12px/1.45 Georgia,serif;color:#4b5563;word-break:break-word">'
            + re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", e(r)) + "</p>"
            for r in resumo["referencias"])
        refs = (f'<div style="margin-top:16px;padding-top:12px;border-top:1px solid #e5e7eb">'
                f'<div style="text-align:center;font:700 12px Arial,sans-serif;letter-spacing:.08em;color:#374151;margin-bottom:10px">REFERÊNCIAS</div>{itens}</div>')
    titulo = e(resumo.get("titulo") or "Panorama")
    return (f'<div style="margin-top:20px;padding:20px 22px;background:#fbf8f1;border-left:4px solid {OURO};border-radius:6px">'
            f'<div style="font:700 11px Arial,sans-serif;letter-spacing:.14em;color:{OURO};text-transform:uppercase;margin-bottom:6px">Panorama da edição</div>'
            f'<h2 style="margin:0 0 14px;font:700 22px/1.3 Georgia,serif;color:{PRETO}">{titulo}</h2>{pars}{refs}</div>')


def html_email(janela: Janela, resultado: list[dict], erros: list[str] | None = None,
               logo_src: str = f"cid:{LOGO_CID}", resumo: dict | None = None) -> str:
    tz = janela.fim.tzinfo
    e = html.escape
    indice = " · ".join(
        f'<a href="#t{i}" style="color:{PRETO};text-decoration:none;border-bottom:1px solid {OURO}">{e(t["emoji"])} {e(t["nome"])} ({len(t["noticias"])})</a>'
        for i, t in enumerate(resultado) if t["noticias"]
    )
    secoes = []
    for i, t in enumerate(resultado):
        if not t["noticias"]:
            continue
        itens = "".join(_item_html(n, tz) for n in t["noticias"])
        secoes.append(
            f'<h2 id="t{i}" style="font-size:17px;margin:28px 0 6px;padding-bottom:6px;border-bottom:2px solid {OURO};color:{PRETO}">'
            f'{e(t["emoji"])} {e(t["nome"])} <span style="color:#9ca3af;font-weight:400">({len(t["noticias"])})</span></h2>'
            f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0">{itens}</table>'
        )
    if not secoes:
        secoes.append('<p style="color:#6b7280">Nenhuma notícia encontrada nesta janela.</p>')
    alto, atencao = alertas(resultado)
    resumo_alerta = legenda = ""
    if alto or atencao:
        resumo_alerta = (f'<div style="margin-top:12px;background:#fff7ed;border:1px solid #fdba74;border-radius:6px;'
                         f'padding:8px 12px;font-size:13px;color:#9a3412">⚠️ <b>Possíveis fake news nesta edição:</b> '
                         f'🔴 {alto} alto risco · 🟡 {atencao} atenção</div>')
        legenda = f'<p style="color:#6b7280;font-size:12px;margin-top:20px">🔴 alto risco · 🟡 atenção · 🔎 checagem — {e(LEGENDA)}</p>'
    aviso = ""
    if erros:
        lista = "".join(f"<li>{e(x)}</li>" for x in erros)
        aviso = (f'<div style="background:#fef3c7;border:1px solid #f59e0b;border-radius:6px;padding:10px 14px;'
                 f'margin-top:24px;font-size:13px"><b>⚠️ Falhas na coleta</b><ul style="margin:6px 0 0 18px;padding:0">{lista}</ul></div>')
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="margin:0;background:#f3f4f6;font-family:Segoe UI,Arial,sans-serif">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center" style="padding:20px 10px">
<table role="presentation" width="640" style="max-width:640px;width:100%;background:#fff;border-radius:10px;overflow:hidden" cellspacing="0" cellpadding="0">
<tr><td style="background:{PRETO};padding:18px 28px;border-bottom:3px solid {OURO}">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr>
<td style="vertical-align:middle"><img src="{logo_src}" width="210" alt="uFiscal — {SLOGAN}" style="display:block;width:210px;max-width:100%;height:auto;border:0;color:#fff;font:700 22px Arial,sans-serif"></td>
<td align="right" style="vertical-align:middle;color:{OURO};font:700 13px Arial,sans-serif;letter-spacing:.14em;text-transform:uppercase">Notícias</td>
</tr></table></td></tr>
<tr><td style="padding:22px 28px 24px">
<div style="font-size:12px;letter-spacing:.08em;color:{OURO};text-transform:uppercase;font-weight:700">{e(janela.edicao)}</div>
<div style="color:#374151;font-size:14px">{e(janela.descricao)} · <b>{total(resultado)}</b> notícias</div>
{resumo_alerta}
{_resumo_html(resumo)}
<div style="margin-top:22px;font:700 11px Arial,sans-serif;letter-spacing:.14em;color:{OURO};text-transform:uppercase">Notícias por tópico</div>
<div style="margin-top:6px;font-size:13px;line-height:1.9">{indice}</div>
{''.join(secoes)}{legenda}{aviso}
<p style="color:#9ca3af;font-size:11px;margin-top:28px">{MARCA} · enviado automaticamente · uFiscal — {SLOGAN}</p>
</td></tr></table></td></tr></table></body></html>"""
