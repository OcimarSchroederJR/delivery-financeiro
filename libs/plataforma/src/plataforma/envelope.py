"""Envelope padrão dos eventos (spec §3.5)."""

import uuid
from collections.abc import Mapping
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from plataforma.correlation import novo_correlation_id, obter_correlation_id
from plataforma.tempo import DataHoraUTC, agora_utc

PADRAO_TIPO_EVENTO = r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$"


class EnvelopeEvento(BaseModel):
    """``tipo`` = ``entidade.fato_no_passado`` e é também a routing key."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    mensagem_id: uuid.UUID
    tipo: Annotated[str, StringConstraints(pattern=PADRAO_TIPO_EVENTO, max_length=100)]
    versao: Annotated[int, Field(ge=1)] = 1
    ocorrido_em: DataHoraUTC
    correlation_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    dados: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def novo(
        cls,
        tipo: str,
        dados: Mapping[str, Any],
        *,
        versao: int = 1,
        correlation_id: str | None = None,
    ) -> Self:
        """Cria um envelope com id novo, ``ocorrido_em`` agora e o correlation id atual.

        ``dados`` deve conter apenas valores JSON (str, int, bool, None, listas, dicts);
        use ``str(uuid)`` e ``para_iso_utc(datetime)`` antes de montar.
        """
        return cls(
            mensagem_id=uuid.uuid4(),
            tipo=tipo,
            versao=versao,
            ocorrido_em=agora_utc(),
            correlation_id=correlation_id or obter_correlation_id() or novo_correlation_id(),
            dados=dict(dados),
        )

    def para_json(self) -> dict[str, Any]:
        """Forma serializável (UUID e datas como string) usada no outbox e no broker."""
        return self.model_dump(mode="json")
