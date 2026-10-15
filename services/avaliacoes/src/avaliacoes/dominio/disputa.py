"""Entidade ``Disputa`` e sua máquina de estados (spec §4.3).

aberta ──improcedente──► improcedente (terminal)
aberta ──procedente──► estorno_pendente ──estorno ok──► resolvida (terminal)
                              └──falha definitiva──► estorno_falhou (terminal)
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Self

from avaliacoes.dominio.erros import (
    DisputaInvalida,
    TransicaoInvalida,
    ValorAprovadoInvalido,
    ValorExcedePago,
)

DESCRICAO_MAXIMA = 2000
PARECER_MAXIMO = 2000
MOTIVO_FALHA_MAXIMO = 200
STATUS_PAGAMENTO_CONTESTAVEIS = frozenset({"aprovado", "parcialmente_estornado"})


class StatusDisputa(StrEnum):
    ABERTA = "aberta"
    ESTORNO_PENDENTE = "estorno_pendente"
    RESOLVIDA = "resolvida"
    IMPROCEDENTE = "improcedente"
    ESTORNO_FALHOU = "estorno_falhou"


STATUS_NAO_TERMINAIS = frozenset({StatusDisputa.ABERTA, StatusDisputa.ESTORNO_PENDENTE})


class MotivoDisputa(StrEnum):
    ITEM_FALTANDO = "item_faltando"
    PEDIDO_ERRADO = "pedido_errado"
    NAO_ENTREGUE = "nao_entregue"
    QUALIDADE = "qualidade"


class Decisao(StrEnum):
    PROCEDENTE = "procedente"
    IMPROCEDENTE = "improcedente"


def _texto_opcional(valor: str | None, *, campo: str, maximo: int) -> str | None:
    if valor is None:
        return None
    texto = valor.strip()
    if len(texto) > maximo:
        raise DisputaInvalida(
            f"{campo} deve ter no máximo {maximo} caracteres.", detalhes={"campo": campo}
        )
    return texto or None


@dataclass(slots=True)
class Disputa:
    id: uuid.UUID
    pedido_id: str
    pagamento_id: str
    cliente_id: str
    motivo: MotivoDisputa
    descricao: str | None
    valor_solicitado_centavos: int
    status: StatusDisputa
    criado_em: datetime
    atualizado_em: datetime
    valor_aprovado_centavos: int | None = None
    parecer: str | None = None
    estorno_id: str | None = None
    tentativas_estorno: int = 0
    proxima_tentativa_em: datetime | None = None
    motivo_falha_estorno: str | None = None

    @classmethod
    def abrir(
        cls,
        *,
        pedido_id: str,
        pagamento_id: str,
        cliente_id: str,
        motivo: MotivoDisputa,
        descricao: str | None,
        valor_solicitado_centavos: int,
        valor_pago_centavos: int,
        agora: datetime,
    ) -> Self:
        if isinstance(valor_solicitado_centavos, bool) or valor_solicitado_centavos <= 0:
            raise DisputaInvalida(
                "valor_solicitado_centavos deve ser positivo.",
                detalhes={"campo": "valor_solicitado_centavos"},
            )
        if valor_solicitado_centavos > valor_pago_centavos:
            raise ValorExcedePago(detalhes={"valor_pago_centavos": valor_pago_centavos})
        return cls(
            id=uuid.uuid4(),
            pedido_id=pedido_id,
            pagamento_id=pagamento_id,
            cliente_id=cliente_id,
            motivo=motivo,
            descricao=_texto_opcional(descricao, campo="descricao", maximo=DESCRICAO_MAXIMA),
            valor_solicitado_centavos=valor_solicitado_centavos,
            status=StatusDisputa.ABERTA,
            criado_em=agora,
            atualizado_em=agora,
        )

    @property
    def terminal(self) -> bool:
        return self.status not in STATUS_NAO_TERMINAIS

    @property
    def decisao(self) -> Decisao | None:
        if self.status is StatusDisputa.ABERTA:
            return None
        if self.status is StatusDisputa.IMPROCEDENTE:
            return Decisao.IMPROCEDENTE
        return Decisao.PROCEDENTE

    @property
    def chave_idempotencia_estorno(self) -> str:
        """Fixa por disputa: repetir o estorno é seguro (spec §4.3, saga passo 2)."""
        return f"disputa-{self.id}"

    @property
    def motivo_estorno(self) -> str:
        """Texto fixo por disputa: o corpo repetido tem de ser idêntico (idempotência)."""
        return f"Disputa {self.id} procedente ({self.motivo.value})."

    def valor_a_estornar(self) -> int:
        self._exigir(StatusDisputa.ESTORNO_PENDENTE)
        if self.valor_aprovado_centavos is None:  # pragma: no cover - garantido por aprovar()
            raise TransicaoInvalida("Disputa sem valor aprovado.")
        return self.valor_aprovado_centavos

    def julgar_improcedente(
        self, *, parecer: str | None, valor_aprovado_centavos: int | None, agora: datetime
    ) -> None:
        self._exigir(StatusDisputa.ABERTA)
        if valor_aprovado_centavos not in (None, 0):
            raise ValorAprovadoInvalido("Disputa improcedente não aprova valor.")
        self.parecer = _texto_opcional(parecer, campo="parecer", maximo=PARECER_MAXIMO)
        self.valor_aprovado_centavos = 0
        self.status = StatusDisputa.IMPROCEDENTE
        self.atualizado_em = agora

    def aprovar(
        self,
        *,
        valor_aprovado_centavos: int | None,
        parecer: str | None,
        agora: datetime,
        primeira_tentativa_em: datetime,
    ) -> None:
        """Procedente: vai para ``estorno_pendente``. Sem valor, usa o solicitado (regra 4)."""
        self._exigir(StatusDisputa.ABERTA)
        valor = (
            self.valor_solicitado_centavos
            if valor_aprovado_centavos is None
            else valor_aprovado_centavos
        )
        if isinstance(valor, bool) or not 0 < valor <= self.valor_solicitado_centavos:
            raise ValorAprovadoInvalido(
                "valor_aprovado_centavos deve ser positivo e no máximo o valor solicitado.",
                detalhes={"valor_solicitado_centavos": self.valor_solicitado_centavos},
            )
        self.parecer = _texto_opcional(parecer, campo="parecer", maximo=PARECER_MAXIMO)
        self.valor_aprovado_centavos = valor
        self.status = StatusDisputa.ESTORNO_PENDENTE
        self.proxima_tentativa_em = primeira_tentativa_em
        self.atualizado_em = agora

    def contar_tentativa(self) -> None:
        self._exigir(StatusDisputa.ESTORNO_PENDENTE)
        self.tentativas_estorno += 1

    def concluir_estorno(self, *, estorno_id: str, agora: datetime) -> None:
        self._exigir(StatusDisputa.ESTORNO_PENDENTE)
        self.estorno_id = estorno_id
        self.status = StatusDisputa.RESOLVIDA
        self.proxima_tentativa_em = None
        self.atualizado_em = agora

    def adiar_estorno(self, *, proxima_tentativa_em: datetime, agora: datetime) -> None:
        self._exigir(StatusDisputa.ESTORNO_PENDENTE)
        self.proxima_tentativa_em = proxima_tentativa_em
        self.atualizado_em = agora

    def falhar_estorno(self, *, motivo: str, agora: datetime) -> None:
        self._exigir(StatusDisputa.ESTORNO_PENDENTE)
        self.motivo_falha_estorno = motivo[:MOTIVO_FALHA_MAXIMO]
        self.status = StatusDisputa.ESTORNO_FALHOU
        self.proxima_tentativa_em = None
        self.atualizado_em = agora

    def _exigir(self, esperado: StatusDisputa) -> None:
        if self.status is not esperado:
            raise TransicaoInvalida(
                f"A disputa está '{self.status.value}'; a operação exige '{esperado.value}'.",
                detalhes={"status_atual": self.status.value},
            )
