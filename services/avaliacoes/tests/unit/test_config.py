from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from avaliacoes.config import Config
from plataforma.testes.tokens import SEGREDO_SERVICO_TESTE

URLS_DE_PRODUCAO: dict[str, Any] = {
    "database_url": "postgresql+asyncpg://u:s@db:5432/avaliacoes",
    "rabbitmq_url": "amqp://u:s@rabbitmq:5672/",
    "jwks_url": "https://identidade.exemplo/.well-known/jwks.json",
    "pedidos_url": "https://pedidos.exemplo",
    "pagamentos_url": "http://pagamentos:8000",
}


def _producao(**urls: Any) -> Config:
    return Config(
        token_servico_segredo=SecretStr(SEGREDO_SERVICO_TESTE), ambiente="producao", **urls
    )


def test_producao_sobe_com_todas_as_urls_explicitas() -> None:
    assert _producao(**URLS_DE_PRODUCAO).pagamentos_url == "http://pagamentos:8000"


@pytest.mark.parametrize("ausente", ["pedidos_url", "pagamentos_url"])
def test_producao_exige_as_urls_das_dependencias_explicitas(ausente: str) -> None:
    urls = {campo: valor for campo, valor in URLS_DE_PRODUCAO.items() if campo != ausente}
    with pytest.raises(ValidationError, match=ausente.upper()):
        _producao(**urls)
