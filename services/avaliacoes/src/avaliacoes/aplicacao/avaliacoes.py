"""Casos de uso de avaliações (camada de entidade)."""

import uuid
from dataclasses import dataclass

from avaliacoes.aplicacao.eventos import AVALIACAO_REGISTRADA, dados_avaliacao_registrada
from avaliacoes.aplicacao.portas import (
    FabricaUnidadeDeTrabalho,
    PortaPedidos,
    Relogio,
    ResumoAvaliacoes,
    Solicitante,
)
from avaliacoes.dominio.avaliacao import Avaliacao, exigir_pedido_avaliavel
from avaliacoes.dominio.erros import AvaliacaoNaoEncontrada, PedidoInexistente
from plataforma.logs import obter_logger
from plataforma.tempo import agora_utc

_log = obter_logger(__name__)


@dataclass(frozen=True, slots=True)
class ComandoRegistrarAvaliacao:
    pedido_id: str
    nota_restaurante: int
    nota_entrega: int | None = None
    comentario: str | None = None


class RegistrarAvaliacao:
    def __init__(
        self,
        uow: FabricaUnidadeDeTrabalho,
        pedidos: PortaPedidos,
        *,
        relogio: Relogio = agora_utc,
    ) -> None:
        self._uow = uow
        self._pedidos = pedidos
        self._relogio = relogio

    async def executar(
        self, comando: ComandoRegistrarAvaliacao, solicitante: Solicitante
    ) -> Avaliacao:
        pedido = await self._pedidos.obter(comando.pedido_id, token=solicitante.token)
        if pedido is None:
            raise PedidoInexistente()
        exigir_pedido_avaliavel(
            cliente_do_pedido=pedido.cliente_id,
            entregue=pedido.entregue,
            cliente_id=solicitante.id,
        )
        avaliacao = Avaliacao.registrar(
            pedido_id=pedido.id,
            cliente_id=solicitante.id,
            restaurante_id=pedido.restaurante_id,
            nota_restaurante=comando.nota_restaurante,
            nota_entrega=comando.nota_entrega,
            comentario=comando.comentario,
            agora=self._relogio(),
        )
        async with self._uow() as uow:
            await uow.avaliacoes.adicionar(avaliacao)
            uow.registrar_evento(AVALIACAO_REGISTRADA, dados_avaliacao_registrada(avaliacao))
            await uow.commit()
        _log.info(
            "avaliacao_registrada",
            avaliacao_id=str(avaliacao.id),
            pedido_id=avaliacao.pedido_id,
            restaurante_id=avaliacao.restaurante_id,
        )
        return avaliacao


class ConsultarAvaliacoes:
    def __init__(self, uow: FabricaUnidadeDeTrabalho) -> None:
        self._uow = uow

    async def obter(self, avaliacao_id: uuid.UUID) -> Avaliacao:
        async with self._uow() as uow:
            avaliacao = await uow.avaliacoes.obter(avaliacao_id)
        if avaliacao is None:
            raise AvaliacaoNaoEncontrada()
        return avaliacao

    async def listar(
        self,
        *,
        restaurante_id: str | None,
        pedido_id: str | None,
        deslocamento: int,
        limite: int,
    ) -> tuple[list[Avaliacao], int]:
        async with self._uow() as uow:
            return await uow.avaliacoes.listar(
                restaurante_id=restaurante_id,
                pedido_id=pedido_id,
                deslocamento=deslocamento,
                limite=limite,
            )

    async def resumir(self, restaurante_id: str) -> ResumoAvaliacoes:
        async with self._uow() as uow:
            return await uow.avaliacoes.resumir(restaurante_id)
