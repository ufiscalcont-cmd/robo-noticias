"""Resumo editorial da edição — 100% gratuito.

1º) GitHub Models (IA gratuita do GitHub, usa o GITHUB_TOKEN do próprio Actions).
2º) Se a IA não estiver disponível: resumo automático sem IA, montado a partir
    das notícias mais repercutidas, com citações diretas das manchetes.

- Usa SOMENTE as manchetes coletadas: o modelo é instruído a não acrescentar
  fatos, números ou nomes que não estejam nelas.
- Ignora notícias marcadas como possível fake news.
- As referências são montadas pelo próprio código, no padrão ABNT NBR 6023:2018,
  a partir dos dados reais de cada notícia citada (nada é inventado pelo modelo).
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
from datetime import datetime

from .coletor import chave
from .janela import Janela

log = logging.getLogger(__name__)

API_URL = "https://models.github.ai/inference/chat/completions"
MODELOS_PADRAO = ["openai/gpt-4o", "openai/gpt-4o-mini"]
MESES = ["jan.", "fev.", "mar.", "abr.", "maio", "jun.", "jul.", "ago.", "set.", "out.", "nov.", "dez."]

SISTEMA = """Você é editor-chefe de um boletim de notícias e revisor de língua portuguesa \
com longa experiência em revisão literária. Escreve na norma-padrão do português do Brasil, \
segundo o Acordo Ortográfico vigente, com pontuação, concordância, regência e crase impecáveis.

Sua tarefa: redigir um resumo geral, curto e envolvente, das notícias mais relevantes do período, \
para leitores do Nordeste — em especial empresários, contadores e gestores.

Regras obrigatórias:
1. Use EXCLUSIVAMENTE as informações das manchetes fornecidas. Não acrescente fatos, números, \
nomes, datas, causas, consequências ou contexto que não estejam explícitos nelas. Na dúvida, omita.
2. Seja politicamente neutro: nada de opiniões, juízos de valor ou adjetivos que qualifiquem \
pessoas, partidos ou governos. Informe; não opine.
3. Atribua as informações às fontes no próprio texto (por exemplo: "conforme o g1", \
"segundo a Folha de S.Paulo"), como recomenda a ABNT NBR 10520 para citações indiretas.
4. Priorize o que tem maior impacto: tributos, economia, decisões de governo, Bahia e Sergipe, \
e grandes acontecimentos nacionais e internacionais.
5. Tom: jornalístico e elegante, com uma abertura que desperte a curiosidade do leitor \
e transições fluidas entre os assuntos. Sem clichês, sem sensacionalismo, sem exclamações.
6. Extensão: de 3 a 5 parágrafos curtos, entre 180 e 280 palavras no total. Números por extenso \
até dez; siglas na forma consagrada (IBS, CBS, STF).
7. Responda APENAS com um JSON válido, sem markdown, no formato:
{"titulo": "título curto e atraente para o resumo", "paragrafos": ["...", "..."], "citadas": [ids das notícias usadas]}"""


def _entrada(resultado: list[dict], max_por_topico: int = 10) -> tuple[str, dict]:
    linhas, por_id, i = [], {}, 0
    for t in resultado:
        validas = [n for n in t["noticias"] if n.nivel not in ("alto", "atencao")]
        for n in validas[:max_por_topico]:
            i += 1
            por_id[i] = n
            linhas.append(f"[{i}] ({t['nome']}) {n.titulo} — {n.fonte}")
    return "\n".join(linhas), por_id


def _chamar_api(env: dict, mensagem: str, modelo: str) -> str:
    corpo = {"model": modelo, "temperature": 0.4, "max_tokens": 1500,
             "messages": [{"role": "system", "content": SISTEMA},
                          {"role": "user", "content": mensagem}]}
    req = urllib.request.Request(
        API_URL, data=json.dumps(corpo).encode(), method="POST",
        headers={"Authorization": f"Bearer {env['GITHUB_TOKEN']}", "Content-Type": "application/json",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        dados = json.loads(resp.read())
    return dados["choices"][0]["message"]["content"]


def _ler_json(texto: str) -> dict:
    inicio, fim = texto.find("{"), texto.rfind("}")
    if inicio < 0 or fim < 0:
        raise ValueError("resposta sem JSON")
    dados = json.loads(texto[inicio:fim + 1])
    paragrafos = [p.strip() for p in dados.get("paragrafos", []) if isinstance(p, str) and p.strip()]
    if not paragrafos:
        raise ValueError("resumo vazio")
    return {"titulo": str(dados.get("titulo", "")).strip(), "paragrafos": paragrafos,
            "citadas": [int(x) for x in dados.get("citadas", []) if str(x).isdigit()]}


def data_abnt(d: datetime) -> str:
    return f"{d.day} {MESES[d.month - 1]} {d.year}"


def referencia_abnt(n, acesso: datetime, tz) -> str:
    """ABNT NBR 6023:2018 — notícia on-line sem autor: entrada pelo título,
    primeira palavra em maiúsculas; nome do veículo em destaque (marcado com **)."""
    titulo = n.titulo.strip().rstrip(".")
    partes = titulo.split(" ", 1)
    titulo = partes[0].upper() + (" " + partes[1] if len(partes) > 1 else "")
    pub = n.publicada.astimezone(tz)
    return (f"{titulo}. **{n.fonte}**, [S. l.], {data_abnt(pub)}. "
            f"Disponível em: {n.link}. Acesso em: {data_abnt(acesso)}.")


def _referencias(citadas: list, janela: Janela) -> list[str]:
    tz = janela.fim.tzinfo
    agora = datetime.now(tz)
    return sorted({referencia_abnt(n, agora, tz) for n in citadas}, key=chave)


def _com_ia(env: dict, janela: Janela, resultado: list[dict]) -> dict | None:
    lista, por_id = _entrada(resultado)
    if len(por_id) < 3:
        return None
    pedido = (f"Período: {janela.edicao.lower()} de {janela.descricao}.\n\n"
              f"Manchetes (id, tópico, título — fonte):\n{lista}")
    modelos = [m.strip() for m in (env.get("RESUMO_MODELO") or "").split(",") if m.strip()] or MODELOS_PADRAO
    ultimo = None
    for modelo in modelos:
        for tentativa in range(1, 3):
            try:
                dados = _ler_json(_chamar_api(env, pedido, modelo))
                citadas = [por_id[i] for i in dict.fromkeys(dados["citadas"]) if i in por_id]
                return {"titulo": dados["titulo"], "paragrafos": dados["paragrafos"],
                        "referencias": _referencias(citadas, janela), "origem": f"IA ({modelo})"}
            except Exception as e:
                ultimo = e
                log.warning("Resumo com %s falhou (%s/2): %s", modelo, tentativa, e)
                time.sleep(5 * tentativa)
    raise RuntimeError(f"IA indisponível: {ultimo}")


# ------------------------------------------------------------- sem IA
ABERTURAS = {
    "Tributos e Contabilidade": "No campo tributário e contábil",
    "Bahia e Sergipe": "No cenário regional",
    "Economia": "Na economia",
    "Política e Brasil": "No noticiário nacional",
    "Mundo": "No exterior",
    "Tecnologia": "Em tecnologia",
    "Saúde e Ciência": "Em saúde e ciência",
    "Esportes": "No esporte",
}


EXTENSO = ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez"]
VERBOS = ["informa", "noticia", "destaca", "relata", "registra", "publica"]


def numero(n: int, feminino: bool = False) -> str:
    """Por extenso até dez (norma jornalística); algarismos acima disso."""
    if 0 <= n <= 10:
        t = EXTENSO[n]
        return {"um": "uma", "dois": "duas"}.get(t, t) if feminino else t
    return str(n)


def _veiculo(fonte: str, prep: str = "") -> str:
    """Nome do veículo com artigo correto e contração: 'o g1', 'da Folha de S.Paulo',
    'do jornal A Tarde' (nomes que já começam com artigo ganham 'o jornal')."""
    f = chave(fonte)
    if f.startswith(("a ", "o ", "as ", "os ")):
        art, nome = "o", f"jornal {fonte}"
    else:
        femininos = ("folha", "agencia", "revista", "gazeta", "tribuna", "veja", "istoe", "exame",
                     "cnn", "bbc", "band", "jovem pan", "carta", "voz", "noticia", "rede", "radio")
        art, nome = ("a" if f.startswith(femininos) else "o"), fonte
    if prep == "de":
        art = "da" if art == "a" else "do"
    elif prep == "em":
        art = "na" if art == "a" else "no"
    return f"{art} {nome}"


MESES_EXTENSO = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
                 "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _periodo(janela: Janela) -> str:
    i, f = janela.inicio, janela.fim
    dia = lambda d: f"{d.day}{'º' if d.day == 1 else ''} de {MESES_EXTENSO[d.month - 1]}"
    if i.date() == f.date():
        return f"entre as {i.hour}h e as {f.hour}h de {dia(f)}"
    return f"entre as {i.hour}h de {dia(i)} e as {f.hour}h de {dia(f)}"


def _repercussao(n, todas: list) -> int:
    from .credibilidade import _parecido, _tokens
    tk = _tokens(n.titulo)
    return len({chave(m.fonte) for m in todas if m is not n and _parecido(tk, _tokens(m.titulo))})


def sem_ia(janela: Janela, resultado: list[dict], todas: list) -> dict | None:
    """Resumo extrativo: as manchetes mais repercutidas, citadas entre aspas e
    atribuídas às fontes (citação direta, ABNT NBR 10520). Não reescreve fatos."""
    blocos = []
    for t in resultado:
        validas = [n for n in t["noticias"] if n.nivel not in ("alto", "atencao", "checagem")]
        if validas:
            principal = max(validas[:15], key=lambda n: _repercussao(n, todas))
            blocos.append((t["nome"], principal, _repercussao(principal, todas)))
    if len(blocos) < 2:
        return None
    total = sum(len(t["noticias"]) for t in resultado)
    destaque = max(blocos, key=lambda b: b[2])
    nome, n, rep = destaque
    extra = (f", assunto que repercutiu em outros {numero(rep)} veículos" if rep > 1 else
             ", assunto também noticiado por outro veículo" if rep == 1 else "")
    paragrafos = [
        f"Esta edição reúne {numero(total, feminino=True)} notícias publicadas {_periodo(janela)}. "
        f"O destaque do período vem {_veiculo(n.fonte, 'de')}: “{n.titulo.rstrip('.')}”{extra}."
    ]
    frases = []
    for k, (nome, n, _) in enumerate(b for b in blocos if b[1] is not destaque[1]):
        inicio = ABERTURAS.get(nome, f"Em {nome.lower()}")
        frases.append(f"{inicio}, {_veiculo(n.fonte)} {VERBOS[k % len(VERBOS)]}: “{n.titulo.rstrip('.')}”.")
    for i in range(0, len(frases), 2):  # dois assuntos por parágrafo
        paragrafos.append(" ".join(frases[i:i + 2]))
    citadas = [b[1] for b in blocos]
    return {"titulo": f"Os destaques da {janela.edicao.lower()}", "paragrafos": paragrafos[:5],
            "referencias": _referencias(citadas, janela), "origem": "automático (sem IA)"}


def gerar(env: dict, janela: Janela, resultado: list[dict], todas: list | None = None) -> dict | None:
    modo = (env.get("RESUMO") or "auto").lower()
    if modo in ("nao", "não", "false", "0", "desligado"):
        return None
    if modo != "sem_ia" and env.get("GITHUB_TOKEN"):
        try:
            r = _com_ia(env, janela, resultado)
            if r:
                return r
        except Exception as e:
            log.warning("Usando resumo sem IA: %s", e)
    return sem_ia(janela, resultado, todas or [n for t in resultado for n in t["noticias"]])
