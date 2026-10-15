import pytest

from notificacoes.dominio.erros import UrlDeWebhookInvalida
from notificacoes.dominio.url_webhook import validar_url_webhook


@pytest.mark.parametrize(
    "url", ["https://exemplo.com/webhook", "https://api.exemplo.com:8443/x?y=1"]
)
def test_urls_validas_em_producao(url: str) -> None:
    assert validar_url_webhook(url, permitir_http=False, permitir_rede_interna=False) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://exemplo.com/webhook",
        "ftp://exemplo.com/x",
        "https:///sem-host",
        "https://usuario:senha@exemplo.com/x",
        "https://exemplo.com/x#fragmento",
        "https://localhost/x",
        "https://127.0.0.1/x",
        "https://10.0.0.5/x",
        "https://[::1]/x",
        "https://169.254.169.254/x",
        "https://servico.internal/x",
        "https://exemplo.com:99999/x",
        "https://exemplo.com/" + "a" * 2050,
        "nao-e-url",
    ],
)
def test_urls_invalidas_em_producao(url: str) -> None:
    with pytest.raises(UrlDeWebhookInvalida):
        validar_url_webhook(url, permitir_http=False, permitir_rede_interna=False)


def test_http_e_rede_interna_aceitos_fora_de_producao() -> None:
    url = "http://localhost:9099/webhook"
    assert validar_url_webhook(url, permitir_http=True, permitir_rede_interna=True) == url


def test_https_obrigatorio_tem_mensagem_clara() -> None:
    with pytest.raises(UrlDeWebhookInvalida) as erro:
        validar_url_webhook("http://exemplo.com", permitir_http=False, permitir_rede_interna=True)
    assert "https" in erro.value.mensagem
    assert erro.value.status_http == 422
