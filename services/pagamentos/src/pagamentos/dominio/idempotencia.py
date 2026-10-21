"""Regras de idempotência (spec §4.1, regra 6).

- A chave vale por 24 h (``VALIDADE``).
- Mesmo corpo: devolve a resposta gravada. Corpo diferente: 422.
- Reservada e ainda em processamento: 409; se ficou abandonada por mais de
  ``TEMPO_MAXIMO_PROCESSAMENTO`` (processo morto), pode ser reassumida. Isso é
  seguro porque a conclusão da chave é gravada na mesma transação do efeito.
- O hash é HMAC-SHA256 com chave secreta: o corpo pode conter o número do cartão
  e um SHA-256 puro seria quebrável por força bruta.
"""

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Self

from pagamentos.dominio.erros import IdempotencyKeyAusente, IdempotencyKeyInvalida

VALIDADE = timedelta(hours=24)
TEMPO_MAXIMO_PROCESSAMENTO = timedelta(seconds=60)
_FORMATO_CHAVE = re.compile(r"[\x21-\x7e]{1,255}")


class StatusChave(StrEnum):
    EM_PROCESSAMENTO = "em_processamento"
    CONCLUIDA = "concluida"


class Decisao(StrEnum):
    PROCESSAR = "processar"
    REPETIR_RESPOSTA = "repetir_resposta"
    CORPO_DIFERENTE = "corpo_diferente"
    EM_PROCESSAMENTO = "em_processamento"


def validar_chave(chave: str | None) -> str:
    if chave is None or not chave.strip():
        raise IdempotencyKeyAusente()
    if not _FORMATO_CHAVE.fullmatch(chave):
        raise IdempotencyKeyInvalida()
    return chave


def calcular_hash(dados: Mapping[str, Any], *, chave: bytes) -> str:
    canonico = json.dumps(dados, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(chave, canonico.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass(slots=True)
class RegistroIdempotencia:
    escopo: str
    chave: str
    hash_requisicao: str
    status: StatusChave
    criado_em: datetime
    status_resposta: int | None = None
    corpo_resposta: dict[str, Any] | None = None

    @classmethod
    def reservar(cls, *, escopo: str, chave: str, hash_requisicao: str, agora: datetime) -> Self:
        return cls(
            escopo=escopo,
            chave=chave,
            hash_requisicao=hash_requisicao,
            status=StatusChave.EM_PROCESSAMENTO,
            criado_em=agora,
        )

    def expirado(self, agora: datetime) -> bool:
        return agora - self.criado_em >= VALIDADE

    def decidir(self, hash_requisicao: str, agora: datetime) -> Decisao:
        if self.expirado(agora):
            return Decisao.PROCESSAR
        if not hmac.compare_digest(self.hash_requisicao, hash_requisicao):
            return Decisao.CORPO_DIFERENTE
        if self.status == StatusChave.CONCLUIDA:
            return Decisao.REPETIR_RESPOSTA
        if agora - self.criado_em >= TEMPO_MAXIMO_PROCESSAMENTO:
            return Decisao.PROCESSAR
        return Decisao.EM_PROCESSAMENTO

    def resposta(self) -> tuple[int, dict[str, Any]]:
        if (
            self.status != StatusChave.CONCLUIDA
            or self.status_resposta is None
            or self.corpo_resposta is None
        ):
            raise ValueError("chave de idempotência não concluída não tem resposta")
        return self.status_resposta, self.corpo_resposta
