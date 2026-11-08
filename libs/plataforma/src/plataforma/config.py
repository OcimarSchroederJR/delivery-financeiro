"""Configuração base dos serviços, lida de variáveis de ambiente."""

from typing import ClassVar, Literal, Self

import httpx
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Valor padrão de TOKEN_SERVICO_SEGREDO nos compose locais: nunca pode chegar à produção.
SEGREDO_DE_DESENVOLVIMENTO = "segredo-local-financeiro-eq5-troque-em-producao"


class ConfiguracaoBase(BaseSettings):
    """Campos comuns aos 3 serviços. Cada serviço herda e acrescenta os seus.

    Os nomes das variáveis de ambiente são os nomes dos campos em maiúsculas
    (ex.: ``database_url`` lê ``DATABASE_URL``).
    """

    # Campos que, em produção, precisam vir do ambiente (ou do construtor), sem cair no
    # padrão de desenvolvimento. Cada serviço estende com as URLs das outras equipes.
    CAMPOS_EXPLICITOS_EM_PRODUCAO: ClassVar[tuple[str, ...]] = (
        "database_url",
        "rabbitmq_url",
        "jwks_url",
    )

    # hide_input_in_errors: o erro de boot vai para o log e não pode carregar segredos.
    model_config = SettingsConfigDict(extra="ignore", frozen=True, hide_input_in_errors=True)

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
    http_prazo_total: float = Field(default=8.0, gt=0)

    otel_habilitado: bool = False
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"

    @model_validator(mode="after")
    def _recusar_valores_de_desenvolvimento_em_producao(self) -> Self:
        if self.ambiente != "producao":
            return self
        if self.token_servico_segredo.get_secret_value() == SEGREDO_DE_DESENVOLVIMENTO:
            raise ValueError(
                "TOKEN_SERVICO_SEGREDO usa o valor padrão de desenvolvimento; "
                "defina um segredo próprio em produção."
            )
        ausentes = [
            campo.upper()
            for campo in self.CAMPOS_EXPLICITOS_EM_PRODUCAO
            if campo not in self.model_fields_set
        ]
        if ausentes:
            raise ValueError(f"Em produção, defina explicitamente: {', '.join(ausentes)}.")
        return self

    def timeout_http(self) -> httpx.Timeout:
        """Timeout padrão de toda chamada HTTP de saída (spec §5)."""
        return httpx.Timeout(
            self.http_timeout_leitura,
            connect=self.http_timeout_conexao,
        )
