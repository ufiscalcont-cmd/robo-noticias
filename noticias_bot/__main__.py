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

from . import credibilidade, envio, formatador, resumo as resumo_mod
from .coletor import coletar, coletar_checagens
from .historico import Historico
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


def carregar_perfil(perfil: str) -> dict:
    """Configuração do robô: topicos.json (padrão) ou perfis/<perfil>.json."""
    caminho = RAIZ / "perfis" / f"{perfil}.json" if perfil else RAIZ / "topicos.json"
    if not caminho.exists():
        raise SystemExit(f"Perfil não encontrado: {caminho.relative_to(RAIZ)}")
    return json.loads(caminho.read_text(encoding="utf-8"))


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
    perfil = (env.get("PERFIL") or "").strip()
    cfg = carregar_perfil(perfil)
    marca = cfg.get("marca") or "Notícias uFiscal"
    env.setdefault("NOME_REMETENTE", marca)
    formatador.configurar(marca=marca, rotulo=cfg.get("rotulo"), emoji=cfg.get("emoji"),
                          unidade=cfg.get("unidade"))
    if cfg.get("resumo_sistema"):
        resumo_mod.SISTEMA = cfg["resumo_sistema"]
    resumo_mod.ABERTURAS.update({t["nome"]: t["abertura"] for t in cfg["topicos"] if t.get("abertura")})
    pasta_dados = RAIZ / "data" / perfil if perfil else RAIZ / "data"
    log.info("Perfil: %s (%s tópicos)", perfil or "padrão", len(cfg["topicos"]))
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
    estado = Estado(Path((env.get("ARQUIVO_ESTADO") or pasta_dados / "estado.json")))
    pendentes = [c for c in canais if args.forcar or args.simular or not estado.enviado(janela.id, c)]
    if not pendentes:
        log.info("Janela %s já enviada em todos os canais. Nada a fazer.", janela.id)
        return 0

    kwargs = {"baixar_fn": baixar_fn} if baixar_fn else {}
    todas: list = []
    resultado, erros = coletar(cfg["topicos"], janela, todas=todas,
                               limite_por_topico=int(cfg.get("limite_por_topico", 40)), **kwargs)
    avisar("notice", "Por tópico: " + " · ".join(f"{t['nome']} {len(t['noticias'])}" for t in resultado))

    # não repete notícias de edições anteriores (só desdobramentos, marcados)
    historico = Historico(Path(env.get("ARQUIVO_HISTORICO") or pasta_dados / "historico.json"))
    removidas, atualizacoes = historico.filtrar(resultado, janela.id)
    avisar("notice", f"Histórico: {removidas} notícia(s) já enviadas foram retiradas; "
                     f"{atualizacoes} desdobramento(s) marcados como atualização")

    verificacao = None
    arq_cred = RAIZ / "credibilidade.json"
    if arq_cred.exists() and (env.get("ALERTA_FAKE_NEWS") or "true").lower() not in ("0", "false", "nao", "não"):
        try:
            cred = json.loads(arq_cred.read_text(encoding="utf-8"))
            checagens, erros_chk = coletar_checagens(cred.get("fontes_de_checagem", []), **kwargs)
            erros += erros_chk
            n_alertas = credibilidade.avaliar(resultado, todas, checagens, cred)
            verificacao = {"analisadas": formatador.total(resultado), "checagens": len(checagens)}
            alto, atencao = formatador.alertas(resultado)
            marcadas = [n for t in resultado for n in t["noticias"] if n.nivel in ("alto", "atencao")]
            for n in marcadas[:10]:
                avisar("notice", f"[{n.nivel}] {n.fonte} ({n.dominio}): {n.titulo[:90]} — {'; '.join(n.motivos)}")
            avisar("notice", f"{formatador.total(resultado)} notícias · alertas de fake news: "
                             f"{alto} alto risco, {atencao} atenção · {len(checagens)} checagens de referência")
        except Exception as e:  # a análise nunca pode impedir o envio
            avisar("warning", f"Análise de fake news falhou, enviando sem ela: {e}")
    log.info("Coletadas %s notícias (%s erro(s) de fonte)", formatador.total(resultado), len(erros))

    resumo = None
    try:
        resumo = resumo_mod.gerar(env, janela, resultado, todas)
        if resumo:
            avisar("notice", f"Resumo {resumo['origem']}: {sum(len(p.split()) for p in resumo['paragrafos'])} palavras, "
                             f"{len(resumo['referencias'])} referência(s)")
    except Exception as e:  # o resumo nunca pode impedir o envio
        avisar("warning", f"Resumo não gerado, enviando sem ele: {e}")

    assunto = formatador.assunto(janela, resultado)
    html = formatador.html_email(janela, resultado, erros, resumo=resumo, verificacao=verificacao)
    texto_mail = formatador.texto_email(janela, resultado, erros, resumo, verificacao)
    texto_wpp = formatador.texto_whatsapp(
        janela, resultado, int(cfg.get("max_por_topico_whatsapp", 6)),
        env.get("WHATSAPP_LINKS", "").lower() in ("1", "true", "sim"), erros, resumo, verificacao)
    partes = formatador.dividir(texto_wpp, envio.limite_whatsapp(env))

    if args.simular:
        saida = RAIZ / "saida" / perfil if perfil else RAIZ / "saida"
        saida.mkdir(exist_ok=True)
        (saida / f"{janela.id}_email.html").write_text(
            html.replace("cid:logo-ufiscal", ("../" if not perfil else "../../") + "assets/logo-ufiscal.png"), encoding="utf-8")
        (saida / f"{janela.id}_whatsapp.txt").write_text("\n\n-----\n\n".join(partes), encoding="utf-8")
        log.info("Simulação gravada em %s (%s parte(s) de WhatsApp)", saida, len(partes))
        return 0

    enviar_email_fn = enviar_email_fn or envio.enviar_email
    enviar_whatsapp_fn = enviar_whatsapp_fn or envio.enviar_whatsapp
    falhas = {}
    historico_salvo = False
    for canal in pendentes:
        try:
            if canal == "email":
                qtd = enviar_email_fn(env, assunto, texto_mail, html)
                if isinstance(qtd, int):
                    avisar("notice", f"E-mail entregue ao servidor para {qtd} destinatário(s), em cópia oculta")
            elif canal == "whatsapp":
                enviar_whatsapp_fn(env, partes)
            else:
                raise RuntimeError(f"Canal desconhecido: {canal}")
            estado.marcar(janela.id, canal)
            if not historico_salvo:  # registra o que os leitores receberam
                historico.registrar(resultado, janela.id)
                historico.salvar()
                historico_salvo = True
        except Exception as e:
            log.exception("Falha no canal %s", canal)
            falhas[canal] = str(e)
            avisar("error", f"Falha no envio por {canal}: {e}")

    if falhas:  # avisa pelo canal que funcionou, e sai com erro (o agendador tenta de novo)
        alerta = f"⚠️ {marca}: falha ao enviar {janela.id} por {', '.join(falhas)}: " + \
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
