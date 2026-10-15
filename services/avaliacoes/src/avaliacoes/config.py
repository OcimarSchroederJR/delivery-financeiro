"""Configuração do serviço de Avaliações (variáveis de ambiente)."""

from plataforma.config import ConfiguracaoBase


class Config(ConfiguracaoBase):
    servico: str = "avaliacoes"
    pedidos_url: str = "http://localhost:8008"
    pagamentos_url: str = "http://localhost:8013"
