"""Coleta de notícias via RSS (Google News e qualquer feed RSS/Atom)."""
from __future__ import annotations

import logging
import math
import re
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable

from .janela import Janela

log = logging.getLogger(__name__)

GOOGLE = "https://news.google.com/rss"
GOOGLE_PARAMS = "hl=pt-BR&gl=BR&ceid=BR:pt-419"
USER_AGENT = "Mozilla/5.0 (compatible; RoboNoticias/1.0)"
ATOM = "{http://www.w3.org/2005/Atom}"


@dataclass
class Noticia:
    titulo: str
    link: str
    fonte: str
    publicada: datetime
    dominio: str = ""
    # preenchidos pela análise de credibilidade
    nivel: str = ""          # "", "atencao", "alto" ou "checagem"
    motivos: list = field(default_factory=list)
    checagem: str = ""       # link de checagem relacionada, se houver
    anterior: str = ""       # se for desdobramento: edição em que o assunto já saiu


def _dominio(url: str) -> str:
    host = urllib.parse.urlparse(url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


# ---------------------------------------------------------------- download
def baixar(url: str, tentativas: int = 4, timeout: int = 25) -> bytes:
    ultimo_erro: Exception | None = None
    for n in range(1, tentativas + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:  # rede instável: tenta de novo com espera crescente
            ultimo_erro = e
            log.warning("Falha ao baixar (%s/%s) %s: %s", n, tentativas, url, e)
            if n < tentativas:
                time.sleep(2 ** n)
    raise RuntimeError(f"Não foi possível baixar {url}: {ultimo_erro}")


def url_da_fonte(fonte: dict, dias: int = 1) -> str:
    tipo = fonte["tipo"]
    if tipo == "google_destaques":
        return f"{GOOGLE}?{GOOGLE_PARAMS}"
    if tipo == "google_topico":
        return f"{GOOGLE}/headlines/section/topic/{fonte['id']}?{GOOGLE_PARAMS}"
    if tipo == "google_busca":
        q = f"{fonte['q']} when:{dias}d"
        return f"{GOOGLE}/search?q={urllib.parse.quote_plus(q)}&{GOOGLE_PARAMS}"
    if tipo == "rss":
        return fonte["url"]
    raise ValueError(f"Tipo de fonte desconhecido: {tipo}")


# ------------------------------------------------------------------- parse
def _txt(el, tag: str) -> str:
    if el is None:
        return ""
    filho = el.find(tag)
    return (filho.text or "").strip() if filho is not None and filho.text else ""


def _data(valor: str) -> datetime | None:
    if not valor:
        return None
    try:
        dt = parsedate_to_datetime(valor)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_feed(dados: bytes) -> list[Noticia]:
    raiz = ET.fromstring(dados)
    noticias: list[Noticia] = []

    canal = raiz.find("channel")
    nome_canal = _txt(canal, "title")
    for item in raiz.iter("item"):  # RSS 2.0
        titulo = _txt(item, "title")
        src = item.find("source")
        fonte = (src.text or "").strip() if src is not None and src.text else nome_canal
        link = _txt(item, "link")
        dominio = _dominio(src.get("url", "")) if src is not None else ""
        dominio = dominio if dominio and dominio != "news.google.com" else (
            "" if "news.google.com" in link else _dominio(link))
        if fonte and titulo.endswith(f" - {fonte}"):
            titulo = titulo[: -len(fonte) - 3]
        dt = _data(_txt(item, "pubDate"))
        if titulo and dt:
            noticias.append(Noticia(titulo, link, fonte, dt, dominio))

    nome_atom = _txt(raiz, f"{ATOM}title")
    for entry in raiz.iter(f"{ATOM}entry"):  # Atom
        link_el = entry.find(f"{ATOM}link")
        link = link_el.get("href", "") if link_el is not None else ""
        dt = _data(_txt(entry, f"{ATOM}published") or _txt(entry, f"{ATOM}updated"))
        titulo = _txt(entry, f"{ATOM}title")
        if titulo and dt:
            noticias.append(Noticia(titulo, link, nome_atom, dt, _dominio(link)))
    return noticias


def chave(titulo: str) -> str:
    t = unicodedata.normalize("NFKD", titulo).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()[:90]


# ------------------------------------------------------------------ coleta
def coletar(
    topicos: list[dict],
    janela: Janela,
    agora: datetime | None = None,
    baixar_fn: Callable[[str], bytes] = baixar,
    limite_por_topico: int = 40,
    todas: list | None = None,
) -> tuple[list[dict], list[str]]:
    """Retorna ([{nome, emoji, noticias}], [erros]).

    A ordem dos tópicos define a prioridade: uma notícia que aparece em dois
    tópicos fica só no primeiro. Se `todas` for uma lista, recebe todas as
    notícias da janela (com repetidas), usada para checar confirmação cruzada.
    """
    agora = agora or datetime.now(janela.fim.tzinfo)
    dias = max(1, math.ceil((agora - janela.inicio).total_seconds() / 86400))
    vistos: set[str] = set()
    resultado, erros = [], []

    for topico in topicos:
        candidatas: list[Noticia] = []
        for fonte in topico["fontes"]:
            url = url_da_fonte(fonte, dias)
            try:
                candidatas.extend(parse_feed(baixar_fn(url)))
            except Exception as e:
                erros.append(f"{topico['nome']}: {e}")
                log.error("Erro na fonte %s: %s", url, e)

        candidatas.sort(key=lambda n: n.publicada, reverse=True)
        escolhidas = []
        for n in candidatas:
            if not janela.contem(n.publicada):
                continue
            if todas is not None:
                todas.append(n)
            k_titulo, k_link = chave(n.titulo), n.link
            if k_titulo in vistos or (k_link and k_link in vistos):
                continue
            vistos.update({k_titulo, k_link})
            escolhidas.append(n)
            if len(escolhidas) >= limite_por_topico:
                break
        resultado.append(
            {"nome": topico["nome"], "emoji": topico.get("emoji", "📌"), "noticias": escolhidas}
        )
    return resultado, erros


def coletar_checagens(fontes: list[dict], baixar_fn: Callable[[str], bytes] = baixar,
                      dias: int = 7) -> tuple[list[Noticia], list[str]]:
    """Baixa as checagens recentes das agências de fact-checking."""
    checagens, erros, vistos = [], [], set()
    for fonte in fontes:
        try:
            for n in parse_feed(baixar_fn(url_da_fonte(fonte, dias))):
                if n.link not in vistos:
                    vistos.add(n.link)
                    checagens.append(n)
        except Exception as e:
            erros.append(f"Checagens: {e}")
            log.error("Erro ao buscar checagens: %s", e)
    return checagens, erros
