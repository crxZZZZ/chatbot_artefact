# Empório da Música

Protótipo em Python de um agente de atendimento para o desafio técnico de AI Engineer da Artefact. O objetivo é responder em português com a identidade da loja, consultar dados operacionais e políticas e lidar com perguntas fora do escopo.

## Funcionalidades disponíveis

- Chat em Streamlit com Ollama local, histórico em memória por sessão e opção de iniciar nova conversa.
- Diagnóstico de conexão, resposta em português e execução de uma ferramenta Python pelo modelo.
- Catálogo SQLite gerado dos CSVs de categorias, produtos e promoções.
- Consultas Python por texto, categoria, orçamento e disponibilidade, com cálculo exato de descontos.
- Consultas ao catálogo pelo chat, com chamadas de ferramentas executadas internamente.
- Apresentação de categorias em pedidos amplos e continuidade para referências como “o segundo produto”.
- Testes automatizados de dados, orquestração e estado da interface; avaliação separada com o modelo real.

**Pedidos e políticas ainda não estão integrados.** O agente informa essa limitação para questões como rastreamento, devoluções, horário e formas de pagamento. As consultas atuais são somente de leitura do catálogo fornecido no exercício.

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

A importação gera `data/catalog.sqlite3` com 9 categorias, 65 produtos e 25 promoções. O arquivo SQLite é um artefato local ignorado pelo Git; os CSVs necessários estão incluídos em `data/raw/`. A camada de dados usa apenas a biblioteca padrão. A suíte completa utiliza as dependências já instaladas, incluindo SDK e Streamlit, com respostas controladas do modelo; não exige servidor Ollama, GPU ou acesso à rede.

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

O adaptador usa `think=False`, temperatura 0,7, `top_p=0.8`, contexto de 8.192 tokens e limite de 1.024 tokens de geração. O contexto acomoda definições de ferramentas, resultados e histórico técnico. Esses parâmetros foram avaliados com a variante Instruct; trocar o modelo exige repetir os diagnósticos e pode exigir ajustes no adaptador.

| Problema | Recuperação |
| --- | --- |
| Serviço indisponível | Abra o Ollama ou execute `ollama serve`; confira `OLLAMA_HOST`. |
| Modelo ausente | Execute `ollama pull qwen3:4b-instruct` ou baixe o modelo configurado. |
| Timeout | Aguarde o carregamento inicial, tente novamente ou aumente `OLLAMA_TIMEOUT_SECONDS`. |
| Geração interrompida pelo limite | Inicie nova conversa e tente uma pergunta mais curta. |
| Catálogo ausente | Execute `python -m emporio.import_data` no ambiente do projeto. |
| Limite de tentativas de consulta | Reformule a pergunta ou informe o nome/modelo desejado. |
| CSV inválido | Corrija o arquivo e a linha indicados pelo importador; os registros anteriores são preservados. |

Mensagens cuja geração falha não são adicionadas ao histórico do chat. Corrigido o problema, a mensagem pode ser reenviada.

## Atendimento e ferramentas

O modelo recebe as definições das ferramentas e pode solicitá-las antes de responder. O Python valida os argumentos, executa as consultas e devolve os resultados ao modelo. Há no máximo quatro rodadas de execução e oito chamadas por turno. Ações desconhecidas e argumentos inválidos geram retornos de erro, permitindo uma correção dentro desse limite.

| Ferramenta | Comportamento |
| --- | --- |
| `listar_categorias` | Retorna nomes e IDs das categorias. Pedidos amplos recebem as categorias e uma pergunta de preferência ou orçamento. |
| `buscar_produtos` | Combina termos, categoria, orçamento e disponibilidade, retornando até cinco resultados. Para um único produto indisponível, inclui até três alternativas disponíveis da mesma categoria. |
| `consultar_produto` | Retorna preço, estoque, status, descrição e especificações por um ID já consultado ou explicitamente informado pelo cliente. Também inclui alternativas se o produto estiver indisponível. |

O modelo não gera SQL nem realiza compras, reservas ou alterações de estoque. IDs não obtidos em consultas nem informados pelo cliente são rejeitados; a ferramenta de detalhes só é oferecida quando há IDs conhecidos na conversa. As alternativas usam a mesma categoria e ordenação por preço, sem garantia de equivalência de características.

O histórico técnico conserva chamadas e resultados para identificar os produtos discutidos. Referências ordinais do primeiro ao quinto item são vinculadas à ordem dos nomes efetivamente apresentados; quando não é possível identificar a opção com segurança, o agente pede esclarecimento. A resposta sobre o item referido exige nova consulta. Nomes abreviados pelo modelo podem impedir esse vínculo.

O prompt orienta novas consultas para preço, estoque e detalhes. Há também uma verificação dos valores escritos como `R$`: eles precisam corresponder a preços ou ao orçamento de consultas bem-sucedidas do turno. Uma resposta sem respaldo é solicitada novamente e, se não puder ser corrigida dentro do limite, o turno termina com erro. Essa barreira não valida toda a semântica da resposta nem todas as formas de escrever valores.

Respostas geradas sem consulta bem-sucedida passam por uma classificação curta de escopo e respaldo no mesmo modelo, com saída JSON restrita. Ela permite conversa breve e explicações de limitações e substitui conhecimentos gerais ou afirmações comerciais sem consulta por um redirecionamento ao atendimento disponível. Essa etapa adiciona uma inferência nesses casos e também está sujeita a erros do classificador; não garante filtragem de todos os pedidos mistos ou adversariais.

A interface apresenta a conversa sem expor chamadas de ferramentas, argumentos, IDs internos ou resultados brutos. O histórico técnico permanece na memória da sessão para sustentar as consultas e referências entre turnos; **Nova conversa** limpa os dois históricos. Para diagnóstico e demonstração técnica, `python -m emporio.check_agent` imprime as chamadas no terminal. Saudações simples recebem uma resposta curta predefinida, sem solicitar nome nem chamar o modelo.

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

- **Disponibilidade:** produtos com status `active` ou `discontinued` e estoque positivo aparecem na busca padrão. Interpretamos a descontinuação como saída de linha, permitindo vender o saldo existente; o status é preservado para informar essa condição sem prometer reposição. Produtos sem estoque e lançamentos (`coming_soon`) permanecem indisponíveis. `get_product()` também retorna indisponíveis para permitir explicar seu status; `available_only=False` permite incluí-los nas buscas.
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
| Execução de ferramentas controlada pelo Python | Restringe a execução a funções registradas, valida tipos e IDs e limita repetições. Preços continuam sendo calculados pela camada de catálogo. |
| Streamlit e histórico por sessão | Permitem demonstrar conversas em Python sem implementar persistência de mensagens nesta versão. |
| SQLite gerado dos CSVs | Preserva relações e permite consultas parametrizadas sem servidor ou dependência de banco adicional. Os CSVs permanecem como fonte reproduzível. |
| Preços calculados em Python | Evitam coerção monetária para ponto flutuante. Após os filtros SQL de texto, categoria e disponibilidade, preço, ordenação e limite são aplicados em Python; essa abordagem é adequada ao snapshot de 65 produtos. |
| Biblioteca padrão para dados e testes | `csv`, `sqlite3`, `Decimal` e `unittest` atendem ao recorte atual sem novas dependências. |

Referências: [SDK Python do Ollama](https://github.com/ollama/ollama-python), [chamadas de ferramentas](https://docs.ollama.com/capabilities/tool-calling), [modelo utilizado](https://ollama.com/library/qwen3:4b-instruct) e [Streamlit](https://docs.streamlit.io/).

## Organização e fontes

```text
app.py                    Interface Streamlit
emporio/
  agent.py                Persona, ciclo de ferramentas e referências entre turnos
  tools.py                Esquemas, validação e adaptação das consultas para o modelo
  config.py               Configuração do modelo
  llm.py                  Adaptador do Ollama e tratamento de erros
  check_ollama.py          Diagnóstico real do modelo e de ferramenta
  check_agent.py           Cenários de catálogo com o modelo real
  database.py              Esquema SQLite, conexão e conversão monetária
  import_data.py           Importação e validação dos CSVs
  catalog.py               Consultas e regras do catálogo
data/raw/                 CSVs de catálogo fornecidos no desafio
tests/                    Testes de dados, agente e interface
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

A suíte cobre importação, rollback, disponibilidade, descontos, arredondamento, orçamento, chamadas de ferramentas, rejeição de IDs inventados, limites de execução, atualização de preço entre turnos, referências ordinais e ausência de raciocínio interno no histórico. Os testes da interface verificam que consultas técnicas não são exibidas, que o histórico interno é preservado e que isolamento, limpeza e recuperação após erro funcionam. Os bancos de teste são temporários; o agente usa respostas controladas do SDK e a interface usa `AppTest` do Streamlit.

O comando `python -m emporio.check_ollama` verifica separadamente a integração real com o modelo: frase em português, chamada `somar(17, 25)`, execução Python e uso do resultado `42` na resposta final. Ele não avalia a qualidade comercial do agente nem a seleção entre ferramentas de atendimento.

Com o banco preparado e o Ollama em execução, rode os cenários comerciais:

```powershell
.\.venv\Scripts\python.exe -m emporio.check_agent
```

O comando exercita saudação, categorias, violões com orçamento, continuação por posição, promoção, produto esgotado com alternativas, descontinuado com saldo, pergunta fora do escopo e informação ainda não integrada. Imprime respostas e chamadas e retorna código 1 se uma condição verificada falhar. Os valores esperados correspondem ao snapshot incluído no repositório. A avaliação verifica condições específicas; não substitui revisão qualitativa das respostas nem garante que todas as afirmações estejam corretas em outras conversas.

## Limitações e continuidade

- Recuperação de políticas, consultas a pedidos e exemplos finais de atendimento ainda estão pendentes.
- As restrições do prompt e a barreira de preços não garantem ausência de alucinações ou resistência a prompt injection. Associações entre nome e preço, afirmações de estoque, interpretação de características e redação ainda dependem do modelo e precisam de avaliação ampliada.
- O histórico não tem persistência, truncamento ou resumo automático. Conversas longas podem exceder o contexto do modelo.
- Não há autenticação, registro de reclamações ou integração com WhatsApp. O aplicativo é um protótipo local.

Com mais tempo: comparar modelos, medir qualidade e latência em cenários representativos, ampliar recuperação e avaliação e implementar identificação adequada para consultas de pedidos.

## Uso de IA

Foi utilizado **Codex** para análise das fontes, discussão de alternativas, implementação e auxílio na validação. As escolhas de execução local gratuita, Streamlit, SDK direto, SQLite e desenvolvimento em entregas incrementais foram discutidas com a pessoa candidata. As alterações são revisadas e commitadas pela pessoa candidata.

A entrega final deve conter um repositório público com histórico incremental, este README atualizado e entre 3 e 5 conversas de exemplo, incluindo um cenário não trivial. Os exemplos serão produzidos com as ferramentas comerciais funcionando.
