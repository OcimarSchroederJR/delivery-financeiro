"""Validação da URL de destino de um webhook (spec §4.2: https, exceto local)."""

import ipaddress
from urllib.parse import urlsplit

from notificacoes.dominio.erros import UrlDeWebhookInvalida

TAMANHO_MAXIMO_URL = 2048
_SUFIXOS_INTERNOS = (".localhost", ".local", ".internal")


def validar_url_webhook(url: str, *, permitir_http: bool, permitir_rede_interna: bool) -> str:
    if len(url) > TAMANHO_MAXIMO_URL:
        raise UrlDeWebhookInvalida(f"A URL do webhook passa de {TAMANHO_MAXIMO_URL} caracteres.")
    partes = urlsplit(url)
    esquemas = {"https", "http"} if permitir_http else {"https"}
    if partes.scheme not in esquemas:
        raise UrlDeWebhookInvalida(
            "A URL do webhook deve usar https."
            if not permitir_http
            else "A URL do webhook deve usar http ou https."
        )
    if not partes.hostname:
        raise UrlDeWebhookInvalida("A URL do webhook não tem host.")
    if partes.username or partes.password:
        raise UrlDeWebhookInvalida("A URL do webhook não pode conter usuário ou senha.")
    if partes.fragment:
        raise UrlDeWebhookInvalida("A URL do webhook não pode conter fragmento (#).")
    try:
        _ = partes.port
    except ValueError as erro:
        raise UrlDeWebhookInvalida("A porta da URL do webhook é inválida.") from erro
    if not permitir_rede_interna and _host_interno(partes.hostname):
        raise UrlDeWebhookInvalida("A URL do webhook aponta para um host interno.")
    return url


def _host_interno(host: str) -> bool:
    if host == "localhost" or host.endswith(_SUFIXOS_INTERNOS):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )
