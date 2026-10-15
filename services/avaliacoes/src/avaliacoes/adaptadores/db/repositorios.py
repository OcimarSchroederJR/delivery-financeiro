"""Repositórios SQLAlchemy (implementam as portas de ``aplicacao.portas``)."""

import uuid
from datetime import datetime

from sqlalchemy import ColumnElement, exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from avaliacoes.adaptadores.db.modelos import AvaliacaoModelo, DisputaModelo
from avaliacoes.aplicacao.portas import ResumoAvaliacoes
from avaliacoes.dominio.avaliacao import Avaliacao
from avaliacoes.dominio.disputa import STATUS_NAO_TERMINAIS, Disputa, MotivoDisputa, StatusDisputa
from avaliacoes.dominio.erros import AvaliacaoDuplicada, DisputaJaAberta


def _avaliacao(modelo: AvaliacaoModelo) -> Avaliacao:
    return Avaliacao(
        id=modelo.id,
        pedido_id=modelo.pedido_id,
        cliente_id=modelo.cliente_id,
        restaurante_id=modelo.restaurante_id,
        nota_restaurante=modelo.nota_restaurante,
        nota_entrega=modelo.nota_entrega,
        comentario=modelo.comentario,
        criado_em=modelo.criado_em,
    )


def _media(valor: object) -> float | None:
    return None if valor is None else round(float(str(valor)), 2)


class RepositorioAvaliacoesSql:
    def __init__(self, sessao: AsyncSession) -> None:
        self._sessao = sessao

    async def adicionar(self, avaliacao: Avaliacao) -> None:
        self._sessao.add(
            AvaliacaoModelo(
                id=avaliacao.id,
                pedido_id=avaliacao.pedido_id,
                cliente_id=avaliacao.cliente_id,
                restaurante_id=avaliacao.restaurante_id,
                nota_restaurante=avaliacao.nota_restaurante,
                nota_entrega=avaliacao.nota_entrega,
                comentario=avaliacao.comentario,
                criado_em=avaliacao.criado_em,
            )
        )
        try:
            await self._sessao.flush()
        except IntegrityError as erro:  # uq_avaliacoes_pedido_id (inclusive sob concorrência)
            raise AvaliacaoDuplicada() from erro

    async def obter(self, avaliacao_id: uuid.UUID) -> Avaliacao | None:
        modelo = await self._sessao.get(AvaliacaoModelo, avaliacao_id)
        return None if modelo is None else _avaliacao(modelo)

    async def listar(
        self,
        *,
        restaurante_id: str | None,
        pedido_id: str | None,
        deslocamento: int,
        limite: int,
    ) -> tuple[list[Avaliacao], int]:
        filtros: list[ColumnElement[bool]] = []
        if restaurante_id is not None:
            filtros.append(AvaliacaoModelo.restaurante_id == restaurante_id)
        if pedido_id is not None:
            filtros.append(AvaliacaoModelo.pedido_id == pedido_id)
        total = await self._sessao.scalar(
            select(func.count()).select_from(AvaliacaoModelo).where(*filtros)
        )
        modelos = await self._sessao.scalars(
            select(AvaliacaoModelo)
            .where(*filtros)
            .order_by(AvaliacaoModelo.criado_em.desc(), AvaliacaoModelo.id.desc())
            .offset(deslocamento)
            .limit(limite)
        )
        return [_avaliacao(m) for m in modelos], int(total or 0)

    async def resumir(self, restaurante_id: str) -> ResumoAvaliacoes:
        linha = (
            await self._sessao.execute(
                select(
                    func.avg(AvaliacaoModelo.nota_restaurante),
                    func.avg(AvaliacaoModelo.nota_entrega),
                    func.count(),
                ).where(AvaliacaoModelo.restaurante_id == restaurante_id)
            )
        ).one()
        return ResumoAvaliacoes(
            restaurante_id=restaurante_id,
            media_restaurante=_media(linha[0]),
            media_entrega=_media(linha[1]),
            total=int(linha[2]),
        )


def _disputa(modelo: DisputaModelo) -> Disputa:
    return Disputa(
        id=modelo.id,
        pedido_id=modelo.pedido_id,
        pagamento_id=modelo.pagamento_id,
        cliente_id=modelo.cliente_id,
        motivo=MotivoDisputa(modelo.motivo),
        descricao=modelo.descricao,
        valor_solicitado_centavos=modelo.valor_solicitado_centavos,
        status=StatusDisputa(modelo.status),
        criado_em=modelo.criado_em,
        atualizado_em=modelo.atualizado_em,
        valor_aprovado_centavos=modelo.valor_aprovado_centavos,
        parecer=modelo.parecer,
        estorno_id=modelo.estorno_id,
        tentativas_estorno=modelo.tentativas_estorno,
        proxima_tentativa_em=modelo.proxima_tentativa_em,
        motivo_falha_estorno=modelo.motivo_falha_estorno,
    )


def _copiar(disputa: Disputa, modelo: DisputaModelo) -> DisputaModelo:
    modelo.id = disputa.id
    modelo.pedido_id = disputa.pedido_id
    modelo.pagamento_id = disputa.pagamento_id
    modelo.cliente_id = disputa.cliente_id
    modelo.motivo = disputa.motivo.value
    modelo.descricao = disputa.descricao
    modelo.valor_solicitado_centavos = disputa.valor_solicitado_centavos
    modelo.valor_aprovado_centavos = disputa.valor_aprovado_centavos
    modelo.status = disputa.status.value
    modelo.parecer = disputa.parecer
    modelo.estorno_id = disputa.estorno_id
    modelo.tentativas_estorno = disputa.tentativas_estorno
    modelo.proxima_tentativa_em = disputa.proxima_tentativa_em
    modelo.motivo_falha_estorno = disputa.motivo_falha_estorno
    modelo.criado_em = disputa.criado_em
    modelo.atualizado_em = disputa.atualizado_em
    return modelo


_NAO_TERMINAIS = [status.value for status in STATUS_NAO_TERMINAIS]


class RepositorioDisputasSql:
    def __init__(self, sessao: AsyncSession) -> None:
        self._sessao = sessao

    async def adicionar(self, disputa: Disputa) -> None:
        self._sessao.add(_copiar(disputa, DisputaModelo()))
        try:
            await self._sessao.flush()
        except IntegrityError as erro:  # ix_disputas_pedido_id_nao_terminal
            raise DisputaJaAberta() from erro

    async def obter(self, disputa_id: uuid.UUID, *, para_atualizar: bool = False) -> Disputa | None:
        consulta = select(DisputaModelo).where(DisputaModelo.id == disputa_id)
        if para_atualizar:
            consulta = consulta.with_for_update()
        modelo = await self._sessao.scalar(consulta.execution_options(populate_existing=True))
        return None if modelo is None else _disputa(modelo)

    async def salvar(self, disputa: Disputa) -> None:
        modelo = await self._sessao.get(DisputaModelo, disputa.id)
        if modelo is None:
            self._sessao.add(_copiar(disputa, DisputaModelo()))
        else:
            _copiar(disputa, modelo)
        await self._sessao.flush()

    async def existe_nao_terminal(self, pedido_id: str) -> bool:
        consulta = select(
            exists().where(
                DisputaModelo.pedido_id == pedido_id, DisputaModelo.status.in_(_NAO_TERMINAIS)
            )
        )
        return bool(await self._sessao.scalar(consulta))

    async def listar(
        self,
        *,
        status: StatusDisputa | None,
        cliente_id: str | None,
        deslocamento: int,
        limite: int,
    ) -> tuple[list[Disputa], int]:
        filtros: list[ColumnElement[bool]] = []
        if status is not None:
            filtros.append(DisputaModelo.status == status.value)
        if cliente_id is not None:
            filtros.append(DisputaModelo.cliente_id == cliente_id)
        total = await self._sessao.scalar(
            select(func.count()).select_from(DisputaModelo).where(*filtros)
        )
        modelos = await self._sessao.scalars(
            select(DisputaModelo)
            .where(*filtros)
            .order_by(DisputaModelo.criado_em.desc(), DisputaModelo.id.desc())
            .offset(deslocamento)
            .limit(limite)
        )
        return [_disputa(m) for m in modelos], int(total or 0)

    async def reservar_para_retentativa(
        self, *, agora: datetime, reservar_ate: datetime, limite: int
    ) -> list[uuid.UUID]:
        modelos = (
            await self._sessao.scalars(
                select(DisputaModelo)
                .where(
                    DisputaModelo.status == StatusDisputa.ESTORNO_PENDENTE.value,
                    DisputaModelo.proxima_tentativa_em <= agora,
                )
                .order_by(DisputaModelo.proxima_tentativa_em, DisputaModelo.id)
                .limit(limite)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for modelo in modelos:
            modelo.proxima_tentativa_em = reservar_ate
        await self._sessao.flush()
        return [modelo.id for modelo in modelos]
