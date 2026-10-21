"""Composição: monta os casos de uso a partir das portas concretas."""

import hashlib
from dataclasses import dataclass

from pagamentos.aplicacao.consultas import ConsultasPagamentos
from pagamentos.aplicacao.criar_pagamento import CriarPagamento
from pagamentos.aplicacao.estornar_pagamento import EstornarPagamento
from pagamentos.aplicacao.idempotencia import ExecutorIdempotente
from pagamentos.aplicacao.portas import (
    Apresentador,
    ConsultaPedidos,
    FabricaUnidadeDeTrabalho,
    GatewayDePagamento,
    Relogio,
)
from plataforma.tempo import agora_utc


@dataclass(frozen=True, slots=True)
class CasosDeUso:
    apresentador: Apresentador
    idempotencia: ExecutorIdempotente
    criar_pagamento: CriarPagamento
    estornar_pagamento: EstornarPagamento
    consultas: ConsultasPagamentos


def derivar_chave_hash(segredo: str) -> bytes:
    """Chave do HMAC da idempotência, separada do uso do segredo no token de serviço."""
    return hashlib.sha256(b"pagamentos.idempotencia:" + segredo.encode("utf-8")).digest()


def montar_casos_de_uso(
    *,
    fabrica_uow: FabricaUnidadeDeTrabalho,
    pedidos: ConsultaPedidos,
    gateway: GatewayDePagamento,
    apresentador: Apresentador,
    segredo: str,
    relogio: Relogio = agora_utc,
) -> CasosDeUso:
    return CasosDeUso(
        apresentador=apresentador,
        idempotencia=ExecutorIdempotente(
            fabrica_uow, apresentador, chave_hash=derivar_chave_hash(segredo), relogio=relogio
        ),
        criar_pagamento=CriarPagamento(
            fabrica_uow=fabrica_uow,
            pedidos=pedidos,
            gateway=gateway,
            apresentador=apresentador,
            relogio=relogio,
        ),
        estornar_pagamento=EstornarPagamento(
            fabrica_uow=fabrica_uow, apresentador=apresentador, relogio=relogio
        ),
        consultas=ConsultasPagamentos(fabrica_uow),
    )
