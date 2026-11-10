"""Capture conversas reais: python -m emporio.export_examples --output-dir tmp/conversas."""

import argparse
from datetime import datetime
from pathlib import Path
import sys

from emporio.agent import AgentError, ChatAgent, WELCOME
from emporio.config import load_settings
from emporio.llm import OllamaService


SCENARIOS = (
    (
        "01_catalogo_orcamento.md",
        "Catálogo, orçamento e continuidade",
        (
            "Quais produtos vocês têm?",
            "Quais violões disponíveis custam até R$ 1000?",
            "Quanto custa o segundo?",
        ),
    ),
    (
        "02_promocao_pix.md",
        "Promoção e condição de pagamento",
        ("O Ohana CK-20 tem desconto e posso somar o desconto do PIX?",),
    ),
    (
        "03_devolucao.md",
        "Devolução e esclarecimento das condições",
        (
            "Me arrependi da compra e quero devolver.",
            "Foi online, recebi há cinco dias. Está sem uso e na embalagem original, com todos os manuais e acessórios.",
        ),
    ),
    (
        "04_fora_do_escopo.md",
        "Pergunta fora do escopo e retorno ao atendimento",
        (
            "Qual a capital da França?",
            "Tudo bem. Qual é o horário de funcionamento da loja?",
        ),
    ),
)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("tmp/conversas"),
                        help="Diretório novo para os quatro arquivos; não sobrescreve capturas existentes.")
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("O diretório de saída já existe. Escolha outro caminho para preservar as capturas.")

    try:
        settings = load_settings()
        agent = ChatAgent(OllamaService(settings))
        documents = []
        for filename, title, questions in SCENARIOS:
            captured_at = datetime.now().astimezone().isoformat(timespec="seconds")
            history = []
            parts = [
                f"# {title}",
                f"Captura: `{captured_at}` · Modelo configurado: `{settings.model}`.",
                "Conversa executada pelo mesmo agente usado no chat, com histórico independente. "
                "A saudação é a mensagem inicial da interface; as respostas abaixo foram preservadas sem edição.",
                "## Assistente", WELCOME,
            ]
            print(f"\n=== {title} ===", flush=True)
            for question in questions:
                print(f"Cliente: {question}", flush=True)
                reply = agent.reply([*history, {"role": "user", "content": question}])
                history = reply.history
                parts.extend(["## Cliente", question, "## Assistente", reply.content])
                print(f"Assistente: {reply.content}", flush=True)
                for trace in reply.consultations:
                    print(f"  [{trace.origin}] {trace.name}({trace.arguments}) "
                          f"-> ok={trace.result.get('ok')}", flush=True)
            documents.append((filename, "\n\n".join(parts) + "\n"))

        # Só grava após concluir os quatro cenários; não publica uma captura parcial por erro do agente.
        args.output_dir.mkdir(parents=True, exist_ok=False)
        for filename, content in documents:
            (args.output_dir / filename).write_text(content, encoding="utf-8")
    except (AgentError, ValueError, OSError) as exc:
        print(f"[ERRO] {exc}", file=sys.stderr)
        return 1
    print(f"\nQuatro conversas gravadas em {args.output_dir}. Revise as respostas antes de publicá-las.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
