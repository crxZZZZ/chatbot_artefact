"""Avaliação de cenários do catálogo com o modelo real: python -m emporio.check_agent."""

import sys
from time import perf_counter
from decimal import Decimal

from emporio.agent import AgentError, ChatAgent
from emporio.config import load_settings
from emporio.database import normalize_text
from emporio.llm import OllamaService


def verify(agent: ChatAgent) -> None:
    def ask(question: str, history: list[dict] | None = None):
        print(f"\nCliente: {question}", flush=True)
        result = agent.reply([*(history or []), {"role": "user", "content": question}])
        print(f"Agente: {result.content}", flush=True)
        for trace in result.consultations:
            print(f"  [{trace.origin}] {trace.name}({trace.arguments}) -> ok={trace.result.get('ok')}", flush=True)
        return result

    def require(condition: bool, message: str) -> None:
        if not condition:
            raise ValueError(message)

    greeting = ask("oi")
    require(not greeting.consultations, "Saudação disparou uma consulta desnecessária.")
    require("se chama" not in normalize_text(greeting.content), "Saudação forçou uma confirmação de nome.")
    print("[OK] Saudação simples.", flush=True)

    broad = ask("Quais produtos vocês têm?")
    require(any(t.name == "listar_categorias" and t.result.get("ok") for t in broad.consultations), "Categorias não foram consultadas.")
    require(not any(t.name == "buscar_produtos" for t in broad.consultations), "Pedido amplo gerou vitrine arbitrária.")
    require("?" in broad.content, "Faltou perguntar a preferência do cliente.")
    print("[OK] Categorias e esclarecimento de preferência.", flush=True)

    budget = ask("Quais violões disponíveis custam até R$ 1000?", broad.history)
    searches = [t for t in budget.consultations if t.name == "buscar_produtos" and t.result.get("ok")]
    require(bool(searches), "A busca com orçamento não foi executada.")
    require(any(t.arguments.get("category_id") == 5 and Decimal(t.arguments.get("max_price_brl", "NaN")) == 1000 for t in searches), "Categoria ou orçamento não foram respeitados.")
    require("Rozini RC-104 Nylon Estudante" in budget.content, "O cenário de continuação precisa apresentar o segundo produto esperado.")
    print("[OK] Consulta de violões com orçamento.", flush=True)

    follow_up = ask("Quanto custa o segundo?", budget.history)
    require(any(t.name == "consultar_produto" and t.arguments.get("product_id") == 85 and t.result.get("ok") for t in follow_up.consultations), "O segundo produto não foi consultado corretamente.")
    require("Rozini RC-104 Nylon Estudante" in follow_up.content and "459,90" in follow_up.content, "Continuação não apresentou o nome/preço esperados.")
    print("[OK] Referência ordinal e nova consulta.", flush=True)

    promotion = ask("Quanto custa o Ohana CK-20? Tem promoção?")
    require(all(value in promotion.content for value in ("549,00", "439,20")), "Preço original ou promocional não foi apresentado.")
    require("20%" in promotion.content.replace(" ", ""), "Percentual de desconto incorreto ou ausente.")
    print("[OK] Preço original, desconto e preço final.", flush=True)

    unavailable = ask("Tem Giannini GF-3D em estoque?")
    require(any(term in normalize_text(unavailable.content) for term in (
        "esgotad", "sem estoque", "indisponivel", "nao esta em estoque", "estoque zero", "disponibilidade zero",
    )), "Indisponibilidade não foi informada.")
    alternatives = [p for t in unavailable.consultations if t.result.get("ok") for p in t.result.get("alternativas", [])]
    require(bool(alternatives) and all(p["disponivel"] for p in alternatives), "Faltaram alternativas realmente disponíveis.")
    require(any(p["nome"] in unavailable.content for p in alternatives), "Nenhuma alternativa consultada foi apresentada.")
    print("[OK] Produto sem estoque e alternativas consultadas.", flush=True)

    discontinued = ask("Posso comprar o Ibanez Bass 2X Electric Bass?")
    require(any(term in normalize_text(discontinued.content) for term in ("descontinuad", "fora de linha", "saiu de linha")), "Descontinuação não foi informada.")
    require("441,00" in discontinued.content, "Preço do saldo descontinuado não foi apresentado.")
    print("[OK] Venda do saldo descontinuado.", flush=True)

    outside = ask("Qual a capital da França?")
    require("paris" not in normalize_text(outside.content), "O agente respondeu conhecimentos gerais fora do atendimento.")
    require(not outside.consultations, "Pergunta fora de escopo disparou consulta ao catálogo.")
    print("[OK] Redirecionamento de pergunta fora do escopo.", flush=True)

    hours = ask("Qual o horário de funcionamento da loja?")
    require(any(t.name == "consultar_politicas" and t.arguments.get("topico") == "horarios" and t.result.get("ok") for t in hours.consultations), "Horário não foi consultado no manual.")
    require("18" in hours.content and "13" in hours.content, "Horários esperados não foram apresentados.")
    print("[OK] Horário fundamentado no manual.", flush=True)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    started = perf_counter()
    try:
        verify(ChatAgent(OllamaService(load_settings())))
    except (AgentError, ValueError) as exc:
        print(f"[ERRO] {exc}", file=sys.stderr)
        return 1
    print(f"\n[OK] Cenários concluídos em {perf_counter() - started:.2f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
