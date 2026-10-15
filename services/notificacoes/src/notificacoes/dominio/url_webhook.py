"""Validação da URL de destino de um webhook (spec §4.2: https, exceto local).

Mitigação de SSRF em duas camadas: no cadastro (aqui) recusa nomes internos,
nomes sem domínio (``postgres``, ``mock-identidade``) e IPs internos, inclusive
nas formas numéricas antigas (``2130706433``, ``127.1``, ``0x7f000001``); na
entrega, o adaptador resolve o DNS, recusa IP interno com ``ip_bloqueado`` e
conecta no IP já validado.
"""

import ipaddress
from urllib.parse import urlsplit, urlunsplit

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
    if permitir_rede_interna:
        return url
    host = partes.hostname.rstrip(".")
    ip = ip_do_host(host)
    if ip is None:
        if host == "localhost" or host.endswith(_SUFIXOS_INTERNOS) or "." not in host:
            raise UrlDeWebhookInvalida("A URL do webhook aponta para um host interno.")
        return url
    if ip_bloqueado(ip):
        raise UrlDeWebhookInvalida("A URL do webhook aponta para um host interno.")
    canonico = str(ip) if ip.version == 4 else f"[{ip}]"
    if canonico == partes.hostname:
        return url
    netloc = canonico if partes.port is None else f"{canonico}:{partes.port}"
    return urlunsplit(partes._replace(netloc=netloc))


IpQualquer = ipaddress.IPv4Address | ipaddress.IPv6Address


def ip_bloqueado(ip: IpQualquer) -> bool:
    """IP fora da internet pública (privado, loopback, link-local, reservado, multicast)."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        not ip.is_global
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def ip_do_host(host: str) -> IpQualquer | None:
    """IP literal do host, aceitando as formas numéricas antigas do IPv4."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return _ipv4_legado(host)


def _parte_numerica(texto: str) -> int | None:
    try:
        if texto.lower().startswith("0x"):
            return int(texto[2:], 16)
        if len(texto) > 1 and texto.startswith("0"):
            return int(texto[1:], 8)
        return int(texto, 10)
    except ValueError:
        return None


def _ipv4_legado(host: str) -> ipaddress.IPv4Address | None:
    """``inet_aton``: 1 a 4 partes decimais, octais (``0``) ou hexadecimais (``0x``)."""
    textos = host.split(".")
    if not 1 <= len(textos) <= 4 or not all(textos):
        return None
    partes = [_parte_numerica(texto) for texto in textos]
    if any(parte is None for parte in partes):
        return None
    numeros = [parte for parte in partes if parte is not None]
    *iniciais, ultima = numeros
    if any(not 0 <= numero <= 255 for numero in iniciais):
        return None
    if not 0 <= ultima < 256 ** (4 - len(iniciais)):
        return None
    valor = 0
    for numero in iniciais:
        valor = valor * 256 + numero
    valor = valor * 256 ** (4 - len(iniciais)) + ultima
    return ipaddress.IPv4Address(valor)
