"""Datas e horas: sempre UTC, serializadas em ISO 8601 com sufixo Z."""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AwareDatetime, PlainSerializer


def agora_utc() -> datetime:
    """Momento atual com fuso UTC."""
    return datetime.now(UTC)


def para_iso_utc(momento: datetime) -> str:
    """Formata como ``2026-10-14T14:30:00Z``. Rejeita datetime sem fuso."""
    if momento.tzinfo is None:
        raise ValueError("datetime sem fuso horário não pode ser serializado")
    return momento.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


DataHoraUTC = Annotated[
    AwareDatetime,
    PlainSerializer(para_iso_utc, return_type=str, when_used="json"),
]
"""Tipo para campos de data/hora em schemas Pydantic (entrada exige fuso; saída em Z)."""
