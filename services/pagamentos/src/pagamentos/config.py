"""Configuração do serviço de Pagamentos (variáveis de ambiente)."""

from pydantic import Field

from plataforma.config import ConfiguracaoBase


class Config(ConfiguracaoBase):
    servico: str = "pagamentos"
    pedidos_url: str = "http://localhost:8008"
    gateway_atraso_timeout_segundos: float = Field(default=3.0, ge=0)
    idempotencia_limpeza_intervalo_segundos: float = Field(default=3600.0, gt=0)
