import ipaddress

import pytest

from notificacoes.dominio.erros import UrlDeWebhookInvalida
from notificacoes.dominio.url_webhook import ip_bloqueado, validar_url_webhook


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


@pytest.mark.parametrize(
    "url",
    [
        "https://postgres/x",
        "https://rabbitmq:5672/x",
        "https://mock-identidade:8001/perfis/1",
        "https://2130706433/x",
        "https://127.1/x",
        "https://0x7f000001/x",
        "https://0177.0.0.1/x",
        "https://0.0.0.0/x",
        "https://localhost./x",
        "https://[::ffff:127.0.0.1]/x",
        "https://[fd00::1]/x",
        "https://100.64.0.1/x",
        "https://[ff02::1]/x",
    ],
)
def test_ssrf_nomes_de_servico_e_formas_numericas_sao_recusados(url: str) -> None:
    with pytest.raises(UrlDeWebhookInvalida):
        validar_url_webhook(url, permitir_http=False, permitir_rede_interna=False)


def test_forma_numerica_publica_e_normalizada() -> None:
    assert (
        validar_url_webhook(
            "https://0x5db8d822:8443/x?y=1", permitir_http=False, permitir_rede_interna=False
        )
        == "https://93.184.216.34:8443/x?y=1"
    )


def test_nomes_de_servico_continuam_aceitos_em_ambiente_local() -> None:
    url = "http://mock-identidade:8001/webhook"
    assert validar_url_webhook(url, permitir_http=True, permitir_rede_interna=True) == url


@pytest.mark.parametrize(
    ("ip", "bloqueado"),
    [
        ("10.0.0.5", True),
        ("172.16.0.1", True),
        ("192.168.1.1", True),
        ("127.0.0.1", True),
        ("169.254.169.254", True),
        ("100.64.0.1", True),
        ("224.0.0.1", True),
        ("0.0.0.0", True),  # noqa: S104 - endereço só verificado, nunca usado
        ("::1", True),
        ("fe80::1", True),
        ("fd00::1", True),
        ("::ffff:10.0.0.1", True),
        ("93.184.216.34", False),
        ("2606:2800:220:1:248:1893:25c8:1946", False),
    ],
)
def test_ip_bloqueado(ip: str, bloqueado: bool) -> None:
    assert ip_bloqueado(ipaddress.ip_address(ip)) is bloqueado
