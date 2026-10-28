"""Análise de risco de desinformação (fake news).

Não "prova" que algo é falso: calcula um RISCO a partir de sinais que os
checadores profissionais usam como triagem e marca a notícia com um alerta.

Pontuação (quanto maior, mais suspeita):
  fonte na lista de suspeitas ............ +3
  fonte não reconhecida .................. +1   (fonte reconhecida: −1)
  título sensacionalista ................. +1 a +2
  ninguém mais noticiou (fonte não reconhecida) +1
  confirmada por veículo reconhecido ..... −1
  assunto parecido com checagem recente .. +3
Nível: 3 ou mais = 🔴 alto risco · 2 = 🟡 atenção · até 1 = sem alerta.
"""
from __future__ import annotations

import re

from .coletor import Noticia, chave

STOP = set("""
a o as os um uma uns umas de da do das dos em na no nas nos por para pra com sem
sob sobre entre ate e ou que se ao aos mas mais menos muito ja nao sim seu sua
seus suas ele ela eles elas isso esta este essa esse foi ser sao era tem ter
diz dizem apos como quando onde porque pelo pela pelos pelas qual quem tambem
sera vai vao the and for
""".split())

# palavras do veredito das checagens, que não fazem parte do assunto
VEREDITO = set("""
falso falsa enganoso enganosa fake verdadeiro verdade boato checagem checamos
verificamos verifica comprova montagem video foto post posts publicacao
publicacoes circula circulam viral redes sociais mensagem mensagens
contexto distorce distorcido inventado inventada
""".split())

PADRAO_CHECAGEM = re.compile(
    r"^(e falso|e enganoso|e fake|e boato|e verdade|verificamos|checamos|fato ou fake)"
    r"|\be fake\b|\bfato ou fake\b|\bboato\b|\bchecagem\b|\bverificamos\b|\bcomprova\b"
)


def _tokens(titulo: str, sem_veredito: bool = False) -> set[str]:
    t = {w for w in chave(titulo).split() if len(w) >= 3 and w not in STOP}
    return t - VEREDITO if sem_veredito else t


def _parecido(a: set, b: set, minimo: int = 3, proporcao: float = 0.5) -> bool:
    if not a or not b:
        return False
    comum = len(a & b)
    return comum >= minimo and comum / min(len(a), len(b)) >= proporcao


def _na_lista(n: Noticia, lista: list[str]) -> bool:
    d = (n.dominio or "").lower()
    nome = chave(n.fonte)
    for item in lista:
        item = item.lower().strip()
        if not item:
            continue
        if "." in item:  # domínio
            if d == item or d.endswith("." + item):
                return True
        elif chave(item) == nome:  # nome do veículo
            return True
    return False


def eh_checagem(n: Noticia, cfg: dict) -> bool:
    return _na_lista(n, cfg.get("agencias_checagem", [])) or bool(PADRAO_CHECAGEM.search(chave(n.titulo)))


def _sensacionalismo(titulo: str, termos: list[str]) -> list[str]:
    sinais = []
    t = f" {chave(titulo)} "
    achados = [x for x in termos if f" {chave(x)} " in t]
    if achados:
        sinais.append(f"termos apelativos ({', '.join(achados[:3])})")
    letras = [c for c in titulo if c.isalpha()]
    if len(letras) > 20 and sum(c.isupper() for c in letras) / len(letras) > 0.6:
        sinais.append("título quase todo em maiúsculas")
    if re.search(r"[!?]{2,}", titulo):
        sinais.append("pontuação exagerada")
    return sinais


def avaliar(resultado: list[dict], todas: list[Noticia], checagens: list[Noticia], cfg: dict) -> int:
    """Marca as notícias de `resultado` com nível e motivos. Retorna quantas têm alerta."""
    confiaveis = cfg.get("fontes_confiaveis", []) + cfg.get("agencias_checagem", [])
    suspeitas = cfg.get("fontes_suspeitas", [])
    termos = cfg.get("termos_sensacionalistas", [])
    base = [(m, _tokens(m.titulo)) for m in todas]
    checks = [(c, _tokens(c.titulo, True)) for c in checagens if eh_checagem(c, cfg)]
    alertas = 0

    for topico in resultado:
        for n in topico["noticias"]:
            if eh_checagem(n, cfg):
                n.nivel, n.motivos = "checagem", ["conteúdo de agência de checagem"]
                continue
            risco, motivos = 0, []
            conf = _na_lista(n, confiaveis)
            susp = _na_lista(n, suspeitas)
            if susp:
                risco += 3
                motivos.append("fonte na lista de sites suspeitos")
            elif conf:
                risco -= 1
            else:
                risco += 1
                motivos.append("fonte não reconhecida")

            sens = _sensacionalismo(n.titulo, termos)
            if sens:
                risco += min(2, len(sens))
                motivos += sens

            tk = _tokens(n.titulo)
            outras = [m for m, mt in base
                      if m is not n and chave(m.fonte) != chave(n.fonte) and _parecido(tk, mt)]
            if not conf:
                if not outras:
                    risco += 1
                    motivos.append("nenhum outro veículo noticiou")
                elif not susp and any(_na_lista(m, confiaveis) for m in outras):
                    risco -= 1

            tk_sem = _tokens(n.titulo, True)
            for c, ct in checks:
                if _parecido(tk_sem, ct, minimo=3, proporcao=0.6):
                    risco += 3
                    motivos.append(f"assunto parecido já foi checado por {c.fonte}")
                    n.checagem = c.link
                    break

            n.motivos = motivos
            n.nivel = "alto" if risco >= 3 else "atencao" if risco == 2 else ""
            alertas += n.nivel in ("alto", "atencao")
    return alertas
