"""Configuração base dos serviços, lida de variáveis de ambiente."""

from typing import Literal

import httpx
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfiguracaoBase(BaseSettings):
    """Campos comuns aos 3 serviços. Cada serviço herda e acrescenta os seus.

    Os nomes das variáveis de ambiente são os nomes dos campos em maiúsculas
    (ex.: ``database_url`` lê ``DATABASE_URL``).
    """

    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    servico: str
    ambiente: Literal["local", "teste", "producao"] = "local"
    log_formato: Literal["json", "console"] = "console"
    log_nivel: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    root_path: str = ""

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"

    jwks_url: str = "http://localhost:8001/.well-known/jwks.json"
    jwks_ttl_segundos: float = Field(default=300.0, gt=0)
    jwt_claim_papel: str = "papel"
    jwt_emissor: str | None = None
    jwt_audiencia: str | None = None
    token_servico_segredo: SecretStr = Field(min_length=32)

    http_timeout_conexao: float = Field(default=1.0, gt=0)
    http_timeout_leitura: float = Field(default=3.0, gt=0)

    otel_habilitado: bool = False
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"

    def timeout_http(self) -> httpx.Timeout:
        """Timeout padrão de toda chamada HTTP de saída (spec §5)."""
        return httpx.Timeout(
            self.http_timeout_leitura,
            connect=self.http_timeout_conexao,
        )
