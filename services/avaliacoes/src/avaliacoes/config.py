"""Configuração do serviço de Avaliações (variáveis de ambiente)."""

from pydantic import Field

from plataforma.config import ConfiguracaoBase


class Config(ConfiguracaoBase):
    servico: str = "avaliacoes"
    pedidos_url: str = "http://localhost:8008"
    pagamentos_url: str = "http://localhost:8013"

    # Saga de disputa (spec §4.3): retentativa do estorno pelo worker.
    saga_max_tentativas: int = Field(default=10, ge=1)
    saga_espera_base_segundos: float = Field(default=5.0, gt=0)
    saga_espera_maxima_segundos: float = Field(default=300.0, gt=0)
    saga_atraso_inicial_segundos: float = Field(default=30.0, ge=0)
    saga_reserva_segundos: float = Field(default=60.0, gt=0)
    worker_intervalo_segundos: float = Field(default=1.0, gt=0)
    worker_tamanho_lote: int = Field(default=10, ge=1)
