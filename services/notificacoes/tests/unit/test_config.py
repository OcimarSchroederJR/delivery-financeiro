from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from notificacoes.aplicacao.solicitante import PoliticaDeUrl
from notificacoes.config import Config
from plataforma.testes.tokens import SEGREDO_SERVICO_TESTE


def _config(**mudancas: Any) -> Config:
    return Config(token_servico_segredo=SecretStr(SEGREDO_SERVICO_TESTE), **mudancas)


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
    with pytest.raises(ValidationError):
        _config(ambiente="producao")
    config = _config(ambiente="producao", webhook_segredo_cifragem=SecretStr("c" * 32))
    assert config.segredo_de_cifragem() == "c" * 32


def test_segredo_de_cifragem_fora_de_producao_usa_o_token_de_servico() -> None:
    assert _config().segredo_de_cifragem() == SEGREDO_SERVICO_TESTE


def test_politica_de_url_por_ambiente() -> None:
    assert _config().politica_de_url() == PoliticaDeUrl(True, True)
    producao = _config(ambiente="producao", webhook_segredo_cifragem=SecretStr("c" * 32))
    assert producao.politica_de_url() == PoliticaDeUrl(False, False)
