"""Raiz de composição: liga as portas aos adaptadores reais (usada pela API e pelo worker)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from avaliacoes.adaptadores.clientes.pagamentos import PagamentosHttp
from avaliacoes.adaptadores.clientes.pedidos import PedidosHttp
from avaliacoes.adaptadores.db.unidade_de_trabalho import fabrica_uow_sql
from avaliacoes.aplicacao.portas import (
    EmissorDeToken,
    FabricaUnidadeDeTrabalho,
    PortaPagamentos,
    PortaPedidos,
    Relogio,
)
from avaliacoes.aplicacao.saga import PoliticaDeRetentativa, SagaEstorno
from avaliacoes.config import Config
from plataforma.auth import EmissorTokenServico
from plataforma.cliente_http import ClienteHttp
from plataforma.tempo import agora_utc


@dataclass(frozen=True, slots=True)
class Dependencias:
    uow: FabricaUnidadeDeTrabalho
    pedidos: PortaPedidos
    pagamentos: PortaPagamentos
    emissor_token: EmissorDeToken
    politica: PoliticaDeRetentativa
    relogio: Relogio = agora_utc

    def saga(self) -> SagaEstorno:
        return SagaEstorno(
            self.uow,
            self.pagamentos,
            self.emissor_token,
            politica=self.politica,
            relogio=self.relogio,
        )


def politica_da_config(config: Config) -> PoliticaDeRetentativa:
    return PoliticaDeRetentativa(
        max_tentativas=config.saga_max_tentativas,
        espera_base=timedelta(seconds=config.saga_espera_base_segundos),
        espera_maxima=timedelta(seconds=config.saga_espera_maxima_segundos),
        atraso_inicial=timedelta(seconds=config.saga_atraso_inicial_segundos),
        reserva=timedelta(seconds=config.saga_reserva_segundos),
    )


@asynccontextmanager
async def dependencias_reais(
    config: Config, fabrica_sessoes: async_sessionmaker[AsyncSession]
) -> AsyncIterator[Dependencias]:
    """Um ``ClienteHttp`` (com seu circuit breaker) por dependência, fechado no fim."""
    async with (
        ClienteHttp("pedidos", config.pedidos_url, timeout=config.timeout_http()) as pedidos,
        ClienteHttp(
            "pagamentos", config.pagamentos_url, timeout=config.timeout_http()
        ) as pagamentos,
    ):
        yield Dependencias(
            uow=fabrica_uow_sql(fabrica_sessoes),
            pedidos=PedidosHttp(pedidos),
            pagamentos=PagamentosHttp(pagamentos),
            emissor_token=EmissorTokenServico(
                config.token_servico_segredo.get_secret_value(), servico=config.servico
            ),
            politica=politica_da_config(config),
        )
