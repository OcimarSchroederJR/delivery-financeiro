"""Paginação ``?pagina=1&tamanho=20`` (máx. 100) e resposta ``{itens, pagina, tamanho, total}``."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Self

from fastapi import Depends, Query
from pydantic import BaseModel

TAMANHO_MAXIMO = 100


@dataclass(frozen=True, slots=True)
class ParametrosPaginacao:
    pagina: int = 1
    tamanho: int = 20

    @property
    def deslocamento(self) -> int:
        return (self.pagina - 1) * self.tamanho


def parametros_paginacao(
    pagina: Annotated[int, Query(ge=1, description="Página, começando em 1")] = 1,
    tamanho: Annotated[
        int, Query(ge=1, le=TAMANHO_MAXIMO, description="Itens por página (máx. 100)")
    ] = 20,
) -> ParametrosPaginacao:
    return ParametrosPaginacao(pagina=pagina, tamanho=tamanho)


Paginacao = Annotated[ParametrosPaginacao, Depends(parametros_paginacao)]


class Pagina[T](BaseModel):
    itens: list[T]
    pagina: int
    tamanho: int
    total: int

    @classmethod
    def criar(cls, itens: Sequence[T], parametros: ParametrosPaginacao, total: int) -> Self:
        return cls(
            itens=list(itens), pagina=parametros.pagina, tamanho=parametros.tamanho, total=total
        )
