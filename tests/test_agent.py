"""Ferramentas reais em SQLite e respostas controladas do SDK para testar a orquestração."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ollama import ChatResponse

from emporio.agent import AgentError, ChatAgent, MAX_TOOL_CALLS, MAX_TOOL_ROUNDS
from emporio.catalog import Catalog
from emporio.import_data import import_catalog
from emporio.llm import OllamaUnavailableError
from emporio.tools import CatalogTools


def response(content="", calls=(), thinking=None):
    return ChatResponse(message={
        "role": "assistant", "content": content, "thinking": thinking,
        "tool_calls": [{"function": {"name": name, "arguments": args}} for name, args in calls],
    })


class FakeService:
    def __init__(self, *responses, capabilities=("tools",), in_scope=True):
        self.responses = list(responses)
        self.requests = []
        self.capabilities = capabilities
        self.in_scope = in_scope

    def check_model(self):
        return self.capabilities

    def response_in_scope(self, question, answer):
        return self.in_scope

    def chat(self, messages, tools=None):
        self.requests.append(deepcopy(messages))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class CatalogAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "catalog.sqlite3"
        import_catalog(database=self.database)
        self.catalog = Catalog(self.database)
        self.tools = CatalogTools(self.catalog)

    def agent(self, *responses):
        service = FakeService(*responses)
        return ChatAgent(service, self.catalog), service

    def test_greeting_uses_no_catalog_tools(self):
        agent, service = self.agent()
        reply = agent.reply([{"role": "user", "content": "oi"}])
        self.assertEqual(reply.consultations, [])
        self.assertEqual(reply.content, "Oi! Como posso ajudar?")
        self.assertEqual(len(reply.history), 2)
        self.assertEqual(service.requests, [])

    def test_categories_use_real_catalog_and_have_no_price(self):
        result = self.tools.execute("listar_categorias", {})
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["categorias"]), 9)
        self.assertEqual(result["categorias"][4]["name"], "Violões")

    def test_tool_search_respects_budget_and_limits_results(self):
        result = self.tools.execute("buscar_produtos", {"category_id": 5, "max_price_brl": "1000.00"})
        self.assertTrue(result["ok"])
        self.assertEqual([p["produto_id"] for p in result["produtos"]], [83, 85, 89, 88, 81])
        self.assertEqual([p["posicao"] for p in result["produtos"]], [1, 2, 3, 4, 5])
        json.dumps(result)  # Não há Decimal ou objetos do SDK no resultado enviado ao modelo.

    def test_specific_product_can_be_found_when_out_of_stock(self):
        result = self.tools.execute("buscar_produtos", {"query": "Giannini GF-3D", "available_only": False})
        self.assertEqual(len(result["produtos"]), 1)
        self.assertFalse(result["produtos"][0]["disponivel"])
        self.assertEqual(result["produtos"][0]["estoque"], 0)
        self.assertTrue(result["alternativas"])
        self.assertTrue(all(p["disponivel"] and p["categoria_id"] == 5 for p in result["alternativas"]))
        self.assertFalse(any(p["produto_id"] == 96 for p in result["alternativas"]))

    def test_product_details_include_promotion_specs_and_discontinued_status(self):
        discounted = self.tools.execute("consultar_produto", {"product_id": 121})["produto"]
        self.assertEqual(discounted["preco_original_brl"], "549.00")
        self.assertEqual(discounted["preco_final_brl"], "439.20")
        self.assertEqual(discounted["promocao"]["percentual"], 20)
        self.assertIsInstance(discounted["especificacoes"], dict)
        discontinued = self.tools.execute("consultar_produto", {"product_id": 136})["produto"]
        self.assertTrue(discontinued["disponivel"])
        self.assertEqual(discontinued["status"], "discontinued")

    def test_empty_search_requests_category_clarification(self):
        self.assertEqual(self.tools.execute("buscar_produtos", {})["erro"], "argumentos_invalidos")

    def test_unknown_tools_and_invalid_arguments_are_not_executed(self):
        self.assertEqual(self.tools.execute("__import__", {})["erro"], "ferramenta_desconhecida")
        for name, args in (
            ("consultar_produto", {}), ("consultar_produto", {"product_id": True}),
            ("consultar_produto", {"product_id": -1}), ("listar_categorias", {"extra": 1}),
            ("buscar_produtos", {"query": "violão", "limit": 6}),
            ("buscar_produtos", {"category_id": 5, "max_price_brl": 1000}),
        ):
            with self.subTest(name=name, args=args):
                self.assertEqual(self.tools.execute(name, args)["erro"], "argumentos_invalidos")

    def test_missing_product_and_empty_results_are_successful_queries(self):
        self.assertIsNone(self.tools.execute("consultar_produto", {"product_id": 99999})["produto"])
        result = self.tools.execute("buscar_produtos", {"query": "produto-xyz-inexistente"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["produtos"], [])

    def test_tool_result_is_returned_to_model_with_trace(self):
        agent, service = self.agent(
            response(calls=[("consultar_produto", {"product_id": 121})]),
            response("Ohana CK-20 Concert Natural: de R$ 549,00 por R$ 439,20, desconto de 20%."),
        )
        history = [{"role": "user", "content": "Quanto custa o Ohana CK-20, ID 121?"}]
        original = deepcopy(history)
        reply = agent.reply(history)
        self.assertEqual(history, original)
        self.assertEqual(len(reply.consultations), 1)
        self.assertEqual(reply.consultations[0].name, "consultar_produto")
        self.assertTrue(reply.consultations[0].result["ok"])
        self.assertIn("+00:00", reply.consultations[0].consulted_at)
        tool_message = next(m for m in service.requests[1] if m["role"] == "tool")
        self.assertEqual(json.loads(tool_message["content"])["produto"]["preco_final_brl"], "439.20")

    def test_invalid_arguments_can_be_corrected_in_the_next_model_call(self):
        agent, _ = self.agent(
            response(calls=[("consultar_produto", {"product_id": 0})]),
            response(calls=[("consultar_produto", {"product_id": 121})]),
            response("O Ohana CK-20 custa R$ 439,20."),
        )
        reply = agent.reply([{"role": "user", "content": "Quanto custa o produto ID 121?"}])
        self.assertFalse(reply.consultations[0].result["ok"])
        self.assertTrue(reply.consultations[1].result["ok"])

    def test_price_without_a_current_query_requires_correction(self):
        agent, _ = self.agent(
            response("Esse instrumento custa R$ 1,00."),
            response(calls=[("consultar_produto", {"product_id": 121})]),
            response("O Ohana CK-20 custa R$ 439,20."),
        )
        reply = agent.reply([{"role": "user", "content": "Quanto custa o produto ID 121?"}])
        self.assertEqual(len(reply.consultations), 1)
        self.assertFalse(any(m["role"] == "system" for m in reply.history))
        self.assertNotIn("R$ 1,00", str(reply.history))

    def test_unsupported_prices_never_reach_a_successful_reply(self):
        agent, _ = self.agent(*[response("Preço R$ 1,00.") for _ in range(MAX_TOOL_ROUNDS + 1)])
        with self.assertRaises(AgentError):
            agent.reply([{"role": "user", "content": "Quanto custa?"}])

    def test_failed_catalog_is_visible_without_confirming_old_data(self):
        service = FakeService(
            response(calls=[("consultar_produto", {"product_id": 121})]),
            response("Não consegui verificar o catálogo agora. Tente novamente em instantes."),
        )
        agent = ChatAgent(service, Catalog(Path(self.temp.name) / "missing.sqlite3"))
        reply = agent.reply([{"role": "user", "content": "Quanto custa o produto ID 121?"}])
        self.assertEqual(reply.consultations[0].result["erro"], "catalogo_indisponivel")
        self.assertNotIn("R$", reply.content)

    def test_repeated_calls_stop_at_round_limit(self):
        agent, _ = self.agent(*[
            response(calls=[("consultar_produto", {"product_id": 81})]) for _ in range(MAX_TOOL_ROUNDS + 1)
        ])
        with self.assertRaises(AgentError) as raised:
            agent.reply([{"role": "user", "content": "Consulte o Yamaha C40, ID 81."}])
        self.assertEqual(len(raised.exception.consultations), MAX_TOOL_ROUNDS)

    def test_oversized_batch_is_rejected_before_execution(self):
        agent, _ = self.agent(response(calls=[("listar_categorias", {})] * (MAX_TOOL_CALLS + 1)))
        with self.assertRaises(AgentError) as raised:
            agent.reply([{"role": "user", "content": "Quais categorias?"}])
        self.assertEqual(raised.exception.consultations, [])

    def test_llm_failure_preserves_completed_consultations(self):
        agent, _ = self.agent(
            response(calls=[("consultar_produto", {"product_id": 81})]),
            OllamaUnavailableError("Tempo de espera excedido."),
        )
        with self.assertRaises(AgentError) as raised:
            agent.reply([{"role": "user", "content": "Quanto custa o Yamaha, ID 81?"}])
        self.assertEqual(len(raised.exception.consultations), 1)

    def test_invented_product_id_is_rejected_and_name_search_can_recover(self):
        agent, _ = self.agent(
            response(calls=[("consultar_produto", {"product_id": 102})]),
            response(calls=[("buscar_produtos", {"query": "Ohana CK-20", "available_only": False})]),
            response("Ohana CK-20 Concert Natural: R$ 439,20."),
        )
        reply = agent.reply([{"role": "user", "content": "Quanto custa o Ohana CK-20?"}])
        self.assertEqual(reply.consultations[0].result["erro"], "id_desconhecido")
        self.assertEqual(reply.consultations[1].result["produtos"][0]["produto_id"], 121)

    def test_reasoning_is_not_saved_in_history_or_traces(self):
        agent, _ = self.agent(
            response(calls=[("listar_categorias", {})], thinking="raciocinio-secreto"),
            response("Temos guitarras e violões. Qual instrumento interessa?", thinking="raciocinio-secreto"),
        )
        reply = agent.reply([{"role": "user", "content": "Quais produtos?"}])
        self.assertNotIn("raciocinio-secreto", str(reply))

    def test_model_without_tool_support_fails_clearly(self):
        agent = ChatAgent(FakeService(capabilities=()), self.catalog)
        with self.assertRaisesRegex(AgentError, "suporte a ferramentas"):
            agent.reply([{"role": "user", "content": "Quais produtos vocês têm?"}])

    def test_general_knowledge_answer_is_replaced_by_store_redirection(self):
        service = FakeService(response("A capital da França é Paris."), in_scope=False)
        reply = ChatAgent(service, self.catalog).reply([{"role": "user", "content": "Qual a capital da França?"}])
        self.assertNotIn("Paris", reply.content)
        self.assertIn("Empório da Música", reply.content)
        self.assertNotIn("Paris", str(reply.history))

    def test_social_response_can_preserve_customer_name(self):
        agent, _ = self.agent(response("Você se chama Gabriel."))
        reply = agent.reply([{"role": "user", "content": "Meu nome é Gabriel. Como eu me chamo?"}])
        self.assertEqual(reply.content, "Você se chama Gabriel.")

    def listed_options(self):
        agent, _ = self.agent(
            response(calls=[("buscar_produtos", {"category_id": 5, "max_price_brl": "1000.00", "limit": 3})]),
            response("1. Tagima Memphis AC-39 Nylon Natural\n2. Rozini RC-104 Nylon Estudante\n3. Shelby SN-100 Folk Aço Preto"),
        )
        return agent.reply([{"role": "user", "content": "Violões até mil reais?"}])

    def test_second_option_is_bound_to_display_order_and_wrong_id_is_rejected(self):
        previous = self.listed_options()
        agent, _ = self.agent(
            response(calls=[("consultar_produto", {"product_id": 89})]),
            response(calls=[("consultar_produto", {"product_id": 85})]),
            response("O Rozini RC-104 Nylon Estudante custa R$ 459,90."),
        )
        reply = agent.reply([*previous.history, {"role": "user", "content": "Quanto custa o segundo?"}])
        self.assertEqual(reply.consultations[0].result["erro"], "referencia_incorreta")
        self.assertEqual(reply.consultations[1].arguments["product_id"], 85)

    def test_ordinal_uses_names_displayed_by_assistant_not_raw_result_position(self):
        previous = self.listed_options()
        previous.history[-1]["content"] = "1. Rozini RC-104 Nylon Estudante\n2. Tagima Memphis AC-39 Nylon Natural"
        agent, _ = self.agent(
            response(calls=[("consultar_produto", {"product_id": 83})]),
            response("Tagima Memphis AC-39 Nylon Natural: R$ 429,90."),
        )
        reply = agent.reply([*previous.history, {"role": "user", "content": "E a segunda opção?"}])
        self.assertEqual(reply.consultations[0].arguments["product_id"], 83)

    def test_ordinal_reply_identifies_product_even_when_model_omits_its_name(self):
        previous = self.listed_options()
        agent, _ = self.agent(
            response(calls=[("consultar_produto", {"product_id": 85})]),
            response("O segundo custa R$ 459,90."),
        )
        reply = agent.reply([*previous.history, {"role": "user", "content": "Quanto custa o segundo?"}])
        self.assertIn("Rozini RC-104 Nylon Estudante", reply.content)

    def test_unresolved_ordinal_asks_for_clarification_without_guessing(self):
        agent, service = self.agent()
        reply = agent.reply([{"role": "user", "content": "Quanto custa o segundo?"}])
        self.assertIn("nome ou modelo", reply.content)
        self.assertEqual(service.requests, [])

    def test_second_alternative_excludes_unavailable_product_in_intro(self):
        agent, _ = self.agent(
            response(calls=[("buscar_produtos", {"query": "Giannini GF-3D", "available_only": False})]),
            response("Giannini GF-3D Dreadnought Sunburst está esgotado.\n"
                     "1. Tagima Memphis AC-39 Nylon Natural\n2. Rozini RC-104 Nylon Estudante\n"
                     "3. Shelby SN-100 Folk Aço Preto"),
        )
        previous = agent.reply([{"role": "user", "content": "Tem Giannini GF-3D?"}])
        agent, _ = self.agent(
            response(calls=[("consultar_produto", {"product_id": 85})]),
            response("Rozini RC-104 Nylon Estudante: R$ 459,90."),
        )
        reply = agent.reply([*previous.history, {"role": "user", "content": "E o segundo?"}])
        self.assertEqual(reply.consultations[0].arguments["product_id"], 85)

    def test_follow_up_on_removed_product_does_not_loop_or_reuse_old_price(self):
        previous = self.listed_options()
        agent = ChatAgent(FakeService(
            response(calls=[("consultar_produto", {"product_id": 85})]),
            response("O produto consultado não foi encontrado no catálogo atual."),
        ), self.catalog)
        from contextlib import closing
        from emporio.database import connect_database
        with closing(connect_database(self.database, read_only=False)) as connection, connection:
            connection.execute("DELETE FROM products WHERE product_id = 85")
        reply = agent.reply([*previous.history, {"role": "user", "content": "E o segundo?"}])
        self.assertIsNone(reply.consultations[0].result["produto"])

    def test_follow_up_reloads_price_instead_of_reusing_old_tool_results(self):
        previous = self.listed_options()
        # Alteração posterior no banco: a resposta deve usar a nova consulta.
        from emporio.database import connect_database
        from contextlib import closing
        with closing(connect_database(self.database, read_only=False)) as connection, connection:
            connection.execute("UPDATE products SET price_cents = 48000 WHERE product_id = 85")
        agent, _ = self.agent(
            response(calls=[("consultar_produto", {"product_id": 85})]),
            response("Rozini RC-104 Nylon Estudante: R$ 480,00."),
        )
        reply = agent.reply([*previous.history, {"role": "user", "content": "Quanto custa o segundo?"}])
        self.assertEqual(reply.consultations[0].result["produto"]["preco_final_brl"], "480.00")


if __name__ == "__main__":
    unittest.main()
