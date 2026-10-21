"""Padrões de assinatura no estilo das routing keys AMQP.

``*`` casa exatamente um segmento e ``#`` casa zero ou mais segmentos
(ex.: ``pagamento.*`` casa ``pagamento.aprovado``; ``#`` casa tudo).
"""

import re

from notificacoes.dominio.erros import PadraoDeEventoInvalido

TAMANHO_MAXIMO_PADRAO = 100
_SEGMENTO = r"(?:[a-z][a-z0-9_]*|\*|#)"
_PADRAO = re.compile(rf"{_SEGMENTO}(?:\.{_SEGMENTO})*")


def validar_padrao(padrao: str) -> str:
    if len(padrao) > TAMANHO_MAXIMO_PADRAO or not _PADRAO.fullmatch(padrao):
        raise PadraoDeEventoInvalido(
            "Padrão de evento inválido: use segmentos minúsculos separados por ponto, "
            "com * (um segmento) ou # (zero ou mais segmentos).",
            detalhes={"padrao": padrao[:TAMANHO_MAXIMO_PADRAO]},
        )
    return padrao


def padrao_casa(padrao: str, tipo: str) -> bool:
    return _casa(tuple(padrao.split(".")), tuple(tipo.split(".")))


def _casa(padrao: tuple[str, ...], tipo: tuple[str, ...]) -> bool:
    if not padrao:
        return not tipo
    cabeca, resto = padrao[0], padrao[1:]
    if cabeca == "#":
        return any(_casa(resto, tipo[inicio:]) for inicio in range(len(tipo) + 1))
    if not tipo:
        return False
    return cabeca in ("*", tipo[0]) and _casa(resto, tipo[1:])
