import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from noticias_bot import formatador
from noticias_bot.coletor import Noticia
from noticias_bot.historico import Historico
from noticias_bot.janela import janela_especifica, obter_fuso

DT = datetime(2026, 10, 28, 15, tzinfo=timezone.utc)


def n(titulo, link=None):
    return Noticia(titulo, link or f"https://x/{abs(hash(titulo))}", "g1", DT, "g1.globo.com")


def res(*noticias):
    return [{"nome": "T", "emoji": "", "noticias": list(noticias)}]


class TestHistorico(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = Historico(Path(self.tmp.name) / "historico.json")
        self.h.registrar(res(
            n("Câmara aprova texto-base da regulamentação da reforma tributária", "https://a/1"),
            n("Dólar fecha a R$ 5,20 com tensão no exterior"),
            n("Governo da Bahia anuncia obras em rodovias do sertão"),
        ), "2026-10-28_08h", agora=datetime(2026, 10, 28, 8))
        self.h.salvar()
        self.h = Historico(Path(self.tmp.name) / "historico.json")  # relê do disco

    def tearDown(self):
        self.tmp.cleanup()

    def filtrar(self, *noticias, edicao="2026-10-28_20h"):
        r = res(*noticias)
        contagem = self.h.filtrar(r, edicao)
        return r[0]["noticias"], contagem

    def test_mesmo_link_nao_repete(self):
        ficam, (rem, _) = self.filtrar(n("Outro título qualquer", "https://a/1"))
        self.assertEqual((ficam, rem), ([], 1))

    def test_mesmo_assunto_sem_novidade_nao_repete(self):
        ficam, _ = self.filtrar(n("Câmara aprova texto-base de regulamentação da reforma tributária"))
        self.assertEqual(ficam, [])

    def test_mesmo_assunto_reescrito_por_outro_veiculo_nao_repete(self):
        ficam, _ = self.filtrar(n("Governo baiano anuncia obras em rodovias do sertão da Bahia"))
        self.assertEqual(ficam, [])

    def test_desdobramento_entra_marcado(self):
        a = n("Senado aprova regulamentação da reforma tributária; texto vai à sanção")
        b = n("Dólar fecha a R$ 5,35 após dados de emprego nos EUA")
        ficam, (rem, atu) = self.filtrar(a, b)
        self.assertEqual(len(ficam), 2)          # as duas são enviadas
        self.assertEqual(atu, 1)                 # a da reforma é desdobramento
        self.assertEqual(a.anterior, "edição da manhã de 28/10")
        self.assertEqual(b.anterior, "")         # cotação do dia com outro contexto: notícia nova

    def test_noticia_nova_passa_sem_marca(self):
        a = n("STF julga recurso sobre ICMS na base do PIS e da Cofins")
        ficam, _ = self.filtrar(a)
        self.assertEqual((ficam, a.anterior), ([a], ""))

    def test_reenvio_forcado_da_mesma_edicao_sai_completo(self):
        a = n("Câmara aprova texto-base da regulamentação da reforma tributária", "https://a/1")
        ficam, _ = self.filtrar(a, edicao="2026-10-28_08h")
        self.assertEqual(ficam, [a])

    def test_memoria_expira_em_15_dias(self):
        self.h.registrar(res(), "2026-11-20_08h", agora=datetime(2026, 11, 20, 8))
        self.assertEqual(self.h.itens, [])

    def test_selo_de_atualizacao(self):
        a = n("Senado aprova regulamentação da reforma tributária; texto vai à sanção")
        r = res(a)
        self.h.filtrar(r, "2026-10-28_20h")
        j = janela_especifica(date(2026, 10, 28), "20h", obter_fuso())
        self.assertIn("ATUALIZAÇÃO", formatador.html_email(j, r))
        self.assertIn("🔄", formatador.texto_whatsapp(j, r))


if __name__ == "__main__":
    unittest.main()
