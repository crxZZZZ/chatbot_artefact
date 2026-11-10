"""Ferramentas de leitura do catálogo expostas ao modelo por JSON Schema."""

from copy import deepcopy
import sqlite3

from emporio.catalog import Catalog, Product
from emporio.database import CatalogError


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "listar_categorias",
            "description": (
                "Liste as categorias de instrumentos e seus IDs. Use quando o cliente perguntar "
                "quais produtos a loja tem sem informar preferência. Apresente as categorias e "
                "pergunte qual instrumento ou orçamento interessa. Também use para descobrir IDs de categoria."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_produtos",
            "description": (
                "Consulte produtos, preços, estoque e promoções. Combine categoria, orçamento e termos "
                "do nome/modelo. Não envie uma frase inteira como busca. Para um produto específico, "
                "use available_only=false para encontrar também itens esgotados e lançamentos. "
                "Para recomendações, use available_only=true. Resultados por preço crescente. "
                "Se não houver resultados, simplifique os termos ou peça esclarecimento; não conclua "
                "que a categoria inteira está indisponível."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Marca ou modelo; vazio quando filtrar só por categoria/orçamento."},
                    "category_id": {"type": "integer", "minimum": 1, "description": "ID obtido em listar_categorias; não invente."},
                    "max_price_brl": {"type": "string", "description": "Orçamento em reais com ponto decimal, por exemplo 1000.00."},
                    "available_only": {"type": "boolean", "description": "Padrão true. False para consultar produto específico mesmo indisponível."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 5, "description": "Máximo de resultados, padrão 5."},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_produto",
            "description": (
                "Obtenha detalhes e preço/estoque atuais de um produto pelo ID retornado anteriormente. "
                "Use para continuações como 'e o segundo?' e perguntas sobre características. "
                "Não invente IDs. O retorno inclui produtos indisponíveis e descontinuados."
            ),
            "parameters": {
                "type": "object",
                "properties": {"product_id": {"type": "integer", "minimum": 1}},
                "required": ["product_id"],
                "additionalProperties": False,
            },
        },
    },
]


def product_summary(product: Product) -> dict:
    if product.stock_quantity <= 0:
        situation = "Sem estoque; não pode ser oferecido como disponível."
    elif product.status == "coming_soon":
        situation = "Lançamento ainda não liberado para venda."
    elif product.status == "discontinued":
        situation = "Fora de linha, venda limitada ao saldo existente; sem promessa de reposição."
    else:
        situation = "Disponível para venda."
    return {
        "produto_id": product.product_id, "nome": product.name,
        "categoria_id": product.category_id, "categoria": product.category_name,
        "status": product.status, "disponivel": product.available,
        "estoque": product.stock_quantity, "situacao": situation,
        "preco_original_brl": str(product.price_brl),
        "preco_final_brl": str(product.effective_price_brl),
        "promocao": (
            {"percentual": product.discount_percent, "descricao": product.promotion_description}
            if product.promotion_id is not None else None
        ),
    }


class CatalogTools:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        self.handlers = {
            "listar_categorias": self._categories,
            "buscar_produtos": self._search,
            "consultar_produto": self._product,
        }

    @property
    def definitions(self) -> list[dict]:
        return deepcopy(TOOL_DEFINITIONS)

    def execute(self, name: str, arguments: dict) -> dict:
        if name not in self.handlers:
            return {"ok": False, "erro": "ferramenta_desconhecida", "mensagem": "Use apenas as ferramentas de catálogo fornecidas."}
        try:
            self._validate(name, arguments)
            return {"ok": True, **self.handlers[name](**arguments)}
        except ValueError as exc:
            return {"ok": False, "erro": "argumentos_invalidos", "mensagem": str(exc)}
        except (CatalogError, sqlite3.Error, OSError):
            return {
                "ok": False, "erro": "catalogo_indisponivel",
                "mensagem": "Não foi possível consultar o catálogo. Não confirme preço ou estoque.",
                "recuperacao": "Execute python -m emporio.import_data e verifique o banco local.",
            }

    def _validate(self, name: str, arguments: dict) -> None:
        if not isinstance(arguments, dict):
            raise ValueError("Os argumentos devem ser um objeto JSON.")
        schema = next(t["function"]["parameters"] for t in TOOL_DEFINITIONS if t["function"]["name"] == name)
        properties = schema["properties"]
        if set(arguments) - properties.keys():
            raise ValueError("Há argumentos desconhecidos; siga o esquema da ferramenta.")
        if any(key not in arguments for key in schema.get("required", [])):
            raise ValueError("Faltam argumentos obrigatórios da ferramenta.")
        types = {"string": str, "integer": int, "boolean": bool}
        for key, value in arguments.items():
            spec = properties[key]
            if type(value) is not types[spec["type"]]:
                raise ValueError(f"{key} deve ter tipo {spec['type']}.")
            if "minimum" in spec and value < spec["minimum"]:
                raise ValueError(f"{key} deve ser pelo menos {spec['minimum']}.")
            if "maximum" in spec and value > spec["maximum"]:
                raise ValueError(f"{key} deve ser no máximo {spec['maximum']}.")

    def _categories(self) -> dict:
        return {"categorias": [
            {"category_id": category.category_id, "name": category.name}
            for category in self.catalog.list_categories()
        ]}

    def _search(
        self, query: str = "", category_id: int | None = None,
        max_price_brl: str | None = None, available_only: bool = True, limit: int = 5,
    ) -> dict:
        if not query.strip() and category_id is None and max_price_brl is None:
            raise ValueError("Para um pedido amplo, consulte listar_categorias e pergunte a preferência do cliente.")
        products = self.catalog.search_products(
            query, category_id=category_id, max_price_brl=max_price_brl,
            available_only=available_only, limit=limit,
        )
        return {
            "produtos": [{"posicao": i, **product_summary(product)} for i, product in enumerate(products, 1)],
            "limite": limit, "ordem": "preco_final_crescente",
            "alternativas": (
                self._alternatives(products[0], max_price_brl)
                if len(products) == 1 and not products[0].available else []
            ),
        }

    def _alternatives(self, product: Product, max_price_brl: str | None = None) -> list[dict]:
        return [product_summary(alternative) for alternative in self.catalog.search_products(
            category_id=product.category_id, max_price_brl=max_price_brl, available_only=True, limit=3,
        )]

    def _product(self, product_id: int) -> dict:
        product = self.catalog.get_product(product_id)
        if product is None:
            return {"produto": None, "mensagem": "ID não encontrado no catálogo."}
        return {
            "produto": {**product_summary(product), "descricao": product.description, "especificacoes": product.specs},
            "alternativas": self._alternatives(product) if not product.available else [],
        }
