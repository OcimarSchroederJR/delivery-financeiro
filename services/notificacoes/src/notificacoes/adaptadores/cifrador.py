"""Cifragem do segredo de webhook em repouso (Fernet: AES-128-CBC + HMAC-SHA256)."""

import base64
import hashlib
from typing import Self

from cryptography.fernet import Fernet, InvalidToken

from notificacoes.aplicacao.portas import SegredoIlegivel

__all__ = ["CifradorFernet", "SegredoIlegivel"]

_ROTULO = b"notificacoes-webhooks:"


class CifradorFernet:
    """Implementa ``CifradorDeSegredos``."""

    def __init__(self, chave: bytes) -> None:
        self._fernet = Fernet(chave)

    @classmethod
    def de_segredo(cls, segredo: str) -> Self:
        """Deriva a chave Fernet (32 bytes, base64) de um segredo textual."""
        resumo = hashlib.sha256(_ROTULO + segredo.encode()).digest()
        return cls(base64.urlsafe_b64encode(resumo))

    def cifrar(self, texto: str) -> str:
        return self._fernet.encrypt(texto.encode()).decode()

    def decifrar(self, cifrado: str) -> str:
        try:
            return self._fernet.decrypt(cifrado.encode()).decode()
        except InvalidToken as erro:
            raise SegredoIlegivel("Não foi possível decifrar o segredo do webhook.") from erro
