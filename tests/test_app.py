"""Estado de sessão e ausência de consultas técnicas na interface de atendimento."""

from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from emporio.agent import AgentError, AgentReply, ToolTrace
from emporio.database import PROJECT_ROOT


class ChatInterfaceTests(unittest.TestCase):
    def app(self):
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=10).run()
        self.assertFalse(app.exception)
        return app

    def test_initial_state_and_welcome_do_not_force_customer_name(self):
        app = self.app()
        self.assertEqual(app.session_state.agent_history, [])
        self.assertEqual(len(app.session_state.messages), 1)
        self.assertNotIn("Você se chama", app.session_state.messages[0]["content"])
        self.assertEqual(len(app.expander), 0)

    def test_technical_history_is_preserved_without_exposing_traces(self):
        trace = ToolTrace("listar_categorias", {}, {"ok": True, "categorias": [], "internal": "INTERNAL_TRACE_ONLY"}, "2026-11-10T12:00:00+00:00")
        captured = []

        def reply(history):
            captured.append(deepcopy(history))
            technical = [*history,
                         {"role": "assistant", "tool_calls": [{"function": {"name": trace.name, "arguments": {}}}]},
                         {"role": "tool", "tool_name": trace.name, "content": json.dumps(trace.result)},
                         {"role": "assistant", "content": "Qual instrumento interessa?"}]
            return AgentReply("Qual instrumento interessa?", technical, [trace])

        app = self.app()
        with patch("emporio.agent.ChatAgent.reply", side_effect=reply):
            app.chat_input[0].set_value("Quais produtos?").run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.session_state.messages), 3)
            self.assertEqual(len(app.expander), 0)
            self.assertEqual(len(app.get("json")), 0)
            self.assertNotIn("consultations", app.session_state.messages[-1])
            self.assertFalse(any("INTERNAL_TRACE_ONLY" in element.value for element in app.markdown))
            app.run()
            self.assertEqual(len(app.expander), 0)
            app.chat_input[0].set_value("Quero um violão.").run()
            self.assertTrue(any(message["role"] == "tool" for message in captured[1]))
            self.assertEqual(len(app.session_state.messages), 5)
            self.assertEqual(len(app.expander), 0)
            self.assertEqual(len(app.get("json")), 0)
            app.button[0].click().run()
            self.assertEqual(len(app.session_state.messages), 1)
            self.assertEqual(app.session_state.agent_history, [])
            self.assertEqual(len(app.expander), 0)
        other = self.app()
        self.assertEqual(len(other.session_state.messages), 1)
        self.assertEqual(other.session_state.agent_history, [])

    def test_failed_turn_hides_trace_without_polluting_history_and_can_be_retried(self):
        app = self.app()
        trace = ToolTrace("buscar_produtos", {"query": "Yamaha"}, {"ok": False}, "2026-11-10T12:00:00+00:00")
        with patch("emporio.agent.ChatAgent.reply", side_effect=AgentError("Falha de teste.", [trace])):
            app.chat_input[0].set_value("Quanto custa?").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.error[0].value, "Falha de teste.")
        self.assertEqual(len(app.expander), 0)
        self.assertEqual(len(app.get("json")), 0)
        self.assertEqual(len(app.session_state.messages), 1)
        self.assertEqual(app.session_state.agent_history, [])
        with patch("emporio.agent.ChatAgent.reply", side_effect=lambda history: AgentReply(
            "Qual modelo interessa?", [*history, {"role": "assistant", "content": "Qual modelo interessa?"}],
        )):
            app.chat_input[0].set_value("Quanto custa?").run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(len(app.session_state.messages), 3)
        self.assertEqual(len(app.session_state.agent_history), 2)


if __name__ == "__main__":
    unittest.main()
