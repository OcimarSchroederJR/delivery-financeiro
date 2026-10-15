"""Quem está chamando o caso de uso (independente de FastAPI e de JWT)."""

from dataclasses import dataclass, field

PAPEL_CLIENTE = "cliente"


@dataclass(frozen=True, slots=True)
class Solicitante:
    id: str
    papel: str
    token: str = field(repr=False)

    @property
    def e_cliente(self) -> bool:
        return self.papel == PAPEL_CLIENTE
