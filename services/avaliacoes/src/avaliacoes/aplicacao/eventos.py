"""Eventos publicados pelo serviço (via outbox) e seus ``dados`` (spec §3.5)."""

from avaliacoes.aplicacao.portas import DadosEvento
from avaliacoes.dominio.avaliacao import Avaliacao
from avaliacoes.dominio.disputa import Disputa, StatusDisputa

AVALIACAO_REGISTRADA = "avaliacao.registrada"
DISPUTA_ABERTA = "disputa.aberta"
DISPUTA_RESOLVIDA = "disputa.resolvida"
DISPUTA_ESTORNO_FALHOU = "disputa.estorno_falhou"


def dados_avaliacao_registrada(avaliacao: Avaliacao) -> DadosEvento:
    return {
        "avaliacao_id": str(avaliacao.id),
        "pedido_id": avaliacao.pedido_id,
        "restaurante_id": avaliacao.restaurante_id,
        "cliente_id": avaliacao.cliente_id,
        "nota_restaurante": avaliacao.nota_restaurante,
        "nota_entrega": avaliacao.nota_entrega,
    }


def dados_disputa_aberta(disputa: Disputa) -> DadosEvento:
    return {
        "disputa_id": str(disputa.id),
        "pedido_id": disputa.pedido_id,
        "cliente_id": disputa.cliente_id,
        "motivo": disputa.motivo.value,
        "valor_solicitado_centavos": disputa.valor_solicitado_centavos,
    }


def dados_disputa_resolvida(disputa: Disputa) -> DadosEvento:
    """``resolvida`` → procedente com o valor estornado; ``improcedente`` → valor 0."""
    if disputa.status is StatusDisputa.RESOLVIDA:
        decisao, valor = "procedente", disputa.valor_aprovado_centavos
    elif disputa.status is StatusDisputa.IMPROCEDENTE:
        decisao, valor = "improcedente", 0
    else:
        raise ValueError(f"disputa.resolvida não se aplica ao status {disputa.status.value}")
    return {
        "disputa_id": str(disputa.id),
        "pedido_id": disputa.pedido_id,
        "cliente_id": disputa.cliente_id,
        "decisao": decisao,
        "valor_estornado_centavos": valor,
    }


def dados_disputa_estorno_falhou(disputa: Disputa) -> DadosEvento:
    if disputa.status is not StatusDisputa.ESTORNO_FALHOU:
        raise ValueError(f"disputa.estorno_falhou não se aplica ao status {disputa.status.value}")
    return {
        "disputa_id": str(disputa.id),
        "pedido_id": disputa.pedido_id,
        "motivo": disputa.motivo_falha_estorno,
    }
