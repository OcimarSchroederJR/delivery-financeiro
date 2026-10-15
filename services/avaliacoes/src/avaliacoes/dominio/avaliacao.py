"""Entidade ``Avaliacao`` e regras para avaliar um pedido (spec §4.3, regras 1 e 2)."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Self

from avaliacoes.dominio.erros import AvaliacaoInvalida, PedidoDeOutroCliente, PedidoNaoEntregue

NOTA_MINIMA = 1
NOTA_MAXIMA = 5
COMENTARIO_MAXIMO = 1000


def _validar_nota(campo: str, nota: int) -> None:
    if isinstance(nota, bool) or not NOTA_MINIMA <= nota <= NOTA_MAXIMA:
        raise AvaliacaoInvalida(
            f"{campo} deve ser um inteiro entre {NOTA_MINIMA} e {NOTA_MAXIMA}.",
            detalhes={"campo": campo},
        )


def _normalizar_comentario(comentario: str | None) -> str | None:
    if comentario is None:
        return None
    texto = comentario.strip()
    if len(texto) > COMENTARIO_MAXIMO:
        raise AvaliacaoInvalida(
            f"comentario deve ter no máximo {COMENTARIO_MAXIMO} caracteres.",
            detalhes={"campo": "comentario"},
        )
    return texto or None


def exigir_pedido_avaliavel(*, cliente_do_pedido: str, entregue: bool, cliente_id: str) -> None:
    """Regra 1: o pedido é do cliente do token e já foi entregue."""
    if cliente_do_pedido != cliente_id:
        raise PedidoDeOutroCliente()
    if not entregue:
        raise PedidoNaoEntregue()


@dataclass(slots=True)
class Avaliacao:
    id: uuid.UUID
    pedido_id: str
    cliente_id: str
    restaurante_id: str
    nota_restaurante: int
    nota_entrega: int | None
    comentario: str | None
    criado_em: datetime

    @classmethod
    def registrar(
        cls,
        *,
        pedido_id: str,
        cliente_id: str,
        restaurante_id: str,
        nota_restaurante: int,
        nota_entrega: int | None,
        comentario: str | None,
        agora: datetime,
    ) -> Self:
        _validar_nota("nota_restaurante", nota_restaurante)
        if nota_entrega is not None:
            _validar_nota("nota_entrega", nota_entrega)
        return cls(
            id=uuid.uuid4(),
            pedido_id=pedido_id,
            cliente_id=cliente_id,
            restaurante_id=restaurante_id,
            nota_restaurante=nota_restaurante,
            nota_entrega=nota_entrega,
            comentario=_normalizar_comentario(comentario),
            criado_em=agora,
        )
