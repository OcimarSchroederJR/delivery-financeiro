"""Configuração do serviço de Pagamentos (variáveis de ambiente)."""

from typing import ClassVar

from pydantic import Field

from plataforma.config import ConfiguracaoBase


class Config(ConfiguracaoBase):
    CAMPOS_EXPLICITOS_EM_PRODUCAO: ClassVar[tuple[str, ...]] = (
        *ConfiguracaoBase.CAMPOS_EXPLICITOS_EM_PRODUCAO,
        "pedidos_url",
    )

    servico: str = "pagamentos"
    pedidos_url: str = "http://localhost:8008"
    gateway_atraso_timeout_segundos: float = Field(default=3.0, ge=0)
    idempotencia_limpeza_intervalo_segundos: float = Field(default=3600.0, gt=0)
