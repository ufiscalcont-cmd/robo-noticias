"""Cálculo das janelas de coleta.

Duas edições por dia, no fuso de São Paulo:
  * Edição da manhã (envio 08:00) -> notícias de 20:00 do dia anterior até 08:00
  * Edição da noite (envio 20:00) -> notícias de 08:00 até 20:00 do mesmo dia
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo


def obter_fuso(nome: str | None = None) -> tzinfo:
    nome = nome or os.environ.get("FUSO", "America/Sao_Paulo")
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(nome)
    except Exception:
        # O Brasil não tem horário de verão desde 2019: UTC-3 fixo é seguro.
        return timezone(timedelta(hours=-3), "BRT")


@dataclass(frozen=True)
class Janela:
    inicio: datetime
    fim: datetime

    @property
    def id(self) -> str:
        return f"{self.fim:%Y-%m-%d}_{self.fim:%H}h"

    @property
    def edicao(self) -> str:
        return "Edição da manhã" if self.fim.hour == 8 else "Edição da noite"

    @property
    def descricao(self) -> str:
        if self.inicio.date() == self.fim.date():
            return f"{self.fim:%d/%m/%Y} · {self.inicio:%H:%M} às {self.fim:%H:%M}"
        return f"{self.inicio:%d/%m %H:%M} até {self.fim:%d/%m/%Y %H:%M}"

    def contem(self, momento: datetime) -> bool:
        return self.inicio <= momento < self.fim


def janela_terminando_em(fim: datetime) -> Janela:
    tz = fim.tzinfo
    if fim.hour == 8:
        inicio = datetime.combine(fim.date() - timedelta(days=1), time(20), tz)
    elif fim.hour == 20:
        inicio = datetime.combine(fim.date(), time(8), tz)
    else:
        raise ValueError("A janela precisa terminar às 08:00 ou às 20:00")
    return Janela(inicio, fim)


def janela_atual(agora: datetime | None = None, tz: tzinfo | None = None) -> Janela:
    """Última janela já encerrada em relação a `agora`.

    Se a execução atrasar (ex.: roda às 20:40), continua pegando 08h–20h.
    """
    tz = tz or obter_fuso()
    agora = (agora or datetime.now(tz)).astimezone(tz)
    hoje = agora.date()
    oito = datetime.combine(hoje, time(8), tz)
    vinte = datetime.combine(hoje, time(20), tz)
    if agora >= vinte:
        fim = vinte
    elif agora >= oito:
        fim = oito
    else:  # madrugada: a última janela encerrada foi a das 20h de ontem
        fim = datetime.combine(hoje - timedelta(days=1), time(20), tz)
    return janela_terminando_em(fim)


def janela_especifica(dia: date, edicao: str, tz: tzinfo | None = None) -> Janela:
    tz = tz or obter_fuso()
    hora = {"08h": 8, "manha": 8, "20h": 20, "noite": 20}[edicao.lower()]
    return janela_terminando_em(datetime.combine(dia, time(hora), tz))
