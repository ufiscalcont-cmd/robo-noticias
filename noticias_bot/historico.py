"""Memória das notícias já enviadas, para não repetir nas próximas edições.

Regras, para cada notícia nova comparada com o que saiu nos últimos 15 dias:
  * mesmo link ou mesmo título .................................. não envia
  * mesmo assunto (títulos muito parecidos) sem fato novo ........ não envia
  * mesmo assunto COM fato novo (desdobramento) .................. envia, marcada
    como 🔄 ATUALIZAÇÃO, com a edição em que o assunto saiu antes

"Fato novo" = o título traz palavras que indicam desdobramento (aprova, adia,
sanciona, prende, morre, recua…), números novos, ou vários termos inéditos.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from .coletor import chave
from .credibilidade import _tokens

DIAS_MEMORIA = 15

DESDOBRAMENTO = set("""
aprova aprovado aprovada aprovam rejeita rejeitado rejeitada veta vetado vetada derruba derrubado
sanciona sancionado sancionada promulga publica publicado publicada regulamenta regulamentado
adia adiado adiada suspende suspenso suspensa cancela cancelado cancelada prorroga prorrogado
prorrogada recua revoga revogado retoma volta voltam confirma confirmado confirmada desmente
decide decidiu decisao julga julgamento condena condenado condenada absolve absolvido
prende preso presa presos prisao solto solta libera liberado liberada indicia indiciado denuncia
morre morte mortos morreu feridos resgata resgatado encontrado encontrada
renuncia demite demitido exonera exonerado nomeia nomeado eleito eleita vence perde empata
sobe sobem cai caem dispara despenca recorde amplia reduz eleva corta
encerra termina conclui inicia comeca entra vigor efeito acordo fecha fechado
sancao votacao aprovacao vota votam plenario senado camara stf stj tst tse tcu cnj
lei decreto portaria medida provisoria oficializa oficial diario turno resultado final
reacao responde rebate investiga investigacao operacao balanco atualiza atualizacao
""".split())


def _rotulo(janela_id: str) -> str:
    """'2026-10-27_20h' -> 'edição da noite de 27/10'."""
    try:
        dia, hora = janela_id.split("_")
        d = datetime.strptime(dia, "%Y-%m-%d")
        return f"edição da {'manhã' if hora == '08h' else 'noite'} de {d:%d/%m}"
    except ValueError:
        return "edição anterior"


def _numeros(tk: set) -> set:
    return {t for t in tk if any(c.isdigit() for c in t)}


def classificar(tk: set, k: str, link: str, anteriores: list[dict]) -> tuple[str, dict | None]:
    """Retorna ('nova' | 'repetida' | 'desdobramento', item anterior mais parecido)."""
    melhor, melhor_sim = None, 0.0
    for a in anteriores:
        if (link and link == a["l"]) or k == a["k"]:
            return "repetida", a
        atk = set(a["tk"])
        comum = len(tk & atk)
        if comum < 3:
            continue
        sim = comum / max(1, min(len(tk), len(atk)))
        if sim >= 0.5 and sim > melhor_sim:
            melhor, melhor_sim = a, sim
    if not melhor:
        return "nova", None
    novos = tk - set(melhor["tk"])
    fato_novo = (novos & DESDOBRAMENTO) or _numeros(novos) or len(novos) >= 3
    if fato_novo and len(novos) >= 2:
        return "desdobramento", melhor
    return "repetida", melhor


class Historico:
    def __init__(self, caminho: Path):
        self.caminho = Path(caminho)
        self.itens: list[dict] = []
        if self.caminho.exists():
            try:
                self.itens = json.loads(self.caminho.read_text(encoding="utf-8")).get("itens", [])
            except (ValueError, AttributeError):
                self.itens = []

    def filtrar(self, resultado: list[dict], janela_id: str) -> tuple[int, int]:
        """Remove repetidas e marca desdobramentos. Retorna (removidas, atualizações).

        Itens da própria edição são ignorados na comparação, para que um reenvio
        forçado da mesma edição saia completo."""
        anteriores = [a for a in self.itens if a["e"] != janela_id]
        removidas = atualizacoes = 0
        for t in resultado:
            ficam = []
            for n in t["noticias"]:
                tipo, ant = classificar(_tokens(n.titulo), chave(n.titulo), n.link, anteriores)
                if tipo == "repetida":
                    removidas += 1
                    continue
                if tipo == "desdobramento":
                    n.anterior = _rotulo(ant["e"])
                    atualizacoes += 1
                ficam.append(n)
            t["noticias"] = ficam
        return removidas, atualizacoes

    def registrar(self, resultado: list[dict], janela_id: str, agora: datetime | None = None) -> None:
        agora = agora or datetime.now()
        self.itens = [a for a in self.itens if a["e"] != janela_id]
        for t in resultado:
            for n in t["noticias"]:
                self.itens.append({"e": janela_id, "k": chave(n.titulo), "l": n.link,
                                   "t": n.titulo, "tk": sorted(_tokens(n.titulo)),
                                   "d": agora.isoformat(timespec="seconds")})
        limite = (agora - timedelta(days=DIAS_MEMORIA)).isoformat()
        self.itens = [a for a in self.itens if a["d"] >= limite]

    def salvar(self) -> None:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.caminho.write_text(json.dumps({"itens": self.itens}, ensure_ascii=False, indent=0),
                                encoding="utf-8")
