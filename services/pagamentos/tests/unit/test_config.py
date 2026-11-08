from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from pagamentos.config import Config
from plataforma.testes.tokens import SEGREDO_SERVICO_TESTE

URLS_DE_PRODUCAO: dict[str, Any] = {
    "database_url": "postgresql+asyncpg://u:s@db:5432/pagamentos",
    "rabbitmq_url": "amqp://u:s@rabbitmq:5672/",
    "jwks_url": "https://identidade.exemplo/.well-known/jwks.json",
    "pedidos_url": "https://pedidos.exemplo",
}


def _producao(**urls: Any) -> Config:
    return Config(
        token_servico_segredo=SecretStr(SEGREDO_SERVICO_TESTE), ambiente="producao", **urls
    )


def test_producao_sobe_com_todas_as_urls_explicitas() -> None:
    assert _producao(**URLS_DE_PRODUCAO).pedidos_url == "https://pedidos.exemplo"


def test_producao_exige_a_url_de_pedidos_explicita() -> None:
    urls = {campo: valor for campo, valor in URLS_DE_PRODUCAO.items() if campo != "pedidos_url"}
    with pytest.raises(ValidationError, match="PEDIDOS_URL"):
        _producao(**urls)
