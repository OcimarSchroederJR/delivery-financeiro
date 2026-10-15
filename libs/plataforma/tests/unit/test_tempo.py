from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import BaseModel

from plataforma.tempo import DataHoraUTC, agora_utc, para_iso_utc


def test_para_iso_utc_converte_para_z() -> None:
    momento = datetime(2026, 10, 14, 11, 30, tzinfo=timezone(timedelta(hours=-3)))
    assert para_iso_utc(momento) == "2026-10-14T14:30:00Z"


def test_para_iso_utc_rejeita_datetime_sem_fuso() -> None:
    with pytest.raises(ValueError, match="sem fuso"):
        para_iso_utc(datetime(2026, 10, 14, 14, 30))  # noqa: DTZ001


def test_agora_utc_tem_fuso() -> None:
    assert agora_utc().tzinfo is UTC


def test_data_hora_utc_serializa_em_json_com_z() -> None:
    class Modelo(BaseModel):
        quando: DataHoraUTC

    modelo = Modelo(quando=datetime(2026, 10, 14, 14, 30, 5, 999, tzinfo=UTC))
    assert modelo.model_dump(mode="json") == {"quando": "2026-10-14T14:30:05Z"}
