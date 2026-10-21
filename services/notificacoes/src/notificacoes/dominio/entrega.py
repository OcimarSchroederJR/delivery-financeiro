"""Registro de cada tentativa de entrega de um webhook."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Self


@dataclass(frozen=True, slots=True)
class EntregaWebhook:
    id: uuid.UUID
    assinatura_id: uuid.UUID
    mensagem_id: uuid.UUID
    tentativa: int
    status_http: int | None
    duracao_ms: int
    erro: str | None
    criado_em: datetime

    @classmethod
    def registrar(
        cls,
        *,
        assinatura_id: uuid.UUID,
        mensagem_id: uuid.UUID,
        tentativa: int,
        status_http: int | None,
        duracao_ms: int,
        erro: str | None,
        agora: datetime,
    ) -> Self:
        return cls(
            id=uuid.uuid4(),
            assinatura_id=assinatura_id,
            mensagem_id=mensagem_id,
            tentativa=tentativa,
            status_http=status_http,
            duracao_ms=duracao_ms,
            erro=erro,
            criado_em=agora,
        )
