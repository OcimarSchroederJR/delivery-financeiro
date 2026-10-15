"""Schemas Pydantic de entrada e saída da API."""

import uuid
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from avaliacoes.aplicacao.portas import ResumoAvaliacoes
from avaliacoes.dominio.avaliacao import Avaliacao
from avaliacoes.dominio.disputa import Decisao, Disputa, MotivoDisputa, StatusDisputa
from plataforma.tempo import DataHoraUTC

IdExterno = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Nota = Annotated[int, Field(strict=True, ge=1, le=5)]


class AvaliacaoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pedido_id: IdExterno
    nota_restaurante: Nota
    nota_entrega: Nota | None = None
    comentario: Annotated[str, StringConstraints(max_length=1000)] | None = None


class AvaliacaoSaida(BaseModel):
    id: uuid.UUID
    pedido_id: str
    cliente_id: str
    restaurante_id: str
    nota_restaurante: int
    nota_entrega: int | None
    comentario: str | None
    criado_em: DataHoraUTC

    @classmethod
    def de(cls, avaliacao: Avaliacao) -> Self:
        return cls(
            id=avaliacao.id,
            pedido_id=avaliacao.pedido_id,
            cliente_id=avaliacao.cliente_id,
            restaurante_id=avaliacao.restaurante_id,
            nota_restaurante=avaliacao.nota_restaurante,
            nota_entrega=avaliacao.nota_entrega,
            comentario=avaliacao.comentario,
            criado_em=avaliacao.criado_em,
        )


class ResumoAvaliacoesSaida(BaseModel):
    restaurante_id: str
    media_restaurante: float | None
    media_entrega: float | None
    total: int

    @classmethod
    def de(cls, resumo: ResumoAvaliacoes) -> Self:
        return cls(
            restaurante_id=resumo.restaurante_id,
            media_restaurante=resumo.media_restaurante,
            media_entrega=resumo.media_entrega,
            total=resumo.total,
        )


class DisputaEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pedido_id: IdExterno
    motivo: MotivoDisputa
    descricao: Annotated[str, StringConstraints(max_length=2000)] | None = None
    valor_solicitado_centavos: Annotated[int, Field(strict=True, gt=0)]


class DecisaoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Decisao
    valor_aprovado_centavos: Annotated[int, Field(strict=True, ge=0)] | None = None
    parecer: Annotated[str, StringConstraints(max_length=2000)] | None = None


class DisputaSaida(BaseModel):
    id: uuid.UUID
    pedido_id: str
    pagamento_id: str
    cliente_id: str
    motivo: MotivoDisputa
    descricao: str | None
    valor_solicitado_centavos: int
    valor_aprovado_centavos: int | None
    status: StatusDisputa
    parecer: str | None
    estorno_id: str | None
    tentativas_estorno: int
    motivo_falha_estorno: str | None
    criado_em: DataHoraUTC
    atualizado_em: DataHoraUTC

    @classmethod
    def de(cls, disputa: Disputa) -> Self:
        return cls(
            id=disputa.id,
            pedido_id=disputa.pedido_id,
            pagamento_id=disputa.pagamento_id,
            cliente_id=disputa.cliente_id,
            motivo=disputa.motivo,
            descricao=disputa.descricao,
            valor_solicitado_centavos=disputa.valor_solicitado_centavos,
            valor_aprovado_centavos=disputa.valor_aprovado_centavos,
            status=disputa.status,
            parecer=disputa.parecer,
            estorno_id=disputa.estorno_id,
            tentativas_estorno=disputa.tentativas_estorno,
            motivo_falha_estorno=disputa.motivo_falha_estorno,
            criado_em=disputa.criado_em,
            atualizado_em=disputa.atualizado_em,
        )
