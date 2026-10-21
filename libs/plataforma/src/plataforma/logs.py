"""Logs estruturados com structlog (spec §6).

Campos fixos em toda linha: ``servico``, ``correlation_id``, ``trace_id``,
``nivel`` e ``evento`` (no formato JSON). Dados sensíveis são redigidos por
um processor que roda antes de qualquer renderização, inclusive para logs de
bibliotecas (uvicorn, FastStream, SQLAlchemy) que passam pelo logging padrão.
"""

import dataclasses
import logging
import re
import sys
from collections.abc import Mapping
from typing import Any, Literal

import structlog
from pydantic import BaseModel
from structlog.typing import EventDict, Processor, WrappedLogger

from plataforma.correlation import obter_correlation_id
from plataforma.telemetria import trace_id_atual

REDIGIDO = "***"

CHAVES_SENSIVEIS = frozenset(
    {
        "authorization",
        "token",
        "access_token",
        "refresh_token",
        "token_servico",
        "senha",
        "password",
        "segredo",
        "secret",
        "cvv",
        "cartao",
        "numero_cartao",
    }
)

_PADRAO_CARTAO = re.compile(
    # 13 a 19 dígitos, contíguos ou separados por espaço/hífen ("4111 1111 1111 1111").
    # Não começa nem termina colado a letra/dígito nem a "<alfanumérico>-": assim
    # trace_id hexadecimal, UUID e ids como "pedido-1234567890123" ficam intactos.
    r"(?<![0-9A-Za-z])(?<![0-9A-Za-z]-)\d(?:[ -]?\d){12,18}(?!-?[0-9A-Za-z])"
)

_PADROES_SENSIVEIS = (
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"),
    _PADRAO_CARTAO,
)

_handler_instalado: logging.Handler | None = None


def _redigir_texto(texto: str) -> str:
    for padrao in _PADROES_SENSIVEIS:
        texto = padrao.sub(REDIGIDO, texto)
    return texto


def _redigir(valor: Any) -> Any:
    if isinstance(valor, str):
        return _redigir_texto(valor)
    if valor is None or isinstance(valor, bool | float):
        return valor
    if isinstance(valor, int):
        return REDIGIDO if 13 <= len(str(abs(valor))) <= 19 else valor
    if isinstance(valor, BaseModel):
        return _redigir(valor.model_dump(mode="json"))
    if dataclasses.is_dataclass(valor) and not isinstance(valor, type):
        return _redigir(dataclasses.asdict(valor))
    if isinstance(valor, Mapping):
        return {
            chave: REDIGIDO if str(chave).lower() in CHAVES_SENSIVEIS else _redigir(item)
            for chave, item in valor.items()
        }
    if isinstance(valor, list | tuple | set | frozenset):
        return [_redigir(item) for item in valor]
    return _redigir_texto(str(valor))


def redigir_dados_sensiveis(_logger: WrappedLogger, _metodo: str, evento: EventDict) -> EventDict:
    """Processor structlog: troca valores sensíveis por ``***``.

    BaseModel e dataclass viram dicionários antes da redação; outros objetos viram
    texto. Chaves internas do structlog (``_record``, ``_from_structlog``) passam intactas.
    """
    return {
        chave: (
            valor
            if chave.startswith("_")
            else REDIGIDO
            if chave.lower() in CHAVES_SENSIVEIS
            else _redigir(valor)
        )
        for chave, valor in evento.items()
    }


def _redigir_linha(_logger: WrappedLogger, _metodo: str, linha: Any) -> Any:
    """Última barreira no formato console: redige a linha já renderizada."""
    return _redigir_texto(linha) if isinstance(linha, str) else linha


def _contexto(servico: str) -> Processor:
    def adicionar(_logger: WrappedLogger, _metodo: str, evento: EventDict) -> EventDict:
        evento.setdefault("servico", servico)
        evento.setdefault("correlation_id", obter_correlation_id())
        evento.setdefault("trace_id", trace_id_atual())
        return evento

    return adicionar


def _renomear_nivel(_logger: WrappedLogger, _metodo: str, evento: EventDict) -> EventDict:
    evento["nivel"] = evento.pop("level", None)
    return evento


def configurar_logs(
    servico: str,
    *,
    formato: Literal["json", "console"] = "console",
    nivel: str = "INFO",
) -> None:
    """Configura structlog e o logging padrão. Pode ser chamada de novo (testes)."""
    global _handler_instalado

    compartilhados: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="momento"),
        _contexto(servico),
        structlog.processors.format_exc_info,
        redigir_dados_sensiveis,
    ]
    renderizacao: list[Processor]
    if formato == "json":
        renderizacao = [
            structlog.processors.EventRenamer("evento"),
            _renomear_nivel,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ]
    else:
        renderizacao = [
            structlog.dev.ConsoleRenderer(exception_formatter=structlog.dev.plain_traceback),
            _redigir_linha,
        ]

    structlog.configure(
        processors=[*compartilhados, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=compartilhados,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, *renderizacao],
        )
    )
    raiz = logging.getLogger()
    if _handler_instalado is not None:
        raiz.removeHandler(_handler_instalado)
    raiz.addHandler(handler)
    raiz.setLevel(nivel)
    _handler_instalado = handler


def obter_logger(nome: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.stdlib.get_logger(nome)
