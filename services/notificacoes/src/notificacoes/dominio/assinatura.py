"""Assinatura de webhook: quais eventos, para onde e de quem."""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Self

from notificacoes.dominio.erros import PadraoDeEventoInvalido
from notificacoes.dominio.padroes import padrao_casa, validar_padrao
from notificacoes.dominio.url_webhook import validar_url_webhook

MAXIMO_PADROES = 20
CAMPOS_DE_DONO = ("cliente_id", "restaurante_id", "entregador_id")


def evento_pertence_a(usuario_id: str, dados: Mapping[str, Any]) -> bool:
    """O evento é "do" usuário se algum campo de dono dos ``dados`` for o id dele."""
    return any(dados.get(campo) == usuario_id for campo in CAMPOS_DE_DONO)


@dataclass(slots=True)
class AssinaturaWebhook:
    id: uuid.UUID
    url: str
    eventos: tuple[str, ...]
    segredo: str = field(repr=False)
    ativa: bool
    criado_por: str
    somente_proprios: bool
    criado_em: datetime

    @classmethod
    def nova(
        cls,
        *,
        url: str,
        eventos: Sequence[str],
        segredo: str,
        criado_por: str,
        somente_proprios: bool,
        agora: datetime,
        permitir_http: bool,
        permitir_rede_interna: bool,
    ) -> Self:
        padroes = tuple(dict.fromkeys(validar_padrao(padrao) for padrao in eventos))
        if not padroes or len(padroes) > MAXIMO_PADROES:
            raise PadraoDeEventoInvalido(f"Informe de 1 a {MAXIMO_PADROES} padrões de evento.")
        return cls(
            id=uuid.uuid4(),
            url=validar_url_webhook(
                url, permitir_http=permitir_http, permitir_rede_interna=permitir_rede_interna
            ),
            eventos=padroes,
            segredo=segredo,
            ativa=True,
            criado_por=criado_por,
            somente_proprios=somente_proprios,
            criado_em=agora,
        )

    def recebe(self, tipo: str, dados: Mapping[str, Any]) -> bool:
        if not self.ativa or not any(padrao_casa(padrao, tipo) for padrao in self.eventos):
            return False
        return not self.somente_proprios or evento_pertence_a(self.criado_por, dados)

    def pode_ser_gerida_por(self, usuario_id: str, *, admin: bool) -> bool:
        return admin or self.criado_por == usuario_id

    def desativar(self) -> None:
        self.ativa = False
