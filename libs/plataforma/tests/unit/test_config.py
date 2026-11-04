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


# --- Produção (spec §7.3): nada de valores de desenvolvimento -------------------------

SEGREDO_DE_DESENVOLVIMENTO = "segredo-local-financeiro-eq5-troque-em-producao"
URLS_DE_PRODUCAO = {
    "database_url": "postgresql+asyncpg://u:s@db:5432/x",
    "rabbitmq_url": "amqp://u:s@rabbitmq:5672/",
    "jwks_url": "https://identidade.exemplo/.well-known/jwks.json",
}


def test_producao_recusa_o_segredo_de_servico_de_desenvolvimento(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOKEN_SERVICO_SEGREDO", SEGREDO_DE_DESENVOLVIMENTO)
    with pytest.raises(ValidationError, match="TOKEN_SERVICO_SEGREDO") as erro:
        ConfiguracaoBase(servico="teste", ambiente="producao", **URLS_DE_PRODUCAO)
    assert SEGREDO_DE_DESENVOLVIMENTO not in str(erro.value)


def test_fora_de_producao_aceita_o_segredo_de_desenvolvimento() -> None:
    config = ConfiguracaoBase(
        servico="teste", token_servico_segredo=SecretStr(SEGREDO_DE_DESENVOLVIMENTO)
    )
    assert config.ambiente == "local"


def test_erro_de_configuracao_nao_expoe_os_valores_recebidos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # O erro de boot vai para o log; segredos e URLs com senha não podem aparecer nele.
    monkeypatch.setenv("TOKEN_SERVICO_SEGREDO", "segredo-curto-vazado")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:senha-do-banco@db:5432/x")
    with pytest.raises(ValidationError, match="token_servico_segredo") as erro:
        ConfiguracaoBase(servico="teste")
    assert "segredo-curto-vazado" not in str(erro.value)
    assert "senha-do-banco" not in str(erro.value)
