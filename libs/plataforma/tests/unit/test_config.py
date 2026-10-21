import pytest
from pydantic import SecretStr, ValidationError

from plataforma.config import ConfiguracaoBase

SEGREDO = "s" * 32


def test_config_le_variaveis_de_ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKEN_SERVICO_SEGREDO", SEGREDO)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:s@db:5432/x")
    monkeypatch.setenv("HTTP_TIMEOUT_LEITURA", "5")
    config = ConfiguracaoBase(servico="teste")
    assert config.database_url == "postgresql+asyncpg://u:s@db:5432/x"
    assert config.token_servico_segredo.get_secret_value() == SEGREDO
    timeout = config.timeout_http()
    assert (timeout.connect, timeout.read) == (1.0, 5.0)


def test_config_padroes_da_spec() -> None:
    config = ConfiguracaoBase(servico="teste", token_servico_segredo=SecretStr(SEGREDO))
    assert config.jwt_claim_papel == "papel"
    assert (config.http_timeout_conexao, config.http_timeout_leitura) == (1.0, 3.0)
    assert config.otel_habilitado is False


def test_config_exige_segredo_de_servico_com_32_caracteres() -> None:
    with pytest.raises(ValidationError):
        ConfiguracaoBase(servico="teste", token_servico_segredo=SecretStr("curto"))
