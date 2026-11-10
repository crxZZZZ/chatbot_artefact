# Empório da Música

Protótipo de agente de atendimento para o desafio técnico de AI Engineer da Artefact. O objetivo final é responder em português com a identidade da loja, consultar dados operacionais e políticas e lidar com perguntas fora do escopo.

## Estado atual — etapa 1

- Chat em Streamlit conectado ao Ollama pelo SDK oficial de Python.
- Modelo padrão `qwen3:4b-instruct`, executado localmente.
- Contexto mantido em memória durante a sessão e botão **Nova conversa**.
- Configuração por ambiente e mensagens de recuperação para serviço indisponível, modelo ausente e timeout.
- Verificação executável de conexão, resposta em português e chamada real de uma função Python.

**As consultas comerciais ainda não estão implementadas.** O assistente informa essa limitação e recebe instruções para não inventar preços, estoque, pedidos, contatos ou políticas. A ferramenta de soma existe somente no diagnóstico; não representa uma consulta aos dados da loja.

## Requisitos

- Python **3.12** (ambiente inicial: 3.12.3).
- [Ollama](https://ollama.com/download) instalado e em execução, com suporte a `tools` e ao parâmetro `think`.
- Modelo `qwen3:4b-instruct` baixado (aproximadamente 2,5 GB). A primeira instalação exige internet; a inferência usa o serviço local.
- Memória disponível para o modelo e seu contexto. O desempenho depende do hardware; veja os resultados de validação abaixo.

Não é necessária chave de API nem contratação de provedor. Os pesos e o runtime do modelo não são distribuídos no Git.

## Instalação e execução — Windows / PowerShell

Na raiz do repositório:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Os comandos usam diretamente o Python do ambiente virtual, dispensando alterações na política de execução do PowerShell. Copie `.env.example` apenas na primeira configuração, para preservar suas escolhas posteriores.

Abra o aplicativo Ollama. Como alternativa, mantenha um terminal separado executando:

```powershell
ollama serve
```

Com o serviço ativo, baixe o modelo se necessário:

```powershell
ollama pull qwen3:4b-instruct
```

Valide a integração e inicie a interface:

```powershell
.\.venv\Scripts\python.exe -m emporio.check_ollama
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Abra [http://localhost:8501](http://localhost:8501). Para encerrar o Streamlit, pressione `Ctrl+C` no terminal.

Em Linux/macOS, crie o mesmo ambiente com `python3 -m venv .venv`, use `.venv/bin/python` e copie a configuração com `cp .env.example .env`.

### Configuração

| Variável | Padrão | Finalidade |
| --- | --- | --- |
| `OLLAMA_HOST` | `http://localhost:11434` | URL HTTP do Ollama nesta máquina. |
| `OLLAMA_MODEL` | `qwen3:4b-instruct` | Modelo local a utilizar. |
| `OLLAMA_TIMEOUT_SECONDS` | `120` | Tempo de espera por requisição ao serviço. |

Variáveis já definidas no processo têm prioridade sobre `.env`. A aplicação aceita endereços de loopback e rejeita tags de nuvem; não faz fallback para APIs externas. Utilize somente modelos locais, inclusive se criar aliases no Ollama. O adaptador verifica a disponibilidade do modelo antes do atendimento. As requisições usam temperatura 0,7, `top_p=0.8`, contexto de 4.096 tokens, limite de 1.024 tokens de geração e `think=False`. Uma resposta interrompida pelo limite é tratada como erro, sem gravar conteúdo parcial.

O plano inicial partiu do `qwen3:4b` já instalado. Seus metadados identificaram a variante **Thinking-2507**, que iniciou raciocínio mesmo com `think=False`; com `think=True`, houve estouro do limite de 2.048 tokens no diagnóstico completo. Por isso, o padrão inicial passou a ser a variante **Instruct** de mesmo porte. Essa escolha prioriza uma resposta direta e uma validação de ferramentas viável para o protótipo. Veja a [variante utilizada](https://ollama.com/library/qwen3:4b-instruct). A qualidade comercial será avaliada nas próximas etapas.

Os parâmetros desta versão foram validados com a variante Instruct. Trocar `OLLAMA_MODEL` exige repetir o diagnóstico e pode exigir ajustes no adaptador, especialmente para modelos com raciocínio obrigatório.

### Recuperação de problemas

| Situação | Como resolver |
| --- | --- |
| Não conecta ao serviço | Abra o Ollama ou execute `ollama serve`; confira `OLLAMA_HOST`. |
| Modelo não encontrado | Execute `ollama pull qwen3:4b-instruct`, ou baixe o modelo configurado em `OLLAMA_MODEL`. |
| Tempo de espera excedido | Aguarde o carregamento inicial, tente novamente ou aumente `OLLAMA_TIMEOUT_SECONDS`. |
| Modelo sem ferramentas | Use um modelo local com suporte a chamadas de funções e repita o diagnóstico. |
| Porta já ocupada ao iniciar Ollama | Verifique se o aplicativo já está em execução; não é necessário iniciar um segundo servidor. |

No chat, uma falha não é gravada como resposta do agente nem adicionada ao histórico. A mensagem pode ser reenviada após a correção.

## Decisões técnicas

| Decisão | Justificativa e consequência |
| --- | --- |
| Python como linguagem principal | Restrição obrigatória do desafio; interface, integração e futuras ferramentas ficam na mesma linguagem. |
| Ollama local | Atende ao orçamento gratuito e mantém o conteúdo das conversas no ambiente local. Exige que o avaliador instale o runtime e baixe o modelo. |
| `qwen3:4b-instruct` | Mantém o porte de 4B com suporte a ferramentas. Escolhido após a variante Thinking instalada exceder o limite de geração na validação. |
| SDK oficial direto | Expõe o fluxo de mensagens e ferramentas sem acrescentar um framework de orquestração. Facilita explicar e testar as decisões do agente. |
| Streamlit | Permite demonstrar um chat em Python rapidamente. A camada de interface fica separada da integração e do comportamento do agente. |
| Histórico na sessão | Suporta continuidade de conversa sem persistir mensagens em banco ou arquivo. Nova conversa limpa o histórico; recarregar a página pode criar outra sessão. |
| Consultas comerciais em etapa posterior | Primeiro validamos a integração. Preços e regras serão fundamentados nas fontes fornecidas quando as ferramentas estiverem prontas. |

Referências: [SDK Python do Ollama](https://github.com/ollama/ollama-python), [chamadas de ferramentas](https://docs.ollama.com/capabilities/tool-calling), [Qwen3 no Ollama](https://ollama.com/library/qwen3), [Streamlit](https://docs.streamlit.io/).

### Organização

```text
app.py                    Interface Streamlit e estado da sessão
emporio/
  config.py               Leitura e validação da configuração
  llm.py                  Adaptador do SDK e tradução de erros
  agent.py                Persona e comportamento inicial
  check_ollama.py          Diagnóstico real do modelo e de ferramenta
.env.example              Configuração de exemplo
requirements.txt          Dependências com versões fixadas
```

## Fontes fornecidas no desafio

Inventário obtido pela leitura dos arquivos originais. Eles ainda não foram copiados para este repositório nem são carregados pela aplicação nesta etapa.

| Fonte | Quantidade | Uso previsto |
| --- | ---: | --- |
| `categories.csv` | 9 categorias | Classificação do catálogo. |
| `products.csv` | 65 produtos | Preços, descrição, estoque, status e especificações. |
| `promotions.csv` | 25 promoções | Descontos e indicação de atividade; 4 estão ativas. |
| `customers.csv` | 50 clientes | Associação com pedidos, com exposição mínima de dados pessoais. |
| `orders.csv` | 20 pedidos | Status, pagamento, rastreio e previsão de entrega. |
| `order_items.csv` | 22 itens | Associação entre pedidos e produtos. |
| `políticas_da_loja.pdf` | 8 páginas | Políticas e procedimentos, versão 2.1 de junho de 2025. |

Os nomes dos CSVs originais incluem o prefixo `desafio_tecnico_ai_eng - `. Não foram encontrados IDs duplicados nas cinco tabelas com chave própria nem referências órfãs entre tabelas. Há campos vazios de rastreio, previsão de entrega e observações. O catálogo inclui dois produtos descontinuados, um em lançamento e dois com estoque zero. Datas de pedidos vão de 2025-10-15 a 2026-03-22; o conteúdo é uma fotografia fornecida pelo exercício, não uma integração com uma loja real.

### Ambiguidades a tratar na próxima etapa

- **WhatsApp:** capa e dados da empresa trazem `(67) 3341-4444`; a seção 7 indica `(67) 3321-4500` como canal principal.
- **E-mail:** a capa usa `contato@emporiodamusica.com.br`; a tabela de dados inclui acento no domínio.
- **Parcelamento:** a tabela geral menciona parcela mínima de R$ 100, enquanto a seção 3.1 estabelece faixas e valores mínimos diferentes.
- **Frete local de exatamente R$ 500:** o texto distingue valores acima e abaixo desse limite e não define a igualdade.
- **Arrependimento e trocas:** há requisitos e exceções em seções diferentes; não vamos extrapolar sua aplicação quando faltarem informações da compra.

Essas divergências serão resolvidas por interpretação explícita ou encaminhamento para atendimento humano, com a decisão registrada antes da implementação das respectivas respostas. O manual é fonte de conhecimento do protótipo; suas instruções de atendimento não autorizam ações externas pelo assistente de desenvolvimento.

## Validação da etapa 1

O diagnóstico `python -m emporio.check_ollama` verifica o modelo local, pede uma frase em português, exige uma chamada `somar(17, 25)`, executa a função em Python, devolve o resultado ao modelo e verifica se a resposta final contém `42`. Uma falha encerra o comando com código 1. Os tempos são impressos por execução; eles não constituem um benchmark.

Validação em **09/11/2026**, com Python 3.12.3, Ollama 0.40.11, Windows, cerca de 32 GB de RAM e GPU NVIDIA GeForce RTX 3060 Ti com 8 GB de VRAM:

| Verificação | Resultado |
| --- | --- |
| Dependências fixadas e `pip check` | Instalação concluída, sem conflitos. O arquivo inclui dependências diretas e transitivas. |
| Sintaxe, UTF-8 e compilação | Seis arquivos Python verificados. |
| Diagnóstico real com `qwen3:4b-instruct` | Aprovado: frase em português, chamada correta, execução Python e resposta final com `42`. |
| Tempo observado no diagnóstico | 4,48 s no total; 1,75 s na saudação e 0,58 s no ciclo da ferramenta. Inclui chamadas locais; uma amostra, sem garantia de desempenho. |
| Interface com `AppTest` do Streamlit | Carregamento, histórico de múltiplos turnos, isolamento entre sessões, nova conversa, erro e reenvio verificados. |
| Chat com modelo real via `AppTest` | Nome do cliente recuperado entre turnos; perguntas sobre preço e devolução receberam aviso de consultas em construção. |
| Serviço indisponível e modelo ausente | Falhas reais convertidas em instruções para iniciar o serviço ou baixar o modelo. |
| Configuração inválida | Timeout inválido rejeitado; erro de configuração exibido sem traceback na interface. |
| Servidor da interface | HTTP 200 em `http://127.0.0.1:8501`. |

Os testes de erro/reenvio e isolamento da interface usaram respostas controladas para verificar o estado da sessão; o diagnóstico de ferramenta e as conversas indicadas como reais utilizaram o modelo local. Não foi adicionada uma suíte de testes de negócio nesta etapa. **A inspeção visual em navegador permanece pendente**, pois não havia navegador conectado disponível no ambiente de execução do assistente.

## Limitações e próximas etapas

- Sem leitura dos CSVs, recuperação do PDF ou ferramentas comerciais. As decisões de armazenamento e retrieval serão tomadas na etapa 2.
- A persona usa um prompt inicial com restrições explícitas. Isso não é uma garantia contra alucinações ou prompt injection; a fundamentação em ferramentas e a avaliação adversarial ainda estão pendentes.
- Histórico sem persistência e sem truncamento ou resumo automático: conversas longas podem exceder o contexto do modelo. Use **Nova conversa** para reiniciar.
- Sem autenticação, consultas a pedidos, registro de reclamações ou integração com WhatsApp. O protótipo é executado localmente.
- A ferramenta aritmética valida a mecânica de function calling, não a qualidade do atendimento ou a seleção entre várias ferramentas.
- Testes automatizados das regras de negócio e avaliação de respostas entram com as funcionalidades comerciais. Nesta etapa usamos diagnóstico real e verificação da interface.
- As 3 a 5 conversas finais de exemplo serão produzidas com o agente comercial funcionando. As verificações técnicas iniciais não serão apresentadas como exemplos finais do desafio.

Com mais tempo: avaliar modelos e estratégias de recuperação, ampliar casos adversariais, implementar identificação adequada para consultas de pedidos e medir qualidade, latência e rastreabilidade das respostas.

## Workflow e uso de IA

Foi utilizado **Codex** para ler o enunciado e as fontes, discutir alternativas, planejar etapas, implementar a base inicial e auxiliar na validação. A pessoa candidata participou das escolhas: execução gratuita local com Ollama, interface Streamlit, SDK direto e desenvolvimento em pequenas entregas. O código e as justificativas devem ser revisados e compreendidos pela pessoa candidata antes de cada commit.

O README será atualizado em cada etapa com as decisões efetivamente tomadas, os resultados e as limitações. Os commits ficam a cargo da pessoa candidata, preservando progresso real.

## Entregáveis do exercício

- [ ] Repositório público no GitHub com histórico incremental.
- [ ] Agente com consultas aos dados e às políticas, persona e tratamento de perguntas fora de escopo.
- [ ] README final com execução, justificativas, limitações e declaração do uso de IA.
- [ ] Entre 3 e 5 conversas de exemplo, incluindo uma situação não trivial.

Após revisar esta primeira etapa:

```powershell
git status --short
git add .
git diff --cached --stat
git diff --cached
git commit -m "chore: estrutura inicial e integração local com Ollama"
```

Antes da entrega, confira a data e o horário informados no e-mail do processo seletivo. O enunciado pede que o repositório não seja alterado após esse prazo.
