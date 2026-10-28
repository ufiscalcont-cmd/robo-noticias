import json
import tempfile
import unittest
from datetime import date, datetime, time
from pathlib import Path
from unittest import mock

from noticias_bot import __main__ as app
from noticias_bot import formatador
from noticias_bot.coletor import coletar, parse_feed, url_da_fonte
from noticias_bot.janela import janela_atual, janela_especifica, obter_fuso

TZ = obter_fuso("America/Sao_Paulo")


def em(d, h, m=0):
    return datetime.combine(d, time(h, m), TZ)


HOJE = date(2026, 10, 28)
ONTEM = date(2026, 10, 27)


def item(titulo, fonte, dt_utc):
    return (f"<item><title>{titulo} - {fonte}</title><link>https://ex.com/{abs(hash(titulo))}</link>"
            f"<pubDate>{dt_utc}</pubDate><source url='https://x'>{fonte}</source></item>")


FEED = ("<rss><channel><title>Google News</title>"
        # 28/10 12:00 BRT = 15:00 UTC (dentro da janela 08–20)
        + item("Receita abre consulta ao lote do IR", "G1", "Wed, 28 Oct 2026 15:00:00 GMT")
        # 28/10 19:59 BRT = 22:59 UTC (dentro)
        + item("Câmara aprova regulamentação do IBS", "Folha", "Wed, 28 Oct 2026 22:59:00 GMT")
        # 28/10 20:00 BRT = 23:00 UTC (fora: fim é exclusivo)
        + item("Notícia das vinte em ponto", "UOL", "Wed, 28 Oct 2026 23:00:00 GMT")
        # 28/10 07:59 BRT (fora)
        + item("Notícia da madrugada", "CNN", "Wed, 28 Oct 2026 10:59:00 GMT")
        # duplicata da primeira, outra fonte e acentuação diferente
        + item("Receita abre consulta ao lote do IR!", "Estadão", "Wed, 28 Oct 2026 14:00:00 GMT")
        + "</channel></rss>").encode()


class TestJanela(unittest.TestCase):
    def test_noite(self):
        j = janela_atual(em(HOJE, 20, 2), TZ)
        self.assertEqual((j.inicio, j.fim), (em(HOJE, 8), em(HOJE, 20)))
        self.assertEqual(j.id, "2026-10-28_20h")

    def test_noite_com_atraso(self):
        self.assertEqual(janela_atual(em(HOJE, 23, 50), TZ).fim, em(HOJE, 20))

    def test_manha(self):
        j = janela_atual(em(HOJE, 8, 0), TZ)
        self.assertEqual((j.inicio, j.fim), (em(ONTEM, 20), em(HOJE, 8)))
        self.assertEqual(j.edicao, "Edição da manhã")

    def test_madrugada_pega_janela_anterior(self):
        self.assertEqual(janela_atual(em(HOJE, 3), TZ).fim, em(ONTEM, 20))

    def test_especifica(self):
        self.assertEqual(janela_especifica(HOJE, "08h", TZ).inicio, em(ONTEM, 20))


class TestColeta(unittest.TestCase):
    def test_parse_remove_fonte_do_titulo(self):
        n = parse_feed(FEED)[0]
        self.assertEqual((n.titulo, n.fonte), ("Receita abre consulta ao lote do IR", "G1"))

    def test_filtra_janela_e_deduplica(self):
        j = janela_especifica(HOJE, "20h", TZ)
        topicos = [{"nome": "A", "fontes": [{"tipo": "rss", "url": "u1"}]},
                   {"nome": "B", "fontes": [{"tipo": "rss", "url": "u2"}]}]
        res, erros = coletar(topicos, j, agora=em(HOJE, 20, 5), baixar_fn=lambda u: FEED)
        titulos = [n.titulo for n in res[0]["noticias"]]
        self.assertEqual(titulos, ["Câmara aprova regulamentação do IBS",
                                   "Receita abre consulta ao lote do IR"])
        self.assertEqual(res[1]["noticias"], [])  # tudo já apareceu no tópico A
        self.assertEqual(erros, [])

    def test_fonte_com_erro_nao_derruba(self):
        def falha(u):
            raise OSError("sem rede")
        j = janela_especifica(HOJE, "20h", TZ)
        res, erros = coletar([{"nome": "A", "fontes": [{"tipo": "rss", "url": "u"}]}], j,
                             agora=em(HOJE, 20, 5), baixar_fn=falha)
        self.assertEqual(len(erros), 1)
        self.assertEqual(res[0]["noticias"], [])

    def test_url_google(self):
        u = url_da_fonte({"tipo": "google_busca", "q": "Simples Nacional"})
        self.assertIn("search?q=Simples+Nacional+when%3A1d", u)
        self.assertIn("ceid=BR:pt-419", u)


class TestFormatacao(unittest.TestCase):
    def setUp(self):
        self.j = janela_especifica(HOJE, "20h", TZ)
        self.res, _ = coletar([{"nome": "Tributos", "emoji": "🧾", "fontes": [{"tipo": "rss", "url": "u"}]}],
                              self.j, agora=em(HOJE, 20, 5), baixar_fn=lambda u: FEED)

    def test_whatsapp(self):
        t = formatador.texto_whatsapp(self.j, self.res)
        self.assertIn("*TRIBUTOS* (2)", t); self.assertIn("NOTÍCIAS uFISCAL", t)
        self.assertIn("(19:59)", t)  # horário convertido para Brasília

    def test_dividir_respeita_limite(self):
        grande = "\n\n".join(f"*T{i}*\n" + "\n".join("• linha " * 10 for _ in range(8)) for i in range(20))
        partes = formatador.dividir(grande, 1500)
        self.assertGreater(len(partes), 1)
        self.assertTrue(all(len(p) <= 1500 + 12 for p in partes))
        self.assertTrue(partes[0].startswith("(1/"))

    def test_html_escapa(self):
        self.assertIn("<a href=", formatador.html_email(self.j, self.res))


class TestFluxoCompleto(unittest.TestCase):
    def test_envia_uma_vez_e_reenvia_so_canal_que_falhou(self):
        with tempfile.TemporaryDirectory() as tmp:
            estado = Path(tmp) / "estado.json"
            env = {"ARQUIVO_ESTADO": str(estado), "CANAIS": "email,whatsapp"}
            emails, wpps = [], []
            wpp_quebrado = {"sim": True}

            def wpp(env_, partes):
                if wpp_quebrado["sim"]:
                    raise RuntimeError("API fora do ar")
                wpps.append(partes)

            def rodar():
                with mock.patch.dict("os.environ", env), \
                     mock.patch.object(app, "janela_atual", lambda tz=None: janela_especifica(HOJE, "20h", TZ)), \
                     mock.patch("noticias_bot.envio.time.sleep"):
                    return app.principal([], baixar_fn=lambda u: FEED,
                                         enviar_email_fn=lambda *a, **k: emails.append(a),
                                         enviar_whatsapp_fn=wpp)

            self.assertEqual(rodar(), 1)            # WhatsApp falhou
            self.assertEqual(len(emails), 2)        # resumo + alerta de falha
            wpp_quebrado["sim"] = False
            self.assertEqual(rodar(), 0)            # reserva: só o WhatsApp
            self.assertEqual((len(emails), len(wpps)), (2, 1))
            self.assertEqual(rodar(), 0)            # nada mais a fazer
            self.assertEqual((len(emails), len(wpps)), (2, 1))
            dados = json.loads(estado.read_text())
            self.assertEqual(set(dados["enviados"]["2026-10-28_20h"]), {"email", "whatsapp"})


if __name__ == "__main__":
    unittest.main()


class TestEmailOculto(unittest.TestCase):
    def test_destinatarios_ficam_ocultos(self):
        from noticias_bot import envio
        enviadas = []

        class FakeSMTP:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def login(self, *a): pass
            def send_message(self, msg):
                enviadas.append(msg)

        env = {"SMTP_USUARIO": "robo@gmail.com", "SMTP_SENHA": "x",
               "EMAIL_DESTINO": "a@x.com; b@y.com,\nc@z.com, a@x.com"}
        with mock.patch("smtplib.SMTP_SSL", FakeSMTP):
            envio.enviar_email(env, "Assunto", "texto", "<p>html</p>")
        msg = enviadas[0]
        self.assertEqual(msg["Bcc"], "a@x.com, b@y.com, c@z.com")
        self.assertNotIn("a@x.com", msg["To"])
        self.assertIn("Notícias uFiscal", msg["From"])
