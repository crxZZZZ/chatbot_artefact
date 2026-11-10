"""Verificação real do modelo: python -m emporio.check_ollama."""

import json
import sys
from time import perf_counter

from emporio.config import load_settings
from emporio.llm import OllamaService, OllamaUnavailableError


def somar(a: int, b: int) -> int:
    """Some dois números inteiros.

    Args:
        a: Primeiro número inteiro.
        b: Segundo número inteiro.
    """
    if type(a) is not int or type(b) is not int:
        raise ValueError("A ferramenta somar aceita somente inteiros.")
    return a + b


def verify(service: OllamaService) -> None:
    started = perf_counter()
    capabilities = service.check_model()
    print(f"[OK] Conexão e modelo local: {service.settings.model}", flush=True)
    if "tools" not in capabilities:
        raise ValueError("O modelo não anuncia suporte a ferramentas. Escolha um modelo local com suporte a tools.")

    greeting = "Olá, estou pronto para ajudar."
    response_started = perf_counter()
    response = service.chat([
        {"role": "system", "content": "Responda somente em português brasileiro. Siga o formato pedido."},
        {"role": "user", "content": f"Responda exatamente com esta frase, sem aspas: {greeting}"},
    ])
    if response.message.tool_calls or response.message.content.strip() != greeting:
        raise ValueError(f"A resposta não correspondeu à frase em português solicitada: {response.message.content!r}")
    print(f"[OK] Resposta em português ({perf_counter() - response_started:.2f}s): {response.message.content}", flush=True)

    messages = [
        {"role": "system", "content": "Você valida ferramentas. Use a função somar para calcular; não calcule sozinho. Responda em português."},
        {"role": "user", "content": "Use a ferramenta somar uma vez para somar os inteiros 17 e 25. Depois informe o resultado."},
    ]
    tool_started = perf_counter()
    response = service.chat(messages, tools=[somar])
    calls = response.message.tool_calls or []
    if len(calls) != 1 or calls[0].function.name != "somar":
        raise ValueError("O modelo não solicitou exatamente uma chamada da ferramenta somar.")
    arguments = calls[0].function.arguments
    if arguments != {"a": 17, "b": 25}:
        raise ValueError(f"Argumentos inesperados na chamada da ferramenta: {arguments!r}")
    result = somar(**arguments)
    if result != 42:
        raise ValueError("A ferramenta não retornou o resultado esperado, 42.")
    messages.append(response.message)
    messages.append({"role": "tool", "tool_name": "somar", "content": json.dumps({"resultado": result})})
    final = service.chat(messages, tools=[somar])
    if final.message.tool_calls or "42" not in final.message.content:
        raise ValueError("O modelo não concluiu a resposta com o resultado retornado pela ferramenta.")
    print(f"[OK] Ferramenta executada: somar(17, 25) = {result}", flush=True)
    print(f"[OK] Resposta após a ferramenta ({perf_counter() - tool_started:.2f}s): {final.message.content}", flush=True)
    print(f"[OK] Verificação concluída em {perf_counter() - started:.2f}s.", flush=True)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        verify(OllamaService(load_settings()))
    except (OllamaUnavailableError, ValueError) as exc:
        print(f"[ERRO] {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
