"""Chaves RSA e tokens RS256 de teste (usados nos testes e no mock da Eq. 1)."""

import json
import time
from collections.abc import Mapping
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from plataforma.auth import VerificadorComposto, VerificadorJwks, VerificadorTokenServico

URL_JWKS_TESTE = "http://identidade.teste/.well-known/jwks.json"
SEGREDO_SERVICO_TESTE = "segredo-de-teste-financeiro-eq5-0123456789"


class GeradorDeTokens:
    def __init__(self, *, kid: str = "chave-teste-1", emissor: str = "mock-identidade") -> None:
        self.kid = kid
        self.emissor = emissor
        self._chave_privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def jwks(self) -> dict[str, Any]:
        publica: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(self._chave_privada.public_key()))
        publica.update({"kid": self.kid, "use": "sig", "alg": "RS256"})
        return {"keys": [publica]}

    def emitir(
        self,
        sub: str,
        papel: str,
        *,
        validade_segundos: int = 3600,
        claims_extras: Mapping[str, Any] | None = None,
    ) -> str:
        agora = int(time.time())
        claims: dict[str, Any] = {
            "iss": self.emissor,
            "sub": sub,
            "papel": papel,
            "iat": agora,
            "exp": agora + validade_segundos,
            **(claims_extras or {}),
        }
        return str(
            jwt.encode(claims, self._chave_privada, algorithm="RS256", headers={"kid": self.kid})
        )


def transporte_jwks(gerador: GeradorDeTokens) -> httpx.MockTransport:
    """Transporte httpx que responde o JWKS do gerador em qualquer URL."""
    return httpx.MockTransport(lambda _requisicao: httpx.Response(200, json=gerador.jwks()))


def criar_verificador_de_teste(
    gerador: GeradorDeTokens, *, segredo_servico: str = SEGREDO_SERVICO_TESTE
) -> VerificadorComposto:
    """Verificador real (JWKS + interno) sem rede, para testes de API dos serviços."""
    return VerificadorComposto(
        externo=VerificadorJwks(
            URL_JWKS_TESTE, cliente=httpx.AsyncClient(transport=transporte_jwks(gerador))
        ),
        interno=VerificadorTokenServico(segredo_servico),
    )
