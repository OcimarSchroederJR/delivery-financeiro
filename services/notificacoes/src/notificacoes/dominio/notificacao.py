"""Notificação (e-mail ou webhook) e sua máquina de estados.

``pendente`` → ``enviada`` | ``falhou``. ``tentativas`` conta as tentativas já
feitas. Com ``max_retentativas = 5``: as falhas 1 a 5 pedem as retentativas
1 a 5 (filas ``retry.1`` … ``retry.5``); a 6ª falha encerra como ``falhou``.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Self

from notificacoes.dominio.assinatura import AssinaturaWebhook
from notificacoes.dominio.erros import TransicaoInvalida

TAMANHO_MAXIMO_ERRO = 500


class Canal(StrEnum):
    EMAIL = "email"
    WEBHOOK = "webhook"


class StatusNotificacao(StrEnum):
    PENDENTE = "pendente"
    ENVIADA = "enviada"
    FALHOU = "falhou"


@dataclass(slots=True)
class Notificacao:
    id: uuid.UUID
    mensagem_id_origem: uuid.UUID
    tipo_evento: str
    canal: Canal
    destino: str | None
    destinatario_id: str | None
    assinatura_id: uuid.UUID | None
    status: StatusNotificacao
    tentativas: int
    ultimo_erro: str | None
    criado_em: datetime
    enviada_em: datetime | None

    @classmethod
    def para_email(
        cls,
        *,
        mensagem_id_origem: uuid.UUID,
        tipo_evento: str,
        destinatario_id: str | None,
        destino: str | None,
        agora: datetime,
    ) -> Self:
        return cls(
            id=uuid.uuid4(),
            mensagem_id_origem=mensagem_id_origem,
            tipo_evento=tipo_evento,
            canal=Canal.EMAIL,
            destino=destino,
            destinatario_id=destinatario_id,
            assinatura_id=None,
            status=StatusNotificacao.PENDENTE,
            tentativas=0,
            ultimo_erro=None,
            criado_em=agora,
            enviada_em=None,
        )

    @classmethod
    def para_webhook(
        cls,
        *,
        mensagem_id_origem: uuid.UUID,
        tipo_evento: str,
        assinatura: AssinaturaWebhook,
        agora: datetime,
    ) -> Self:
        return cls(
            id=uuid.uuid4(),
            mensagem_id_origem=mensagem_id_origem,
            tipo_evento=tipo_evento,
            canal=Canal.WEBHOOK,
            destino=assinatura.url,
            destinatario_id=assinatura.criado_por,
            assinatura_id=assinatura.id,
            status=StatusNotificacao.PENDENTE,
            tentativas=0,
            ultimo_erro=None,
            criado_em=agora,
            enviada_em=None,
        )

    @property
    def pendente(self) -> bool:
        return self.status is StatusNotificacao.PENDENTE

    def registrar_envio(self, *, agora: datetime, destino: str | None = None) -> None:
        self._exigir_pendente()
        self.tentativas += 1
        self.status = StatusNotificacao.ENVIADA
        self.enviada_em = agora
        if destino is not None:
            self.destino = destino

    def registrar_falha(self, erro: str, *, max_retentativas: int) -> int | None:
        """Registra uma falha transitória. Devolve o número da retentativa ou ``None``."""
        self._exigir_pendente()
        self.tentativas += 1
        self.ultimo_erro = erro[:TAMANHO_MAXIMO_ERRO]
        if self.tentativas <= max_retentativas:
            return self.tentativas
        self.status = StatusNotificacao.FALHOU
        return None

    def falhar_definitivamente(self, erro: str) -> None:
        self._exigir_pendente()
        self.tentativas += 1
        self.ultimo_erro = erro[:TAMANHO_MAXIMO_ERRO]
        self.status = StatusNotificacao.FALHOU

    def cancelar(self, motivo: str) -> None:
        """Encerra sem tentar (ex.: assinatura removida antes da entrega)."""
        self._exigir_pendente()
        self.ultimo_erro = motivo[:TAMANHO_MAXIMO_ERRO]
        self.status = StatusNotificacao.FALHOU

    def _exigir_pendente(self) -> None:
        if not self.pendente:
            raise TransicaoInvalida(f"Notificação {self.id} já está {self.status}.")
