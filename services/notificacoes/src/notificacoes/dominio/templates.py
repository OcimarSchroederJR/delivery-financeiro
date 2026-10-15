"""Templates de e-mail (texto puro) por tipo de evento.

Os textos usam ``str.format_map`` só com valores dos ``dados`` (os textos dos
templates são nossos; os valores nunca são reinterpretados). Campos
``*_centavos`` inteiros ganham um irmão ``*_reais`` já formatado.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from notificacoes.dominio.erros import DadosDoEventoInsuficientes

_SUFIXO_CENTAVOS = "_centavos"
_RODAPE = (
    "\n\n--\nEquipe 5 - Financeiro e Pós - Plataforma de Delivery\n"
    "Este é um e-mail automático; não responda."
)


def formatar_reais(centavos: int) -> str:
    sinal = "-" if centavos < 0 else ""
    reais, resto = divmod(abs(centavos), 100)
    inteiro = f"{reais:,}".replace(",", ".")
    return f"{sinal}R$ {inteiro},{resto:02d}"


class _Campos(dict[str, str]):
    def __missing__(self, chave: str) -> str:
        raise DadosDoEventoInsuficientes(f"O evento não traz o campo '{chave}'.")


def _campos(dados: Mapping[str, Any], nome: str) -> _Campos:
    campos = _Campos(nome=nome)
    for chave, valor in dados.items():
        if isinstance(valor, bool) or not isinstance(valor, str | int | float):
            continue
        campos[chave] = str(valor)
        if chave.endswith(_SUFIXO_CENTAVOS) and isinstance(valor, int):
            campos[chave.removesuffix(_SUFIXO_CENTAVOS) + "_reais"] = formatar_reais(valor)
    return campos


@dataclass(frozen=True, slots=True)
class EmailRenderizado:
    assunto: str
    corpo: str


@dataclass(frozen=True, slots=True)
class ModeloEmail:
    tipo: str
    assunto: str
    corpo: str
    campo_destinatario: str | None = "cliente_id"  # None = e-mail do admin

    @property
    def para_admin(self) -> bool:
        return self.campo_destinatario is None

    def destinatario_id(self, dados: Mapping[str, Any]) -> str | None:
        if self.campo_destinatario is None:
            return None
        valor = dados.get(self.campo_destinatario)
        return valor if isinstance(valor, str) and valor else None

    def renderizar(self, dados: Mapping[str, Any], *, nome: str) -> EmailRenderizado:
        campos = _campos(dados, nome)
        return EmailRenderizado(
            assunto=self.assunto.format_map(campos), corpo=self.corpo.format_map(campos)
        )


MODELOS: dict[str, ModeloEmail] = {
    modelo.tipo: modelo
    for modelo in (
        ModeloEmail(
            "pagamento.aprovado",
            "Pagamento aprovado - pedido {pedido_id}",
            "Olá, {nome}!\n\nSeu pagamento de {valor_reais} para o pedido {pedido_id} "
            "foi aprovado (método: {metodo})." + _RODAPE,
        ),
        ModeloEmail(
            "pagamento.recusado",
            "Pagamento recusado - pedido {pedido_id}",
            "Olá, {nome}!\n\nSeu pagamento de {valor_reais} para o pedido {pedido_id} "
            "foi recusado. Motivo: {motivo}.\nVocê pode tentar de novo com outro meio "
            "de pagamento." + _RODAPE,
        ),
        ModeloEmail(  # valor_centavos = valor DESTE estorno (contrato de Pagamentos)
            "pagamento.estornado",
            "Estorno realizado - pedido {pedido_id}",
            "Olá, {nome}!\n\nEstornamos {valor_reais} referentes ao pedido {pedido_id}. "
            "Motivo: {motivo}." + _RODAPE,
        ),
        ModeloEmail(
            "avaliacao.registrada",
            "Obrigado pela sua avaliação - pedido {pedido_id}",
            "Olá, {nome}!\n\nRecebemos sua avaliação do pedido {pedido_id}: nota "
            "{nota_restaurante}/5 para o restaurante." + _RODAPE,
        ),
        ModeloEmail(
            "disputa.aberta",
            "Disputa aberta - pedido {pedido_id}",
            "Olá, {nome}!\n\nRecebemos sua disputa sobre o pedido {pedido_id} (motivo: "
            "{motivo}), com pedido de reembolso de {valor_solicitado_reais}.\n"
            "Protocolo: {disputa_id}." + _RODAPE,
        ),
        ModeloEmail(
            "disputa.resolvida",
            "Disputa {decisao} - pedido {pedido_id}",
            "Olá, {nome}!\n\nSua disputa {disputa_id} sobre o pedido {pedido_id} foi "
            "considerada {decisao}.\nValor estornado: {valor_estornado_reais}." + _RODAPE,
        ),
        ModeloEmail(
            "disputa.estorno_falhou",
            "[Ação necessária] Estorno da disputa {disputa_id} falhou",
            "Olá, {nome}!\n\nO estorno da disputa {disputa_id} (pedido {pedido_id}) "
            "falhou definitivamente: {motivo}.\nVerifique o pagamento e trate o caso "
            "manualmente." + _RODAPE,
            campo_destinatario=None,
        ),
        ModeloEmail(
            "entrega.concluida",
            "Pedido {pedido_id} entregue",
            "Olá, {nome}!\n\nSeu pedido {pedido_id} foi entregue. Que tal avaliar o "
            "restaurante e a entrega?" + _RODAPE,
        ),
    )
}


def modelo_para(tipo: str) -> ModeloEmail | None:
    """Template do tipo; ``None`` = o tipo não gera e-mail (spec §4.2)."""
    return MODELOS.get(tipo)
