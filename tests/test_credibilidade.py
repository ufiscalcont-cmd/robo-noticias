import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from noticias_bot import formatador
from noticias_bot.coletor import Noticia, parse_feed
from noticias_bot.credibilidade import avaliar
from noticias_bot.janela import janela_especifica, obter_fuso
from datetime import date

CFG = json.loads((Path(__file__).resolve().parent.parent / "credibilidade.json").read_text(encoding="utf-8"))
DT = datetime(2026, 10, 28, 15, tzinfo=timezone.utc)


def n(titulo, fonte, dominio):
    return Noticia(titulo, f"https://{dominio}/x", fonte, DT, dominio)


class TestCredibilidade(unittest.TestCase):
    def rodar(self, noticias, extras=(), checagens=(), cfg=CFG):
        resultado = [{"nome": "T", "emoji": "", "noticias": list(noticias)}]
        qtd = avaliar(resultado, list(noticias) + list(extras), list(checagens), cfg)
        return qtd, resultado

    def test_fonte_confiavel_sem_alerta(self):
        a = n("Senado aprova regulamentação da reforma tributária", "g1", "g1.globo.com")
        qtd, _ = self.rodar([a])
        self.assertEqual((qtd, a.nivel), (0, ""))

    def test_desconhecida_sensacionalista_alto_risco(self):
        a = n("URGENTE!! Governo vai confiscar poupança, compartilhe antes que apaguem",
              "Blog da Verdade", "blogdaverdade.xyz")
        self.rodar([a])
        self.assertEqual(a.nivel, "alto")
        self.assertTrue(any("apelativos" in m for m in a.motivos))

    def test_desconhecida_isolada_pede_atencao(self):
        a = n("Prefeitura anuncia nova feira de artesanato no centro", "Portal X", "portalx.com.br")
        self.rodar([a])
        self.assertEqual(a.nivel, "atencao")
        self.assertIn("nenhum outro veículo noticiou", a.motivos)

    def test_desconhecida_confirmada_por_confiavel_sem_alerta(self):
        a = n("Prefeitura anuncia nova feira de artesanato no centro", "Portal X", "portalx.com.br")
        b = n("Prefeitura anuncia feira de artesanato no centro da cidade", "g1", "g1.globo.com")
        self.rodar([a], extras=[b])
        self.assertEqual(a.nivel, "")

    def test_bate_com_checagem(self):
        a = n("Governo vai taxar transferências via Pix a partir de janeiro", "Portal Y", "portaly.net")
        chk = n("É falso que governo vai taxar transferências via Pix em janeiro", "Aos Fatos", "aosfatos.org")
        self.rodar([a], checagens=[chk])
        self.assertEqual(a.nivel, "alto")
        self.assertEqual(a.checagem, "https://aosfatos.org/x")

    def test_noticia_de_checagem_recebe_selo(self):
        a = n("É falso que vacina altera DNA", "Agência Lupa", "lupa.uol.com.br")
        self.rodar([a])
        self.assertEqual(a.nivel, "checagem")

    def test_lista_de_suspeitas(self):
        cfg = dict(CFG, fontes_suspeitas=["sitesuspeito.com"])
        a = n("Ministro faz anúncio sobre impostos", "Site", "sitesuspeito.com")
        b = n("Ministro faz anúncio sobre impostos hoje", "g1", "g1.globo.com")
        self.rodar([a], extras=[b], cfg=cfg)
        self.assertEqual(a.nivel, "alto")

    def test_dominio_lido_do_google_news(self):
        xml = (b"<rss><channel><item><title>T - g1</title><link>https://news.google.com/rss/x</link>"
               b"<pubDate>Wed, 28 Oct 2026 15:00:00 GMT</pubDate>"
               b"<source url='https://g1.globo.com'>g1</source></item></channel></rss>")
        self.assertEqual(parse_feed(xml)[0].dominio, "g1.globo.com")

    def test_formatacao_mostra_alerta(self):
        a = n("URGENTE!! compartilhe essa bomba", "Blog", "blog.xyz")
        _, res = self.rodar([a])
        j = janela_especifica(date(2026, 10, 28), "20h", obter_fuso())
        wpp = formatador.texto_whatsapp(j, res)
        self.assertIn("🔴", wpp)
        self.assertIn("POSSÍVEL FAKE NEWS", wpp)
        self.assertIn("POSSÍVEL FAKE NEWS", formatador.html_email(j, res))


if __name__ == "__main__":
    unittest.main()
