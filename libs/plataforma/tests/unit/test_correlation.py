import uuid

import httpx
import pytest

from plataforma.correlation import (
    HEADER_CORRELATION_ID,
    correlation_id_em,
    definir_correlation_id,
    hook_httpx_correlation,
    normalizar_correlation_id,
    obter_correlation_id,
)


def test_normalizar_mantem_valor_seguro() -> None:
    assert normalizar_correlation_id("abc-123_X.y:z") == "abc-123_X.y:z"


@pytest.mark.parametrize("valor", [None, "", "a b", "x" * 129, "linha\nquebrada", "ç"])
def test_normalizar_troca_valor_inseguro_por_uuid(valor: str | None) -> None:
    resultado = normalizar_correlation_id(valor)
    assert resultado != valor
    uuid.UUID(resultado)


def test_correlation_id_em_restaura_valor_anterior() -> None:
    definir_correlation_id("externo")
    with correlation_id_em("interno") as atual:
        assert atual == "interno"
        assert obter_correlation_id() == "interno"
    assert obter_correlation_id() == "externo"


async def test_hook_httpx_propaga_correlation_id() -> None:
    definir_correlation_id("cid-1")
    requisicao = httpx.Request("GET", "http://x/")
    await hook_httpx_correlation(requisicao)
    assert requisicao.headers[HEADER_CORRELATION_ID] == "cid-1"


async def test_hook_httpx_nao_sobrescreve_header_existente() -> None:
    definir_correlation_id("cid-1")
    requisicao = httpx.Request("GET", "http://x/", headers={HEADER_CORRELATION_ID: "outro"})
    await hook_httpx_correlation(requisicao)
    assert requisicao.headers[HEADER_CORRELATION_ID] == "outro"
