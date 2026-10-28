"""Ponto de entrada:  python -m noticias_bot [opções]

Exemplos:
  python -m noticias_bot                      # janela automática, envia o que faltar
  python -m noticias_bot --simular            # não envia; grava prévias em saida/
  python -m noticias_bot --data 2026-10-28 --edicao 20h --forcar
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

from . import credibilidade, envio, formatador
from .coletor import coletar, coletar_checagens
from .janela import janela_atual, janela_especifica, obter_fuso

RAIZ = Path(__file__).resolve().parent.parent
log = logging.getLogger("noticias_bot")


def carregar_env(caminho: Path) -> dict:
    """Lê .env (se existir) sem sobrescrever variáveis já definidas."""
    if caminho.exists():
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha and not linha.startswith("#") and "=" in linha:
                k, v = linha.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return dict(os.environ)


class Estado:
    """Registra quais janelas já foram enviadas em cada canal (evita duplicar)."""

    def __init__(self, caminho: Path):
        self.caminho = caminho
        self.dados = {"enviados": {}}
        if caminho.exists():
            self.dados = json.loads(caminho.read_text(encoding="utf-8") or '{"enviados": {}}')

    def enviado(self, janela_id: str, canal: str) -> bool:
        return canal in self.dados["enviados"].get(janela_id, {})

    def marcar(self, janela_id: str, canal: str) -> None:
        self.dados["enviados"].setdefault(janela_id, {})[canal] = datetime.now().isoformat(timespec="seconds")
        ultimas = sorted(self.dados["enviados"])[-60:]  # guarda ~30 dias
        self.dados["enviados"] = {k: self.dados["enviados"][k] for k in ultimas}
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.caminho.write_text(json.dumps(self.dados, indent=2, ensure_ascii=False), encoding="utf-8")


def avisar(nivel: str, mensagem: str) -> None:
    """Loga e, no GitHub Actions, cria uma anotação visível na página da execução."""
    {"notice": log.info, "warning": log.warning}.get(nivel, log.error)(mensagem)
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::{nivel}::{mensagem.replace(chr(10), ' ')}", flush=True)


def ler_data(texto: str | None) -> date | None:
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime((texto or "").strip(), formato).date()
        except ValueError:
            pass
    return None


def ler_edicao(texto: str | None) -> str | None:
    t = (texto or "").strip().lower().replace("ã", "a")
    if t in ("08h", "8h", "08", "8", "08:00", "8:00", "manha"):
        return "08h"
    if t in ("20h", "20", "20:00", "noite"):
        return "20h"
    return None


def principal(argv=None, baixar_fn=None, enviar_email_fn=None, enviar_whatsapp_fn=None) -> int:
    ap = argparse.ArgumentParser(prog="noticias_bot")
    ap.add_argument("--data", help="dia da edição (AAAA-MM-DD ou DD/MM/AAAA); padrão: automático")
    ap.add_argument("--edicao", help="08h (manhã) ou 20h (noite); padrão: automático")
    ap.add_argument("--forcar", action="store_true", help="envia mesmo se já enviado")
    ap.add_argument("--simular", action="store_true", help="não envia; grava prévias em saida/")
    ap.add_argument("--canais", help="ex.: email,whatsapp (padrão: variável CANAIS)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    env = carregar_env(RAIZ / ".env")
    cfg = json.loads((RAIZ / "topicos.json").read_text(encoding="utf-8"))
    tz = obter_fuso(env.get("FUSO"))

    janela = None
    if args.data or args.edicao:
        dia, edicao = ler_data(args.data), ler_edicao(args.edicao)
        if dia and edicao:
            janela = janela_especifica(dia, edicao, tz)
        else:
            avisar("warning", f"Data/edição inválidas ({args.data!r}, {args.edicao!r}); "
                              "usando a edição automática. Use AAAA-MM-DD e 08h ou 20h.")
    janela = janela or janela_atual(tz=tz)
    log.info("Janela %s: %s", janela.id, janela.descricao)

    canais = [c.strip() for c in (args.canais or (env.get("CANAIS") or "email")).split(",") if c.strip()]
    estado = Estado(Path((env.get("ARQUIVO_ESTADO") or RAIZ / "data" / "estado.json")))
    pendentes = [c for c in canais if args.forcar or args.simular or not estado.enviado(janela.id, c)]
    if not pendentes:
        log.info("Janela %s já enviada em todos os canais. Nada a fazer.", janela.id)
        return 0

    kwargs = {"baixar_fn": baixar_fn} if baixar_fn else {}
    todas: list = []
    resultado, erros = coletar(cfg["topicos"], janela, todas=todas, **kwargs)

    arq_cred = RAIZ / "credibilidade.json"
    if arq_cred.exists() and (env.get("ALERTA_FAKE_NEWS") or "true").lower() not in ("0", "false", "nao", "não"):
        try:
            cred = json.loads(arq_cred.read_text(encoding="utf-8"))
            checagens, erros_chk = coletar_checagens(cred.get("fontes_de_checagem", []), **kwargs)
            erros += erros_chk
            n_alertas = credibilidade.avaliar(resultado, todas, checagens, cred)
            alto, atencao = formatador.alertas(resultado)
            marcadas = [n for t in resultado for n in t["noticias"] if n.nivel in ("alto", "atencao")]
            for n in marcadas[:10]:
                avisar("notice", f"[{n.nivel}] {n.fonte} ({n.dominio}): {n.titulo[:90]} — {'; '.join(n.motivos)}")
            avisar("notice", f"{formatador.total(resultado)} notícias · alertas de fake news: "
                             f"{alto} alto risco, {atencao} atenção · {len(checagens)} checagens de referência")
        except Exception as e:  # a análise nunca pode impedir o envio
            avisar("warning", f"Análise de fake news falhou, enviando sem ela: {e}")
    log.info("Coletadas %s notícias (%s erro(s) de fonte)", formatador.total(resultado), len(erros))

    assunto = formatador.assunto(janela, resultado)
    html = formatador.html_email(janela, resultado, erros)
    texto_mail = formatador.texto_email(janela, resultado, erros)
    texto_wpp = formatador.texto_whatsapp(
        janela, resultado, int(cfg.get("max_por_topico_whatsapp", 6)),
        env.get("WHATSAPP_LINKS", "").lower() in ("1", "true", "sim"), erros)
    partes = formatador.dividir(texto_wpp, envio.limite_whatsapp(env))

    if args.simular:
        saida = RAIZ / "saida"
        saida.mkdir(exist_ok=True)
        (saida / f"{janela.id}_email.html").write_text(
            html.replace("cid:logo-ufiscal", "../assets/logo-ufiscal.png"), encoding="utf-8")
        (saida / f"{janela.id}_whatsapp.txt").write_text("\n\n-----\n\n".join(partes), encoding="utf-8")
        log.info("Simulação gravada em %s (%s parte(s) de WhatsApp)", saida, len(partes))
        return 0

    enviar_email_fn = enviar_email_fn or envio.enviar_email
    enviar_whatsapp_fn = enviar_whatsapp_fn or envio.enviar_whatsapp
    falhas = {}
    for canal in pendentes:
        try:
            if canal == "email":
                enviar_email_fn(env, assunto, texto_mail, html)
            elif canal == "whatsapp":
                enviar_whatsapp_fn(env, partes)
            else:
                raise RuntimeError(f"Canal desconhecido: {canal}")
            estado.marcar(janela.id, canal)
        except Exception as e:
            log.exception("Falha no canal %s", canal)
            falhas[canal] = str(e)
            avisar("error", f"Falha no envio por {canal}: {e}")

    if falhas:  # avisa pelo canal que funcionou, e sai com erro (o agendador tenta de novo)
        alerta = f"⚠️ Notícias uFiscal: falha ao enviar {janela.id} por {', '.join(falhas)}: " + \
                 "; ".join(f"{c}: {m[:200]}" for c, m in falhas.items())
        for canal in [c for c in canais if c not in falhas]:
            try:
                if canal == "email":
                    # alerta de falha vai só para o administrador, não para a lista
                    admin = envio.lista_emails(env.get("EMAIL_ADMIN") or env.get("SMTP_USUARIO"))
                    enviar_email_fn(env, alerta[:150], alerta, f"<p>{alerta}</p>", admin or None)
                else:
                    enviar_whatsapp_fn(env, [alerta])
            except Exception:
                log.exception("Também falhou o alerta por %s", canal)
        return 1
    return 0


def executar() -> int:
    try:
        return principal()
    except SystemExit:
        raise
    except Exception as e:
        log.exception("Erro inesperado")
        avisar("error", f"Erro inesperado: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(executar())
