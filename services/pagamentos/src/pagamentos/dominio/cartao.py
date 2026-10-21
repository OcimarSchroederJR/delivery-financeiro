"""Dados do cartão: só trafegam em memória. Nunca são persistidos nem logados."""

import re
from dataclasses import dataclass

_NUMERO = re.compile(r"[0-9]{13,19}")


@dataclass(frozen=True, slots=True, repr=False)
class DadosCartao:
    numero: str
    titular: str
    validade: str
    cvv: str

    def __post_init__(self) -> None:
        if not _NUMERO.fullmatch(self.numero):
            # A mensagem nunca inclui o valor recebido.
            raise ValueError("número de cartão inválido")

    @property
    def ultimos_digitos(self) -> str:
        return self.numero[-4:]

    def __repr__(self) -> str:
        return f"DadosCartao(final={self.ultimos_digitos})"

    def __str__(self) -> str:
        return self.__repr__()
