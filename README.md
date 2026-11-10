# Empório da Música

Protótipo em Python de um agente de atendimento para o desafio técnico de AI Engineer da Artefact. O objetivo é responder em português com a identidade da loja, consultar dados operacionais e políticas e lidar com perguntas fora do escopo.

## Funcionalidades disponíveis

- Chat em Streamlit com Ollama local, histórico em memória por sessão e opção de iniciar nova conversa.
- Diagnóstico de conexão, resposta em português e execução de uma ferramenta Python pelo modelo.
- Catálogo SQLite gerado dos CSVs de categorias, produtos e promoções.
- Consultas Python por texto, categoria, orçamento e disponibilidade, com cálculo exato de descontos.
- Testes automatizados de importação e regras do catálogo.

**A camada de catálogo ainda não está conectada ao chat.** O atendimento informa que as consultas comerciais estão em construção. Pedidos, políticas e ferramentas de atendimento serão adicionados nas próximas entregas.

## Requisitos e instalação

- Python **3.12**; dependências diretas e transitivas fixadas em `requirements.txt`.
- [Ollama](https://ollama.com/download) instalado para executar o chat e o diagnóstico do modelo.
- Modelo local `qwen3:4b-instruct`, com download de aproximadamente 2,5 GB. O desempenho depende do hardware disponível.

Na raiz do repositório, em Windows/PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Copie `.env.example` apenas na primeira configuração. Os comandos usam o Python do ambiente virtual diretamente, dispensando sua ativação no PowerShell.

### Preparar o catálogo e executar seus testes

```powershell
.\.venv\Scripts\python.exe -m emporio.import_data
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

A importação gera `data/catalog.sqlite3` com 9 categorias, 65 produtos e 25 promoções. O arquivo SQLite é um artefato local ignorado pelo Git; os CSVs necessários estão incluídos em `data/raw/`. A importação e os testes usam apenas a biblioteca padrão de Python e funcionam sem Ollama, GPU ou acesso à rede.

Para usar outros caminhos:

```powershell
.\.venv\Scripts\python.exe -m emporio.import_data --source-dir data/raw --database data/catalog.sqlite3
```

### Executar o chat

Abra o aplicativo Ollama ou mantenha outro terminal executando `ollama serve`. Com o serviço ativo:

```powershell
ollama pull qwen3:4b-instruct
.\.venv\Scripts\python.exe -m emporio.check_ollama
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Abra [http://localhost:8501](http://localhost:8501). Use `Ctrl+C` no terminal para encerrar o Streamlit. Não é necessária chave de API nem contratação de provedor. A primeira instalação exige internet; a inferência utiliza o serviço local.

Em Linux/macOS, crie o ambiente com `python3 -m venv .venv`, use `.venv/bin/python` e copie a configuração com `cp .env.example .env`.

### Configuração do modelo

| Variável | Padrão | Finalidade |
| --- | --- | --- |
| `OLLAMA_HOST` | `http://localhost:11434` | URL HTTP do serviço nesta máquina. |
| `OLLAMA_MODEL` | `qwen3:4b-instruct` | Modelo local a utilizar. |
| `OLLAMA_TIMEOUT_SECONDS` | `120` | Tempo de espera por requisição. |

Variáveis do processo têm prioridade sobre `.env`. A aplicação aceita endereços de loopback, rejeita tags de nuvem e não faz fallback para provedores externos. Utilize somente modelos locais, inclusive ao criar aliases no Ollama.

O adaptador usa `think=False`, temperatura 0,7, `top_p=0.8`, contexto de 4.096 tokens e limite de 1.024 tokens de geração. Esses parâmetros foram validados com a variante Instruct; trocar o modelo exige repetir o diagnóstico e pode exigir ajustes no adaptador.

| Problema | Recuperação |
| --- | --- |
| Serviço indisponível | Abra o Ollama ou execute `ollama serve`; confira `OLLAMA_HOST`. |
| Modelo ausente | Execute `ollama pull qwen3:4b-instruct` ou baixe o modelo configurado. |
| Timeout | Aguarde o carregamento inicial, tente novamente ou aumente `OLLAMA_TIMEOUT_SECONDS`. |
| Geração interrompida pelo limite | Inicie nova conversa e tente uma pergunta mais curta. |
| Catálogo ausente | Execute `python -m emporio.import_data` no ambiente do projeto. |
| CSV inválido | Corrija o arquivo e a linha indicados pelo importador; os registros anteriores são preservados. |

Mensagens cuja geração falha não são adicionadas ao histórico do chat. Corrigido o problema, a mensagem pode ser reenviada.

## Consultas e regras do catálogo

Exemplo em Python, depois da importação:

```python
from emporio.catalog import Catalog

catalog = Catalog()
categories = catalog.list_categories()
products = catalog.search_products(category_id=5, max_price_brl="1000.00", limit=5)
for product in products:
    print(product.name, product.price_brl, product.effective_price_brl)

product = catalog.get_product(121)
print(product.name, product.effective_price_brl)  # Ohana CK-20 Concert Natural, 439.20
```

- **Disponibilidade:** apenas `status=active` com estoque positivo. Lançamentos e descontinuados não aparecem na busca padrão, mesmo com estoque. `get_product()` também retorna indisponíveis para permitir explicar seu status; `available_only=False` permite incluí-los nas buscas.
- **Busca textual:** todos os termos devem aparecer no conjunto nome, descrição e categoria, desconsiderando acentos e maiúsculas. Não há expansão de sinônimos nem busca semântica. Os parâmetros são separados do SQL; caracteres como `%` são tratados literalmente.
- **Preços:** valores de origem são convertidos com `Decimal` e armazenados como centavos inteiros. O desconto percentual usa aritmética inteira, com arredondamento de meio centavo para cima. As propriedades em reais retornam `Decimal`.
- **Promoções:** somente `is_active=1` afeta o preço. Promoções inativas são preservadas na base. Mais de uma promoção ativa para o mesmo produto impede a importação, evitando escolher ou acumular descontos sem uma regra definida. A fonte atual não apresenta esse conflito.
- **Orçamento:** o limite é inclusivo e usa o preço após a promoção ativa. Informe reais como texto com ponto decimal ou `Decimal`, sem frações de centavo. Os resultados são ordenados por preço efetivo crescente e, em empate, por ID; o limite padrão é 10.
- **Atualização:** cada importação substitui integralmente o snapshot das três tabelas em uma transação. IDs duplicados, referências inválidas e erros de conteúdo impedem a atualização. Consultas abrem o banco em modo somente leitura.

O importador valida campos obrigatórios, inteiros, preços, status, datas, especificações JSON e integridade entre tabelas. Os descontos desta camada contemplam apenas as promoções cadastradas; PIX, parcelamento e demais regras de pagamento ainda não foram implementados. O preço de um item indisponível não representa uma oferta de venda.

## Decisões técnicas

| Escolha | Justificativa |
| --- | --- |
| Python | Linguagem principal exigida pelo desafio. |
| Ollama local e `qwen3:4b-instruct` | Atendem ao orçamento gratuito e permitem inferência local. A variante Instruct foi escolhida após a variante Thinking-2507 exceder o limite de geração no diagnóstico. A execução exige instalar o runtime e baixar os pesos. |
| SDK oficial direto | Mantém explícito o fluxo de mensagens e ferramentas, com poucas dependências de orquestração. |
| Streamlit e histórico por sessão | Permitem demonstrar conversas em Python sem implementar persistência de mensagens nesta versão. |
| SQLite gerado dos CSVs | Preserva relações e permite consultas parametrizadas sem servidor ou dependência de banco adicional. Os CSVs permanecem como fonte reproduzível. |
| Preços calculados em Python | Evitam coerção monetária para ponto flutuante. Após os filtros SQL de texto, categoria e disponibilidade, preço, ordenação e limite são aplicados em Python; essa abordagem é adequada ao snapshot de 65 produtos. |
| Biblioteca padrão para dados e testes | `csv`, `sqlite3`, `Decimal` e `unittest` atendem ao recorte atual sem novas dependências. |

Referências: [SDK Python do Ollama](https://github.com/ollama/ollama-python), [chamadas de ferramentas](https://docs.ollama.com/capabilities/tool-calling), [modelo utilizado](https://ollama.com/library/qwen3:4b-instruct) e [Streamlit](https://docs.streamlit.io/).

## Organização e fontes

```text
app.py                    Interface Streamlit
emporio/
  agent.py                Persona e comportamento inicial
  config.py               Configuração do modelo
  llm.py                  Adaptador do Ollama e tratamento de erros
  check_ollama.py          Diagnóstico real do modelo e de ferramenta
  database.py              Esquema SQLite, conexão e conversão monetária
  import_data.py           Importação e validação dos CSVs
  catalog.py               Consultas e regras do catálogo
data/raw/                 CSVs de catálogo fornecidos no desafio
tests/test_catalog.py     Testes de dados e regras de negócio
```

`data/raw/categories.csv`, `products.csv` e `promotions.csv` são cópias dos arquivos fornecidos, com os nomes simplificados e o conteúdo original preservado. Não são carregados dados de clientes ou pedidos nesta entrega.

| Fonte do desafio | Quantidade | Situação |
| --- | ---: | --- |
| Categorias | 9 | Incluídas e importadas. |
| Produtos | 65 | Incluídos e importados. |
| Promoções | 25, sendo 4 ativas | Incluídas e importadas. |
| Clientes | 50 | Fora da camada atual. |
| Pedidos / itens de pedidos | 20 / 22 | Fora da camada atual. |
| Manual de políticas | 8 páginas, versão 2.1 de junho de 2025 | Recuperação ainda não implementada. |

Os dados representam um snapshot do exercício, sem sincronização com uma operação real. Textos e especificações foram preservados; há inconsistências descritivas na fonte, como o produto 140 citar marcas e materiais diferentes entre nome, descrição e especificações. Elas não são corrigidas automaticamente.

O manual também contém ambiguidades que precisarão de interpretação documentada na implementação das políticas: dois números de WhatsApp, grafias diferentes do e-mail, mínimos de parcelamento divergentes e ausência de regra para frete local de exatamente R$ 500.

## Verificação

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

A suíte contém 23 testes, cobrindo importação do snapshot, reimportação, integridade referencial, rollback, disponibilidade, promoções, arredondamento, limite de orçamento, busca textual, consultas parametrizadas e leitura sem escrita. Os testes usam bancos e variações dos CSVs em diretórios temporários; não modificam as fontes versionadas nem exigem LLM.

O comando `python -m emporio.check_ollama` verifica separadamente a integração real com o modelo: frase em português, chamada `somar(17, 25)`, execução Python e uso do resultado `42` na resposta final. Ele não avalia a qualidade comercial do agente nem a seleção entre ferramentas de atendimento.

## Limitações e continuidade

- O catálogo está disponível pela API Python; a integração das consultas ao chat é a próxima entrega.
- Recuperação de políticas, consultas a pedidos e exemplos finais de atendimento ainda estão pendentes.
- As restrições do prompt não garantem ausência de alucinações ou resistência a prompt injection; a avaliação comercial e adversarial será ampliada com as ferramentas.
- O histórico não tem persistência, truncamento ou resumo automático. Conversas longas podem exceder o contexto do modelo.
- Não há autenticação, registro de reclamações ou integração com WhatsApp. O aplicativo é um protótipo local.

Com mais tempo: comparar modelos, medir qualidade e latência em cenários representativos, ampliar recuperação e avaliação e implementar identificação adequada para consultas de pedidos.

## Uso de IA

Foi utilizado **Codex** para análise das fontes, discussão de alternativas, implementação e auxílio na validação. As escolhas de execução local gratuita, Streamlit, SDK direto, SQLite e desenvolvimento em entregas incrementais foram discutidas com a pessoa candidata. As alterações são revisadas e commitadas pela pessoa candidata.

A entrega final deve conter um repositório público com histórico incremental, este README atualizado e entre 3 e 5 conversas de exemplo, incluindo um cenário não trivial. Os exemplos serão produzidos com as ferramentas comerciais funcionando.
