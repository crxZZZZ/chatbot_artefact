"""Configuração compartilhada pela interface e pela verificação local."""

from dataclasses import dataclass
import math
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    host: str
    model: str
    timeout_seconds: float


def load_settings() -> Settings:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434").strip()
    model = os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct").strip()
    parsed = urlparse(host)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("OLLAMA_HOST deve ser uma URL HTTP local, como http://localhost:11434.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("A porta de OLLAMA_HOST é inválida.") from exc
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("OLLAMA_HOST deve conter somente o endereço local e a porta.")
    if port == 0:
        raise ValueError("A porta de OLLAMA_HOST deve ser maior que zero.")
    if not model or "cloud" in model.lower():
        raise ValueError("OLLAMA_MODEL deve identificar um modelo local, como qwen3:4b-instruct.")
    try:
        timeout = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))
    except ValueError as exc:
        raise ValueError("OLLAMA_TIMEOUT_SECONDS deve ser um número positivo.") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("OLLAMA_TIMEOUT_SECONDS deve ser um número positivo e finito.")
    return Settings(host=host.rstrip("/"), model=model, timeout_seconds=timeout)
