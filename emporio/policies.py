"""Recuperação local por tópicos e seções do manual fornecido no desafio."""

from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import re

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from emporio.database import PROJECT_ROOT


DEFAULT_MANUAL = PROJECT_ROOT / "data" / "raw" / "politicas_da_loja.pdf"
TOPICS = {
    "loja": ("1.2",),
    "contato": ("capa", "1.2", "7"),
    "horarios": ("2",),
    "pagamentos": ("3", "3.1", "6.2"),
    "trocas_devolucoes": ("4", "4.1", "4.2", "4.3", "4.4", "8.1"),
    "frete_entregas": ("5.1", "5.2", "5.3"),
    "promocoes": ("6.1", "6.2", "3"),
    "atendimento": ("7", "7.1", "7.2", "7.3"),
    "garantia": ("8.1", "8.2", "8.3", "4.2"),
    "privacidade": ("9",),
}

# Interpretações explícitas para o manual v2.1; não alteram o texto da fonte.
NOTES = {
    "contato": [
        "Há contatos divergentes: capa/seção 1.2 trazem (67) 3341-4444, enquanto a seção 7 traz (67) 3321-4500. "
        "O e-mail da capa não tem acento no domínio; o da seção 1.2 tem. Se perguntarem qual contato usar, "
        "explique a divergência e peça confirmação à equipe, sem escolher silenciosamente. O endereço é consistente.",
    ],
    "horarios": [
        "Informe o horário regular. Não há calendário de feriados ou consulta a mudanças excepcionais em tempo real.",
    ],
    "pagamentos": [
        "A tabela geral informa parcela mínima de R$ 100,00, mas a seção 3.1 apresenta faixas diferentes. "
        "Quando essa diferença afetar a pergunta, explique que as condições precisam ser confirmadas pela equipe. "
        "Não calcule nem autorize um parcelamento específico com base em uma interpretação arbitrária.",
        "O desconto de PIX é de 5% sobre preço de tabela e não é cumulativo com promoção ativa. "
        "Esta ferramenta explica regras; não executa pagamentos nem calcula uma cotação final.",
    ],
    "trocas_devolucoes": [
        "Para arrependimento, descubra se a compra foi online e quando o produto foi recebido. "
        "Se faltar essa informação, apresente a regra de forma condicional e pergunte. "
        "Não use a data de compra como data de recebimento e não diga que a devolução foi autorizada ou registrada.",
        "As exceções da seção 4.4 são descritas como itens não elegíveis para troca. "
        "Não estenda automaticamente essas exceções a todos os direitos de devolução; caso haja conflito, "
        "oriente confirmação com a equipe. Os 30 dias para troca por defeito não encerram toda a garantia: "
        "a seção 8.1 também informa 90 dias de garantia legal após o recebimento.",
    ],
    "frete_entregas": [
        "O manual não define frete local para pedido de EXATAMENTE R$ 500,00. "
        "Nesse valor, informe a lacuna e peça confirmação à equipe; não escolha frete grátis nem R$ 35,00. "
        "Para outras cidades, não há calculadora de frete integrada; não invente cotação pelo CEP.",
        "Os prazos são estimativas gerais da política. Não há consulta a pedido individual, "
        "rastreio real nem data de entrega confirmada nesta versão.",
    ],
    "promocoes": [
        "Campanhas citadas no manual são exemplos periódicos, não prova de promoção vigente. "
        "Para preço e promoção de um produto, consulte também o catálogo. PIX não acumula com promoção ativa. "
        "Não calcule novos preços nesta ferramenta.",
    ],
    "atendimento": [
        "O manual descreve ações da equipe, mas o protótipo só consulta informações: "
        "não registra nem encaminha reclamações, não envia mensagens e não cria reservas. "
        "Oriente procurar a equipe, sem afirmar que executou essas ações.",
        "Decisão do protótipo: produto descontinuado com saldo pode ser vendido até esgotar o estoque. "
        "Consulte o catálogo e preserve esse status, sem prometer reposição. Há números de contato divergentes; "
        "consulte o tópico contato antes de indicar um canal.",
    ],
    "garantia": [
        "Não confunda 30 dias de troca por defeito com os 90 dias de garantia legal após o recebimento. "
        "A garantia do fabricante depende do certificado e não está cadastrada por produto. "
        "Em caso de conflito ou falta de dados, oriente confirmação com a equipe; não autorize uma troca.",
    ],
    "privacidade": [
        "Explique a política. O protótipo não exclui dados, altera consentimentos nem registra solicitações.",
    ],
}

HEADING = re.compile(r"^(\d{1,2}(?:\.\d+)?)[.]?\s+([A-Za-zÀ-ÿ].*)$")


class PolicyError(RuntimeError):
    """O manual não pôde ser recuperado com a estrutura esperada."""


@lru_cache(maxsize=4)
def _read_manual(path: str, modified_ns: int, size: int) -> dict:
    # mtime e tamanho participam da chave para reler o PDF quando o arquivo mudar.
    try:
        reader = PdfReader(path)
        pages = [page.extract_text(extraction_mode="layout") for page in reader.pages]
    except (OSError, PdfReadError, ValueError) as exc:
        raise PolicyError("Não foi possível extrair o manual de políticas.") from exc
    if not pages:
        raise PolicyError("O manual não contém páginas.")
    version = re.search(r"Versão\s+([\d.]+)", pages[0] or "")
    if not version or version[1] != "2.1":
        raise PolicyError("A versão do manual precisa ser revisada antes de usar esta recuperação.")
    sections = {"capa": {"secao": "capa", "titulo": "Capa", "paginas": [1], "linhas": []}}
    current = "capa"
    for page_number, text in enumerate(pages, 1):
        for line in (text or "").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("Empório da Música Manual") or re.fullmatch(r"Página\s+\d+", stripped):
                continue
            heading = HEADING.match(line)
            if heading:
                current, title = heading.groups()
                if current in sections:
                    raise PolicyError(f"Seção duplicada no manual: {current}.")
                sections[current] = {"secao": current, "titulo": title, "paginas": [], "linhas": []}
            section = sections[current]
            if page_number not in section["paginas"]:
                section["paginas"].append(page_number)
            section["linhas"].append(re.sub(r"\s+", " ", stripped))
    required = {section for ids in TOPICS.values() for section in ids}
    if required - sections.keys():
        raise PolicyError("Não foram encontradas todas as seções esperadas no manual.")
    for section in sections.values():
        section["texto"] = "\n".join(section.pop("linhas"))
    return {"versao": version[1], "secoes": sections}


class PolicyStore:
    def __init__(self, path: Path = DEFAULT_MANUAL):
        self.path = Path(path)

    def lookup(self, topic: str) -> dict:
        if topic not in TOPICS:
            raise ValueError("Tópico de política desconhecido.")
        try:
            stat = self.path.stat()
            manual = _read_manual(str(self.path.resolve()), stat.st_mtime_ns, stat.st_size)
        except OSError as exc:
            raise PolicyError("Manual de políticas não encontrado.") from exc
        return {
            "topico": topic,
            "fonte": {"arquivo": self.path.name, "versao": manual["versao"]},
            "trechos": deepcopy([manual["secoes"][section] for section in TOPICS[topic]]),
            "orientacoes": list(NOTES.get(topic, [])),
        }
