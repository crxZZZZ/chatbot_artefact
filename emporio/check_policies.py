"""Cenários de política com o modelo real: python -m emporio.check_policies."""

import sys
import re

from emporio.agent import AgentError, ChatAgent
from emporio.config import load_settings
from emporio.database import normalize_text
from emporio.llm import OllamaService


def verify(agent: ChatAgent) -> None:
    def ask(question: str, history: list[dict] | None = None):
        print(f"\nCliente: {question}", flush=True)
        reply = agent.reply([*(history or []), {"role": "user", "content": question}])
        print(f"Agente: {reply.content}", flush=True)
        for trace in reply.consultations:
            print(f"  [{trace.origin}] {trace.name}({trace.arguments}) -> ok={trace.result.get('ok')}", flush=True)
        if not any(t.name == "consultar_politicas" and t.result.get("ok") for t in reply.consultations):
            raise ValueError("A pergunta não foi fundamentada no manual.")
        return reply

    def require(condition: bool, message: str) -> None:
        if not condition:
            raise ValueError(message)

    hours = ask("Qual é o horário de funcionamento da loja?")
    require("18" in hours.content and "13" in hours.content, "Horários esperados não foram apresentados.")
    address = ask("Qual o endereço da loja?")
    require("3200" in address.content and "Campo Grande" in address.content, "Endereço incorreto ou ausente.")

    contact = ask("Qual é o WhatsApp correto da loja?")
    require("3341" in contact.content and "3321" in contact.content, "A divergência de contatos foi ocultada.")
    require(any(term in normalize_text(contact.content) for term in ("confirm", "diverg", "diferent")), "Faltou orientar confirmação do contato.")

    shipping = ask("Quanto é o frete para um pedido de exatamente R$ 500 em Campo Grande?")
    require(any(term in normalize_text(shipping.content) for term in ("confirm", "nao define", "nao ha", "nao especific")), "A lacuna de frete não foi sinalizada.")

    first = ask("Me arrependi da compra e quero devolver.")
    require("online" in normalize_text(first.content) and "receb" in normalize_text(first.content)
            and any(marker in normalize_text(first.content) for marker in ("?", "preciso saber", "confirme", "me informe")),
            "Faltou esclarecer canal da compra e recebimento.")
    follow_up = ask("Foi online, recebi há cinco dias. Está sem uso e na embalagem original.", first.history)
    normalized = normalize_text(follow_up.content)
    require("7" in normalized or "sete" in normalized, "Prazo de arrependimento ausente.")
    require("esta autorizada" not in normalized and "envie o produto" not in normalized,
            "O agente autorizou ou instruiu envio sem fluxo de atendimento implementado.")

    mixed = ask("O Ohana CK-20 tem desconto e posso somar o desconto do PIX?")
    require(any(t.name in {"buscar_produtos", "consultar_produto"} and t.result.get("ok") for t in mixed.consultations),
            "Faltou consultar o produto na pergunta que mistura catálogo e política.")
    require("439,20" in mixed.content and "417,24" not in mixed.content, "O preço promocional foi alterado indevidamente.")
    require(bool(re.search(r"nao.{0,45}(acumul|cumul|som|aplic)", normalize_text(mixed.content))),
            "Faltou informar a regra de não cumulatividade.")
    print("\n[OK] Cenários de política concluídos.", flush=True)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        verify(ChatAgent(OllamaService(load_settings())))
    except (AgentError, ValueError) as exc:
        print(f"[ERRO] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
