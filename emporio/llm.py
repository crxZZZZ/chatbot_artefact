"""Acesso ao Ollama pelo SDK oficial, sem fallback para serviços externos."""

from contextlib import contextmanager
from collections.abc import Iterator, Sequence
from typing import Any

import httpx
from ollama import ChatResponse, Client, ResponseError

from emporio.config import Settings


class OllamaUnavailableError(RuntimeError):
    """Falha recuperável que pode ser apresentada na interface ou no terminal."""


class OllamaService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = Client(host=settings.host, timeout=settings.timeout_seconds, trust_env=False)

    @contextmanager
    def _handle_errors(self) -> Iterator[None]:
        try:
            yield
        except httpx.ConnectTimeout as exc:
            raise OllamaUnavailableError(
                f"Não foi possível conectar ao Ollama em {self.settings.host}. "
                "Inicie o aplicativo Ollama ou execute 'ollama serve' em outro terminal."
            ) from exc
        except httpx.TimeoutException as exc:
            raise OllamaUnavailableError(
                "O Ollama excedeu o tempo de espera. O primeiro carregamento pode demorar. "
                "Tente novamente ou aumente OLLAMA_TIMEOUT_SECONDS no .env."
            ) from exc
        except (ConnectionError, httpx.RequestError) as exc:
            raise OllamaUnavailableError(
                f"Não foi possível conectar ao Ollama em {self.settings.host}. "
                "Inicie o aplicativo Ollama ou execute 'ollama serve' em outro terminal."
            ) from exc
        except ResponseError as exc:
            if exc.status_code == 404:
                message = (
                    f"Modelo '{self.settings.model}' não encontrado. "
                    f"Execute 'ollama pull {self.settings.model}' ou ajuste OLLAMA_MODEL no .env."
                )
            else:
                message = (
                    f"O Ollama retornou um erro (HTTP {exc.status_code}). "
                    "Confira o terminal do serviço e se há memória disponível; tente novamente."
                )
            raise OllamaUnavailableError(message) from exc

    def check_model(self) -> list[str]:
        with self._handle_errors():
            details = self.client.show(self.settings.model)
        return details.capabilities or []

    def chat(self, messages: Sequence[Any], tools: Sequence[Any] | None = None) -> ChatResponse:
        with self._handle_errors():
            response = self.client.chat(
                model=self.settings.model,
                messages=messages,
                tools=tools,
                stream=False,
                think=False,
                options={"temperature": 0.7, "top_p": 0.8, "num_ctx": 4096, "num_predict": 1024},
            )
        if response.done_reason == "length":
            raise OllamaUnavailableError(
                "O modelo atingiu o limite de geração antes de concluir. "
                "Inicie uma nova conversa e tente uma pergunta mais curta."
            )
        if not (response.message.content or "").strip() and not response.message.tool_calls:
            raise OllamaUnavailableError("O modelo retornou uma resposta vazia. Tente novamente e execute a verificação local.")
        return response
