import json
import unittest
from datetime import date, datetime, timezone
from unittest import mock

from noticias_bot import formatador, resumo
from noticias_bot.coletor import Noticia
from noticias_bot.janela import janela_especifica, obter_fuso

J = janela_especifica(date(2026, 10, 28), "20h", obter_fuso())


def n(t, f, d, h=15):
    return Noticia(t, "https://news.google.com/x", f, datetime(2026, 10, 28, h, tzinfo=timezone.utc), d)


RES = [
    {"nome": "Tributos e Contabilidade", "emoji": "", "noticias": [n("Receita prorroga prazo do Simples", "Folha de S.Paulo", "folha.uol.com.br")]},
    {"nome": "Bahia e Sergipe", "emoji": "", "noticias": [n("Governo da Bahia anuncia obra", "A Tarde", "atarde.com.br")]},
    {"nome": "Economia", "emoji": "", "noticias": [n("Copom mantém a Selic", "g1", "g1.globo.com")]},
]


class TestResumo(unittest.TestCase):
    def test_sem_ia_gramatica(self):
        r = resumo.gerar({}, J, RES)
        texto = " ".join(r["paragrafos"])
        self.assertIn("três notícias", texto)
        self.assertIn("entre as 8h e as 20h de 28 de outubro", texto)
        self.assertNotIn("de o ", texto)
        self.assertNotIn("a A Tarde", texto)
        self.assertEqual(r["origem"], "automático (sem IA)")

    def test_veiculo(self):
        self.assertEqual(resumo._veiculo("Folha de S.Paulo", "de"), "da Folha de S.Paulo")
        self.assertEqual(resumo._veiculo("g1", "de"), "do g1")
        self.assertEqual(resumo._veiculo("A Tarde"), "o jornal A Tarde")

    def test_referencia_abnt(self):
        ref = resumo.referencia_abnt(RES[2]["noticias"][0], datetime(2026, 10, 28, 20), obter_fuso())
        self.assertEqual(ref, "COPOM mantém a Selic. **g1**, [S. l.], 28 out. 2026. "
                              "Disponível em: https://news.google.com/x. Acesso em: 28 out. 2026.")

    def test_com_ia(self):
        resposta = json.dumps({"titulo": "Um dia de decisões", "paragrafos": ["Parágrafo um.", "Parágrafo dois."],
                               "citadas": [1, 3, 99]})
        with mock.patch.object(resumo, "_chamar_api", return_value=f"```json\n{resposta}\n```"):
            r = resumo.gerar({"GITHUB_TOKEN": "x"}, J, RES)
        self.assertEqual(r["titulo"], "Um dia de decisões")
        self.assertEqual(len(r["referencias"]), 2)  # id 99 inexistente é descartado
        self.assertTrue(r["origem"].startswith("IA"))

    def test_ia_falha_usa_sem_ia(self):
        with mock.patch.object(resumo, "_chamar_api", side_effect=OSError("429")), \
             mock.patch.object(resumo.time, "sleep"):
            r = resumo.gerar({"GITHUB_TOKEN": "x"}, J, RES)
        self.assertEqual(r["origem"], "automático (sem IA)")

    def test_fake_news_fica_fora_do_resumo(self):
        suspeita = n("URGENTE bomba", "Blog", "blog.xyz")
        suspeita.nivel = "alto"
        res = [dict(RES[0], noticias=[suspeita] + RES[0]["noticias"])] + RES[1:]
        r = resumo.gerar({}, J, res)
        self.assertNotIn("URGENTE", " ".join(r["paragrafos"]))

    def test_aparece_no_email_e_whatsapp(self):
        r = resumo.gerar({}, J, RES)
        html = formatador.html_email(J, RES, resumo=r)
        self.assertIn("Panorama da edição", html)
        self.assertIn("REFERÊNCIAS", html)
        self.assertIn("<b>g1</b>", html)
        self.assertIn(r["titulo"].upper(), formatador.texto_whatsapp(J, RES, resumo=r))


if __name__ == "__main__":
    unittest.main()
