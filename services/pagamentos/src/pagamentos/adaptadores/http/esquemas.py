"""Schemas Pydantic de entrada e saída (contrato OpenAPI)."""

from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from pagamentos.aplicacao.criar_pagamento import ComandoCriarPagamento
from pagamentos.dominio.cartao import DadosCartao
from pagamentos.dominio.pagamento import Estorno, MetodoPagamento, Pagamento, StatusPagamento
from plataforma.tempo import DataHoraUTC

PADRAO_ID_EXTERNO = r"^[A-Za-z0-9_-]{1,64}$"


class CartaoEntrada(BaseModel):
    """Nunca persistido nem logado; só os 4 últimos dígitos são guardados."""

    model_config = ConfigDict(extra="forbid")

    numero: Annotated[
        str, Field(pattern=r"^[0-9]{13,19}$", repr=False, examples=["4111111111110000"])
    ]
    titular: Annotated[str, Field(min_length=1, max_length=100, repr=False)]
    validade: Annotated[
        str, Field(pattern=r"^(0[1-9]|1[0-2])/[0-9]{2}$", repr=False, examples=["12/28"])
    ]
    cvv: Annotated[str, Field(pattern=r"^[0-9]{3,4}$", repr=False, examples=["123"])]

    def para_dominio(self) -> DadosCartao:
        return DadosCartao(
            numero=self.numero, titular=self.titular, validade=self.validade, cvv=self.cvv
        )


class CriarPagamentoEntrada(BaseModel):
    """Não há campo de valor: ele vem da Eq. 3 (regra 1)."""

    model_config = ConfigDict(extra="forbid")

    pedido_id: Annotated[str, Field(pattern=PADRAO_ID_EXTERNO, examples=["ped-1"])]
    metodo: MetodoPagamento
    cartao: CartaoEntrada | None = None

    @model_validator(mode="after")
    def _exigir_cartao(self) -> Self:
        if self.metodo == MetodoPagamento.CARTAO_CREDITO and self.cartao is None:
            raise ValueError("o bloco 'cartao' é obrigatório quando metodo = cartao_credito")
        return self

    def para_comando(self) -> ComandoCriarPagamento:
        cartao = None
        if self.metodo == MetodoPagamento.CARTAO_CREDITO and self.cartao is not None:
            cartao = self.cartao.para_dominio()
        return ComandoCriarPagamento(pedido_id=self.pedido_id, metodo=self.metodo, cartao=cartao)

    def dados_idempotencia(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class EstornarEntrada(BaseModel):
    """Sem ``valor_centavos``, estorna o saldo estornável inteiro."""

    model_config = ConfigDict(extra="forbid")

    valor_centavos: Annotated[int, Field(strict=True, gt=0)] | None = Field(
        default=None, examples=[1000]
    )
    motivo: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ] = Field(examples=["disputa procedente"])

    def dados_idempotencia(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class EstornoSaida(BaseModel):
    id: UUID
    pagamento_id: UUID
    valor_centavos: int
    motivo: str
    criado_em: DataHoraUTC

    @classmethod
    def de_dominio(cls, estorno: Estorno) -> Self:
        return cls(
            id=estorno.id,
            pagamento_id=estorno.pagamento_id,
            valor_centavos=estorno.valor_centavos,
            motivo=estorno.motivo,
            criado_em=estorno.criado_em,
        )


class EstornoCriadoSaida(EstornoSaida):
    """Corpo do 201 do estorno. ``status`` é o status do pagamento após este estorno."""

    status: StatusPagamento

    @classmethod
    def de_estorno(cls, estorno: Estorno, status_pagamento: StatusPagamento) -> Self:
        return cls(
            id=estorno.id,
            pagamento_id=estorno.pagamento_id,
            valor_centavos=estorno.valor_centavos,
            motivo=estorno.motivo,
            criado_em=estorno.criado_em,
            status=status_pagamento,
        )


class PagamentoSaida(BaseModel):
    id: UUID
    pedido_id: str
    cliente_id: str
    valor_centavos: int
    metodo: MetodoPagamento
    status: StatusPagamento
    motivo_recusa: str | None
    cartao_final: str | None
    valor_estornado_centavos: int
    saldo_estornavel_centavos: int
    criado_em: DataHoraUTC
    atualizado_em: DataHoraUTC

    @classmethod
    def de_dominio(cls, pagamento: Pagamento) -> Self:
        return cls(
            id=pagamento.id,
            pedido_id=pagamento.pedido_id,
            cliente_id=pagamento.cliente_id,
            valor_centavos=pagamento.valor_centavos,
            metodo=pagamento.metodo,
            status=pagamento.status,
            motivo_recusa=pagamento.motivo_recusa,
            cartao_final=pagamento.cartao_final,
            valor_estornado_centavos=pagamento.valor_estornado_centavos,
            saldo_estornavel_centavos=pagamento.saldo_estornavel_centavos,
            criado_em=pagamento.criado_em,
            atualizado_em=pagamento.atualizado_em,
        )
