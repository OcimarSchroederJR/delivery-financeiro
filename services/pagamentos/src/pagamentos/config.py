"""Configuração do serviço de Pagamentos (variáveis de ambiente)."""

from plataforma.config import ConfiguracaoBase


class Config(ConfiguracaoBase):
    servico: str = "pagamentos"
    pedidos_url: str = "http://localhost:8008"
