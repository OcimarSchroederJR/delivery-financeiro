from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from notificacoes.aplicacao.solicitante import PoliticaDeUrl
from notificacoes.config import Config
from plataforma.testes.tokens import SEGREDO_SERVICO_TESTE

# Em produção as URLs de infraestrutura e das outras equipes vêm sempre explícitas.
URLS_DE_PRODUCAO: dict[str, Any] = {
    "database_url": "postgresql+asyncpg://u:s@db:5432/notificacoes",
    "rabbitmq_url": "amqp://u:s@rabbitmq:5672/",
    "jwks_url": "https://identidade.exemplo/.well-known/jwks.json",
    "identidade_url": "https://identidade.exemplo",
}


def _config(**mudancas: Any) -> Config:
    return Config(token_servico_segredo=SecretStr(SEGREDO_SERVICO_TESTE), **mudancas)


def _producao(**mudancas: Any) -> Config:
    return _config(ambiente="producao", **URLS_DE_PRODUCAO, **mudancas)


def test_padroes_da_spec() -> None:
    config = _config()
    assert config.fila_retry_ttls_ms == (1000, 5000, 30000, 120000, 600000)
    assert config.max_retentativas == 5
    assert config.webhook_timeout_segundos == 5.0
    assert config.perfis_cache_ttl_segundos == 300.0
    assert config.identidade_credencial is None


def test_ttls_pelo_ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FILA_RETRY_TTLS_MS", "[100,100]")
    assert _config().fila_retry_ttls_ms == (100, 100)


@pytest.mark.parametrize("ttls", [(), (0,), tuple(range(1, 12))])
def test_ttls_invalidos(ttls: tuple[int, ...]) -> None:
    with pytest.raises(ValidationError):
        _config(fila_retry_ttls_ms=ttls)


def test_producao_exige_chave_de_cifragem() -> None:
    with pytest.raises(ValidationError, match="WEBHOOK_SEGREDO_CIFRAGEM"):
        _producao()
    config = _producao(webhook_segredo_cifragem=SecretStr("c" * 32))
    assert config.segredo_de_cifragem() == "c" * 32


def test_segredo_de_cifragem_fora_de_producao_usa_o_token_de_servico() -> None:
    assert _config().segredo_de_cifragem() == SEGREDO_SERVICO_TESTE


def test_politica_de_url_por_ambiente() -> None:
    assert _config().politica_de_url() == PoliticaDeUrl(True, True)
    producao = _producao(webhook_segredo_cifragem=SecretStr("c" * 32))
    assert producao.politica_de_url() == PoliticaDeUrl(False, False)


def test_prefetch_padrao_dos_consumidores() -> None:
    assert _config().consumidor_prefetch == 10
