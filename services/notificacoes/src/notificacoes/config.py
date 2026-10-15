"""Configuração do serviço de Notificações (variáveis de ambiente)."""

from typing import Annotated, Self

from pydantic import Field, SecretStr, model_validator

from notificacoes.aplicacao.solicitante import PoliticaDeUrl
from plataforma.config import ConfiguracaoBase

TTLS_RETRY_PADRAO_MS = (1_000, 5_000, 30_000, 120_000, 600_000)

TtlMs = Annotated[int, Field(gt=0, le=3_600_000)]


class Config(ConfiguracaoBase):
    servico: str = "notificacoes"

    identidade_url: str = "http://localhost:8001"
    identidade_credencial: SecretStr | None = None  # credencial de serviço da Eq. 1
    perfis_cache_ttl_segundos: float = Field(default=300.0, gt=0)

    smtp_host: str = "localhost"
    smtp_porta: int = 1025
    smtp_remetente: str = "notificacoes@financeiro-eq5.local"
    smtp_timeout_segundos: float = Field(default=5.0, gt=0)
    email_admin: str = "admin@financeiro-eq5.local"

    webhook_timeout_segundos: float = Field(default=5.0, gt=0)
    webhook_segredo_cifragem: Annotated[SecretStr, Field(min_length=32)] | None = None

    fila_retry_ttls_ms: Annotated[tuple[TtlMs, ...], Field(min_length=1, max_length=10)] = (
        TTLS_RETRY_PADRAO_MS
    )
    relay_intervalo_segundos: float = Field(default=1.0, gt=0)
    consumidor_pausa_em_erro_segundos: float = Field(default=1.0, ge=0)

    @model_validator(mode="after")
    def exigir_chave_de_cifragem_em_producao(self) -> Self:
        if self.ambiente == "producao" and self.webhook_segredo_cifragem is None:
            raise ValueError("WEBHOOK_SEGREDO_CIFRAGEM é obrigatório em produção.")
        return self

    @property
    def max_retentativas(self) -> int:
        """Uma retentativa por fila de retry (spec: 5 filas)."""
        return len(self.fila_retry_ttls_ms)

    def segredo_de_cifragem(self) -> str:
        """Fora de produção, sem chave própria, deriva do segredo de serviço."""
        segredo = self.webhook_segredo_cifragem or self.token_servico_segredo
        return segredo.get_secret_value()

    def politica_de_url(self) -> PoliticaDeUrl:
        """https obrigatório e sem host interno, exceto em ``local`` e ``teste``."""
        local = self.ambiente != "producao"
        return PoliticaDeUrl(permitir_http=local, permitir_rede_interna=local)
