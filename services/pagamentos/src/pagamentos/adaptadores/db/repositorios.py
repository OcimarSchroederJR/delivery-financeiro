"""Repositórios SQLAlchemy: implementam as portas de persistência da aplicação."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, delete, exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pagamentos.adaptadores.db.modelos import (
    INDICE_PEDIDO_EFETIVADO,
    ChaveIdempotenciaModelo,
    EstornoModelo,
    PagamentoModelo,
)
from pagamentos.dominio.erros import IdempotencyEmProcessamento, PedidoJaPago
from pagamentos.dominio.idempotencia import RegistroIdempotencia, StatusChave
from pagamentos.dominio.pagamento import Estorno, MetodoPagamento, Pagamento, StatusPagamento


def _constraint_violada(erro: IntegrityError) -> str | None:
    causa = getattr(erro.orig, "__cause__", None)  # asyncpg.UniqueViolationError
    nome = getattr(causa, "constraint_name", None)
    return nome if isinstance(nome, str) else None


def _estorno_para_modelo(estorno: Estorno) -> EstornoModelo:
    return EstornoModelo(
        id=estorno.id,
        pagamento_id=estorno.pagamento_id,
        valor_centavos=estorno.valor_centavos,
        motivo=estorno.motivo,
        criado_em=estorno.criado_em,
    )


def _para_modelo(pagamento: Pagamento) -> PagamentoModelo:
    return PagamentoModelo(
        id=pagamento.id,
        pedido_id=pagamento.pedido_id,
        cliente_id=pagamento.cliente_id,
        valor_centavos=pagamento.valor_centavos,
        metodo=pagamento.metodo.value,
        status=pagamento.status.value,
        motivo_recusa=pagamento.motivo_recusa,
        cartao_final=pagamento.cartao_final,
        criado_em=pagamento.criado_em,
        atualizado_em=pagamento.atualizado_em,
        estornos=[_estorno_para_modelo(e) for e in pagamento.estornos],
    )


def _para_dominio(modelo: PagamentoModelo) -> Pagamento:
    return Pagamento(
        id=modelo.id,
        pedido_id=modelo.pedido_id,
        cliente_id=modelo.cliente_id,
        valor_centavos=modelo.valor_centavos,
        metodo=MetodoPagamento(modelo.metodo),
        status=StatusPagamento(modelo.status),
        motivo_recusa=modelo.motivo_recusa,
        cartao_final=modelo.cartao_final,
        criado_em=modelo.criado_em,
        atualizado_em=modelo.atualizado_em,
        estornos=[
            Estorno(
                id=e.id,
                pagamento_id=e.pagamento_id,
                valor_centavos=e.valor_centavos,
                motivo=e.motivo,
                criado_em=e.criado_em,
            )
            for e in modelo.estornos
        ],
    )


class RepositorioPagamentosSql:
    def __init__(self, sessao: AsyncSession) -> None:
        self._sessao = sessao

    async def adicionar(self, pagamento: Pagamento) -> None:
        self._sessao.add(_para_modelo(pagamento))
        try:
            await self._sessao.flush()
        except IntegrityError as erro:
            if _constraint_violada(erro) == INDICE_PEDIDO_EFETIVADO:
                raise PedidoJaPago() from erro
            raise

    async def obter(self, pagamento_id: UUID, *, para_atualizar: bool = False) -> Pagamento | None:
        consulta = select(PagamentoModelo).where(PagamentoModelo.id == pagamento_id)
        if para_atualizar:
            consulta = consulta.with_for_update()
        modelo = (await self._sessao.scalars(consulta)).one_or_none()
        return None if modelo is None else _para_dominio(modelo)

    async def existe_efetivado(self, pedido_id: str) -> bool:
        consulta = select(
            exists().where(
                PagamentoModelo.pedido_id == pedido_id,
                PagamentoModelo.status != StatusPagamento.RECUSADO.value,
            )
        )
        return bool(await self._sessao.scalar(consulta))

    async def listar(
        self, *, pedido_id: str | None, cliente_id: str | None, deslocamento: int, limite: int
    ) -> tuple[list[Pagamento], int]:
        filtros: list[ColumnElement[bool]] = []
        if pedido_id is not None:
            filtros.append(PagamentoModelo.pedido_id == pedido_id)
        if cliente_id is not None:
            filtros.append(PagamentoModelo.cliente_id == cliente_id)
        total = await self._sessao.scalar(
            select(func.count()).select_from(PagamentoModelo).where(*filtros)
        )
        consulta = (
            select(PagamentoModelo)
            .where(*filtros)
            .order_by(PagamentoModelo.criado_em.desc(), PagamentoModelo.id.desc())
            .offset(deslocamento)
            .limit(limite)
        )
        modelos = (await self._sessao.scalars(consulta)).all()
        return [_para_dominio(m) for m in modelos], int(total or 0)

    async def salvar(self, pagamento: Pagamento) -> None:
        modelo = await self._sessao.get(PagamentoModelo, pagamento.id)
        if modelo is None:
            raise ValueError("salvar exige um pagamento já persistido")
        modelo.status = pagamento.status.value
        modelo.atualizado_em = pagamento.atualizado_em
        existentes = {e.id for e in modelo.estornos}
        for estorno in pagamento.estornos:
            if estorno.id not in existentes:
                modelo.estornos.append(_estorno_para_modelo(estorno))
        await self._sessao.flush()


def _registro(modelo: ChaveIdempotenciaModelo) -> RegistroIdempotencia:
    return RegistroIdempotencia(
        escopo=modelo.escopo,
        chave=modelo.chave,
        hash_requisicao=modelo.hash_requisicao,
        status=StatusChave(modelo.status),
        criado_em=modelo.criado_em,
        status_resposta=modelo.status_resposta,
        corpo_resposta=modelo.corpo_resposta,
    )


class RepositorioChavesIdempotenciaSql:
    def __init__(self, sessao: AsyncSession) -> None:
        self._sessao = sessao

    @staticmethod
    def _desta(escopo: str, chave: str) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
        return ChaveIdempotenciaModelo.escopo == escopo, ChaveIdempotenciaModelo.chave == chave

    async def obter(
        self, escopo: str, chave: str, *, para_atualizar: bool = False
    ) -> RegistroIdempotencia | None:
        consulta = select(ChaveIdempotenciaModelo).where(*self._desta(escopo, chave))
        if para_atualizar:
            consulta = consulta.with_for_update()
        modelo = (await self._sessao.scalars(consulta)).one_or_none()
        return None if modelo is None else _registro(modelo)

    async def reservar(self, registro: RegistroIdempotencia) -> None:
        self._sessao.add(
            ChaveIdempotenciaModelo(
                escopo=registro.escopo,
                chave=registro.chave,
                hash_requisicao=registro.hash_requisicao,
                status=registro.status.value,
                status_resposta=None,
                corpo_resposta=None,
                criado_em=registro.criado_em,
            )
        )
        try:
            await self._sessao.flush()
        except IntegrityError as erro:  # outra requisição reservou a mesma chave
            raise IdempotencyEmProcessamento() from erro

    async def substituir(self, registro: RegistroIdempotencia) -> None:
        await self._sessao.execute(
            update(ChaveIdempotenciaModelo)
            .where(*self._desta(registro.escopo, registro.chave))
            .values(
                hash_requisicao=registro.hash_requisicao,
                status=registro.status.value,
                status_resposta=None,
                corpo_resposta=None,
                criado_em=registro.criado_em,
            )
        )

    async def concluir(
        self, escopo: str, chave: str, *, status_resposta: int, corpo_resposta: Mapping[str, Any]
    ) -> None:
        await self._sessao.execute(
            update(ChaveIdempotenciaModelo)
            .where(
                *self._desta(escopo, chave),
                ChaveIdempotenciaModelo.status == StatusChave.EM_PROCESSAMENTO.value,
            )
            .values(
                status=StatusChave.CONCLUIDA.value,
                status_resposta=status_resposta,
                corpo_resposta=dict(corpo_resposta),
            )
        )

    async def remover(self, escopo: str, chave: str) -> None:
        await self._sessao.execute(
            delete(ChaveIdempotenciaModelo).where(
                *self._desta(escopo, chave),
                ChaveIdempotenciaModelo.status == StatusChave.EM_PROCESSAMENTO.value,
            )
        )

    async def remover_expiradas(self, antes_de: datetime) -> int:
        removidas = await self._sessao.scalars(
            delete(ChaveIdempotenciaModelo)
            .where(ChaveIdempotenciaModelo.criado_em < antes_de)
            .returning(ChaveIdempotenciaModelo.chave)
        )
        return len(removidas.all())
