"""Recuperação do PDF real, ambiguidades documentadas e integração da ferramenta."""

from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from pypdf import PdfWriter

from emporio.agent import ChatAgent
from emporio.catalog import Catalog
from emporio.policies import DEFAULT_MANUAL, NOTES, PolicyError, PolicyStore, TOPICS
from emporio.tools import CatalogTools
from emporio.import_data import import_catalog
from test_agent import FakeService, response


class PolicyRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.store = PolicyStore()

    def test_every_topic_has_sections_with_page_provenance(self):
        for topic in TOPICS:
            with self.subTest(topic=topic):
                result = self.store.lookup(topic)
                self.assertEqual(result["fonte"], {"arquivo": "politicas_da_loja.pdf", "versao": "2.1"})
                self.assertTrue(result["trechos"])
                for excerpt in result["trechos"]:
                    self.assertTrue(excerpt["texto"])
                    self.assertTrue(excerpt["titulo"])
                    self.assertTrue(all(1 <= page <= 8 for page in excerpt["paginas"]))

    def test_hours_preserve_weekday_saturday_and_holidays(self):
        excerpt = self.store.lookup("horarios")["trechos"][0]
        self.assertEqual(excerpt["paginas"], [2])
        self.assertIn("Segunda a Sexta-feira 09:00 às 18:00", excerpt["texto"])
        self.assertIn("Sábado 09:00 às 13:00", excerpt["texto"])
        self.assertIn("Domingo e Feriados Fechado", excerpt["texto"])

    def test_online_return_window_uses_receipt_and_keeps_conditions(self):
        result = self.store.lookup("trocas_devolucoes")
        excerpts = {section["secao"]: section for section in result["trechos"]}
        self.assertIn("7 (sete) dias corridos após o recebimento", excerpts["4.1"]["texto"])
        self.assertIn("embalagem original", excerpts["4.1"]["texto"])
        self.assertIn("10 dias úteis", excerpts["4.1"]["texto"])
        self.assertIn("4.4", excerpts)
        self.assertIn("90", excerpts["8.1"]["texto"])
        self.assertIn("pergunte", " ".join(result["orientacoes"]))

    def test_shipping_section_continues_across_pages_and_keeps_table(self):
        result = self.store.lookup("frete_entregas")
        section = next(excerpt for excerpt in result["trechos"] if excerpt["secao"] == "5.2")
        self.assertEqual(section["paginas"], [4, 5])
        for carrier in ("PAC", "SEDEX", "Jadlog"):
            self.assertIn(carrier, section["texto"])
        self.assertIn("5 a 12 dias úteis", section["texto"])

    def test_contacts_keep_conflicting_sources_instead_of_normalizing_them(self):
        result = self.store.lookup("contato")
        text = " ".join(excerpt["texto"] for excerpt in result["trechos"])
        for value in ("(67) 3341-4444", "(67) 3321-4500", "contato@emporiodamusica.com.br", "contato@empóriodamusica.com.br"):
            self.assertIn(value, text)
        self.assertIn("divergentes", " ".join(result["orientacoes"]))

    def test_ambiguities_and_limits_are_explicit(self):
        self.assertIn("EXATAMENTE R$ 500,00", " ".join(NOTES["frete_entregas"]))
        self.assertIn("não escolha frete grátis", " ".join(NOTES["frete_entregas"]))
        self.assertIn("não encerra", " ".join(NOTES["trocas_devolucoes"]))
        self.assertIn("faixas diferentes", " ".join(NOTES["pagamentos"]))

    def test_promotion_retrieval_includes_no_stacking_rule(self):
        text = " ".join(s["texto"] for s in self.store.lookup("promocoes")["trechos"])
        self.assertIn("promoções não são cumulativas", text)
        self.assertIn("não se aplica sobre", text)

    def test_retrieval_results_cannot_mutate_cached_source(self):
        first = self.store.lookup("horarios")
        first["trechos"][0]["texto"] = "Horário inventado"
        first["orientacoes"].clear()
        self.assertNotIn("inventado", self.store.lookup("horarios")["trechos"][0]["texto"])
        self.assertTrue(self.store.lookup("horarios")["orientacoes"])

    def test_replacing_manual_does_not_silently_reuse_old_cache(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "manual.pdf"
            shutil.copyfile(DEFAULT_MANUAL, path)
            store = PolicyStore(path)
            self.assertTrue(store.lookup("horarios")["trechos"])
            writer = PdfWriter()
            writer.add_blank_page(width=595, height=842)
            writer.write(path)
            with self.assertRaises(PolicyError):
                store.lookup("horarios")

    def test_missing_manual_and_unknown_topic_fail_explicitly(self):
        with TemporaryDirectory() as directory:
            missing = PolicyStore(Path(directory) / "missing.pdf")
            with self.assertRaises(PolicyError):
                missing.lookup("horarios")
            with self.assertRaises(ValueError):
                missing.lookup("topico_inexistente")


class PolicyAgentTests(unittest.TestCase):
    def test_accessory_request_uses_store_scope_from_manual(self):
        reply = ChatAgent(FakeService(response(
            "A loja trabalha com instrumentos musicais e não vende cabos avulsos.",
        ))).reply([{"role": "user", "content": "Vocês vendem cabos?"}])
        self.assertEqual(reply.consultations[0].arguments["topico"], "atendimento")
        self.assertTrue(any("cabos" in excerpt["texto"] for excerpt in reply.consultations[0].result["trechos"]))

    def test_tool_validates_topic_enum(self):
        tools = CatalogTools(Catalog())
        for arguments in ({}, {"topico": "qualquer"}, {"topico": 2}, {"topico": "horarios", "sql": "x"}):
            with self.subTest(arguments=arguments):
                self.assertEqual(tools.execute("consultar_politicas", arguments)["erro"], "argumentos_invalidos")

    def test_hours_answer_is_backed_by_pdf_section_and_current_trace(self):
        service = FakeService(
            response("De segunda a sexta, das 09:00 às 18:00. Sábado, das 09:00 às 13:00."),
        )
        reply = ChatAgent(service).reply([{"role": "user", "content": "Qual é o horário da loja?"}])
        trace = reply.consultations[0]
        self.assertEqual(trace.name, "consultar_politicas")
        self.assertEqual(trace.result["trechos"][0]["paginas"], [2])
        self.assertIn("18:00", reply.content)

    def test_policy_currency_values_are_supported_by_source_not_product_prices(self):
        service = FakeService(
            response("A taxa local é de R$ 35,00 para pedidos abaixo de R$ 500,00."),
        )
        reply = ChatAgent(service).reply([{"role": "user", "content": "Qual a taxa de frete local?"}])
        self.assertEqual(len(reply.consultations), 1)
        self.assertIn("R$ 35,00", reply.content)

    def test_missing_manual_returns_policy_failure_without_using_catalog(self):
        with TemporaryDirectory() as directory:
            service = FakeService(
                response("Não consegui consultar o horário da loja agora."),
            )
            reply = ChatAgent(service, policies=PolicyStore(Path(directory) / "missing.pdf")).reply(
                [{"role": "user", "content": "Qual o horário?"}]
            )
            self.assertEqual(reply.consultations[0].result["erro"], "politicas_indisponiveis")
            self.assertNotIn("09:00", reply.content)

    def test_hours_cannot_be_answered_before_policy_lookup(self):
        service = FakeService(
            response("De segunda a sexta, das 09:00 às 18:00."),
        )
        reply = ChatAgent(service).reply([{"role": "user", "content": "Qual o horário da loja?"}])
        self.assertEqual(len(reply.consultations), 1)
        self.assertEqual(reply.consultations[0].origin, "roteamento")
        self.assertTrue(any(message["role"] == "tool" for message in service.requests[0]))

    def test_policy_lookup_happens_before_additional_model_tools(self):
        service = FakeService(
            response(calls=[("listar_categorias", {})]),
            response("De segunda a sexta, das 09:00 às 18:00."),
        )
        with TemporaryDirectory() as directory:
            database = Path(directory) / "catalog.sqlite3"
            import_catalog(database=database)
            reply = ChatAgent(service, Catalog(database)).reply([{"role": "user", "content": "Qual o horário?"}])
        self.assertEqual(reply.consultations[0].name, "consultar_politicas")
        self.assertEqual(reply.consultations[1].name, "listar_categorias")
        self.assertTrue(all(trace.result["ok"] for trace in reply.consultations))

    def test_return_clarification_requires_a_new_policy_lookup(self):
        first = ChatAgent(FakeService(
            response("Foi uma compra online e quando você recebeu?"),
        )).reply([{"role": "user", "content": "Quero devolver a compra."}])
        agent = ChatAgent(FakeService(
            response("Pelo prazo informado, pode solicitar dentro da janela de sete dias, sujeito às condições do manual."),
        ))
        reply = agent.reply([*first.history, {"role": "user", "content": "Foi online e recebi há cinco dias."}])
        self.assertEqual(reply.consultations[0].arguments["topico"], "trocas_devolucoes")
        self.assertEqual(reply.consultations[0].origin, "roteamento")

    def test_policy_and_catalog_can_be_consulted_in_same_turn(self):
        with TemporaryDirectory() as directory:
            database = Path(directory) / "catalog.sqlite3"
            import_catalog(database=database)
            service = FakeService(
                response("O preço promocional é R$ 439,20, antes R$ 549,00. O PIX não acumula com a promoção."),
            )
            reply = ChatAgent(service, Catalog(database)).reply(
                [{"role": "user", "content": "Posso somar PIX ao desconto do Ohana CK-20?"}]
            )
            self.assertEqual(len(reply.consultations), 2)
            self.assertTrue(all(trace.result["ok"] for trace in reply.consultations))

    def test_return_authorization_or_shipping_instructions_are_replaced_by_guidance(self):
        for content in ("A devolução está autorizada.", "Envie o produto amanhã; iniciamos o processo."):
            with self.subTest(content=content):
                reply = ChatAgent(FakeService(response(content))).reply(
                    [{"role": "user", "content": "Quero devolver minha compra."}]
                )
                self.assertNotIn("está autorizada", reply.content)
                self.assertNotIn("Envie o produto", reply.content)
                self.assertIn("equipe precisa confirmar", reply.content)
                self.assertIn("7 (sete) dias corridos", reply.content)

    def test_named_pix_question_preloads_policy_and_product_before_generation(self):
        with TemporaryDirectory() as directory:
            database = Path(directory) / "catalog.sqlite3"
            import_catalog(database=database)
            service = FakeService(
                response("O Ohana CK-20 custa R$ 439,20 com promoção e o PIX não acumula."),
            )
            reply = ChatAgent(service, Catalog(database)).reply(
                [{"role": "user", "content": "Ohana CK-20 tem desconto no PIX?"}]
            )
            self.assertEqual(len(reply.consultations), 2)
            self.assertEqual(reply.consultations[-1].name, "buscar_produtos")
            self.assertEqual(reply.consultations[-1].origin, "roteamento")


if __name__ == "__main__":
    unittest.main()
