"""Casos de uso de disputas: abrir, consultar e decidir (inicia a saga)."""

import uuid
from dataclasses import dataclass

from avaliacoes.aplicacao.eventos import (
    DISPUTA_ABERTA,
    DISPUTA_RESOLVIDA,
    dados_disputa_aberta,
    dados_disputa_resolvida,
)
from avaliacoes.aplicacao.portas import (
    FabricaUnidadeDeTrabalho,
    PortaPagamentos,
    Relogio,
    Solicitante,
)
from avaliacoes.aplicacao.saga import SagaEstorno
from avaliacoes.dominio.disputa import (
    STATUS_PAGAMENTO_CONTESTAVEIS,
    Decisao,
    Disputa,
    MotivoDisputa,
    StatusDisputa,
)
from avaliacoes.dominio.erros import (
    DisputaDeOutroCliente,
    DisputaJaAberta,
    DisputaNaoEncontrada,
    PagamentoNaoEncontrado,
    PedidoDeOutroCliente,
)
from plataforma.logs import obter_logger
from plataforma.tempo import agora_utc

_log = obter_logger(__name__)


@dataclass(frozen=True, slots=True)
class ComandoAbrirDisputa:
    pedido_id: str
    motivo: MotivoDisputa
    valor_solicitado_centavos: int
    descricao: str | None = None


@dataclass(frozen=True, slots=True)
class ComandoDecidirDisputa:
    decisao: Decisao
    valor_aprovado_centavos: int | None = None
    parecer: str | None = None


class AbrirDisputa:
    def __init__(
        self,
        uow: FabricaUnidadeDeTrabalho,
        pagamentos: PortaPagamentos,
        *,
        relogio: Relogio = agora_utc,
    ) -> None:
        self._uow = uow
        self._pagamentos = pagamentos
        self._relogio = relogio

    async def executar(self, comando: ComandoAbrirDisputa, solicitante: Solicitante) -> Disputa:
        pagamentos = await self._pagamentos.listar_por_pedido(
            comando.pedido_id, token=solicitante.token
        )
        pagamento = next((p for p in pagamentos if p.status in STATUS_PAGAMENTO_CONTESTAVEIS), None)
        if pagamento is None:
            raise PagamentoNaoEncontrado()
        if pagamento.cliente_id != solicitante.id:
            raise PedidoDeOutroCliente()
        disputa = Disputa.abrir(
            pedido_id=comando.pedido_id,
            pagamento_id=pagamento.id,
            cliente_id=solicitante.id,
            motivo=comando.motivo,
            descricao=comando.descricao,
            valor_solicitado_centavos=comando.valor_solicitado_centavos,
            valor_pago_centavos=pagamento.valor_centavos,
            agora=self._relogio(),
        )
        async with self._uow() as uow:
            if await uow.disputas.existe_nao_terminal(comando.pedido_id):
                raise DisputaJaAberta()
            await uow.disputas.adicionar(disputa)
            uow.registrar_evento(DISPUTA_ABERTA, dados_disputa_aberta(disputa))
            await uow.commit()
        _log.info("disputa_aberta", disputa_id=str(disputa.id), pedido_id=disputa.pedido_id)
        return disputa


class ConsultarDisputas:
    def __init__(self, uow: FabricaUnidadeDeTrabalho) -> None:
        self._uow = uow

    async def obter(self, disputa_id: uuid.UUID, solicitante: Solicitante) -> Disputa:
        async with self._uow() as uow:
            disputa = await uow.disputas.obter(disputa_id)
        if disputa is None:
            raise DisputaNaoEncontrada()
        if not solicitante.admin and disputa.cliente_id != solicitante.id:
            raise DisputaDeOutroCliente()
        return disputa

    async def listar(
        self,
        *,
        status: StatusDisputa | None,
        solicitante: Solicitante,
        deslocamento: int,
        limite: int,
    ) -> tuple[list[Disputa], int]:
        """O cliente vê só as suas; o admin vê todas."""
        async with self._uow() as uow:
            return await uow.disputas.listar(
                status=status,
                cliente_id=None if solicitante.admin else solicitante.id,
                deslocamento=deslocamento,
                limite=limite,
            )


class DecidirDisputa:
    """``PATCH /v1/disputas/{id}`` (admin). Procedente dispara a saga de estorno."""

    def __init__(
        self,
        uow: FabricaUnidadeDeTrabalho,
        saga: SagaEstorno,
        *,
        relogio: Relogio = agora_utc,
    ) -> None:
        self._uow = uow
        self._saga = saga
        self._relogio = relogio

    async def executar(self, disputa_id: uuid.UUID, comando: ComandoDecidirDisputa) -> Disputa:
        agora = self._relogio()
        async with self._uow() as uow:
            disputa = await uow.disputas.obter(disputa_id, para_atualizar=True)
            if disputa is None:
                raise DisputaNaoEncontrada()
            if comando.decisao is Decisao.IMPROCEDENTE:
                disputa.julgar_improcedente(
                    parecer=comando.parecer,
                    valor_aprovado_centavos=comando.valor_aprovado_centavos,
                    agora=agora,
                )
                await uow.disputas.salvar(disputa)
                uow.registrar_evento(DISPUTA_RESOLVIDA, dados_disputa_resolvida(disputa))
                await uow.commit()
                _log.info("disputa_improcedente", disputa_id=str(disputa.id))
                return disputa
            disputa.aprovar(
                valor_aprovado_centavos=comando.valor_aprovado_centavos,
                parecer=comando.parecer,
                agora=agora,
                primeira_tentativa_em=agora + self._saga.politica.atraso_inicial,
            )
            await uow.disputas.salvar(disputa)
            await uow.commit()
        _log.info(
            "disputa_procedente",
            disputa_id=str(disputa.id),
            valor_aprovado_centavos=disputa.valor_aprovado_centavos,
        )
        return await self._saga.tentar(disputa_id)
