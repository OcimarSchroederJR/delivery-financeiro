"""Schemas Pydantic de entrada e saída da API."""

import uuid
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from notificacoes.dominio.assinatura import AssinaturaWebhook
from notificacoes.dominio.entrega import EntregaWebhook
from notificacoes.dominio.notificacao import Notificacao
from plataforma.tempo import DataHoraUTC

Padrao = Annotated[str, StringConstraints(min_length=1, max_length=100)]


class EventoAceito(BaseModel):
    mensagem_id: uuid.UUID
    status: Literal["aceito", "duplicado"]


class AssinaturaEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: Annotated[str, StringConstraints(min_length=1, max_length=2048)] = Field(
        examples=["https://minha-equipe.exemplo.com/webhooks/financeiro"]
    )
    eventos: Annotated[list[Padrao], Field(min_length=1, max_length=20)] = Field(
        description="Padrões no estilo AMQP: * casa um segmento; # casa zero ou mais.",
        examples=[["pagamento.*", "disputa.resolvida"]],
    )


class AssinaturaSaida(BaseModel):
    id: uuid.UUID
    url: str
    eventos: list[str]
    ativa: bool
    criado_por: str
    somente_proprios: bool = Field(
        description="Assinaturas de não-admin só recebem eventos cujo cliente_id, "
        "restaurante_id ou entregador_id seja o próprio usuário."
    )
    criado_em: DataHoraUTC

    @classmethod
    def de(cls, assinatura: AssinaturaWebhook) -> Self:
        return cls(
            id=assinatura.id,
            url=assinatura.url,
            eventos=list(assinatura.eventos),
            ativa=assinatura.ativa,
            criado_por=assinatura.criado_por,
            somente_proprios=assinatura.somente_proprios,
            criado_em=assinatura.criado_em,
        )


class AssinaturaCriada(AssinaturaSaida):
    segredo: str = Field(
        description="Exibido só nesta resposta. Use-o para validar o header X-Assinatura: "
        'sha256=HMAC-SHA256(segredo, "<X-Assinatura-Timestamp>.<corpo>").'
    )

    @classmethod
    def com_segredo(cls, assinatura: AssinaturaWebhook) -> Self:
        return cls(**AssinaturaSaida.de(assinatura).model_dump(), segredo=assinatura.segredo)


class EntregaSaida(BaseModel):
    id: uuid.UUID
    assinatura_id: uuid.UUID
    mensagem_id: uuid.UUID
    tentativa: int
    status_http: int | None
    duracao_ms: int
    erro: str | None
    criado_em: DataHoraUTC

    @classmethod
    def de(cls, entrega: EntregaWebhook) -> Self:
        return cls(
            id=entrega.id,
            assinatura_id=entrega.assinatura_id,
            mensagem_id=entrega.mensagem_id,
            tentativa=entrega.tentativa,
            status_http=entrega.status_http,
            duracao_ms=entrega.duracao_ms,
            erro=entrega.erro,
            criado_em=entrega.criado_em,
        )


class NotificacaoSaida(BaseModel):
    id: uuid.UUID
    mensagem_id_origem: uuid.UUID
    tipo_evento: str
    canal: Literal["email", "webhook"]
    destino: str | None
    destinatario_id: str | None
    assinatura_id: uuid.UUID | None
    status: Literal["pendente", "enviada", "falhou"]
    tentativas: int
    ultimo_erro: str | None
    criado_em: DataHoraUTC
    enviada_em: DataHoraUTC | None

    @classmethod
    def de(cls, notificacao: Notificacao) -> Self:
        return cls(
            id=notificacao.id,
            mensagem_id_origem=notificacao.mensagem_id_origem,
            tipo_evento=notificacao.tipo_evento,
            canal=notificacao.canal.value,
            destino=notificacao.destino,
            destinatario_id=notificacao.destinatario_id,
            assinatura_id=notificacao.assinatura_id,
            status=notificacao.status.value,
            tentativas=notificacao.tentativas,
            ultimo_erro=notificacao.ultimo_erro,
            criado_em=notificacao.criado_em,
            enviada_em=notificacao.enviada_em,
        )
