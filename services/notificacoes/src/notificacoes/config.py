"""Configuração do serviço de Notificações (variáveis de ambiente)."""

from plataforma.config import ConfiguracaoBase


class Config(ConfiguracaoBase):
    servico: str = "notificacoes"
    identidade_url: str = "http://localhost:8001"
    smtp_host: str = "localhost"
    smtp_porta: int = 1025
    smtp_remetente: str = "notificacoes@financeiro-eq5.local"
