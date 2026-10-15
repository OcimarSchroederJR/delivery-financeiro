"""Quem pede (vem do JWT) e a política de URLs de webhook (vem do ambiente)."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Solicitante:
    """``admin`` vê e gere tudo; os demais, só o que é seu."""

    id: str
    admin: bool


@dataclass(frozen=True, slots=True)
class PoliticaDeUrl:
    permitir_http: bool
    permitir_rede_interna: bool
