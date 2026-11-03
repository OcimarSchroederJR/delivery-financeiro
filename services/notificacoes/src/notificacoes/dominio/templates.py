"""Templates de e-mail (texto puro) por tipo de evento.

Os textos usam ``str.format_map`` só com valores dos ``dados`` (os textos dos
templates são nossos; os valores nunca são reinterpretados). Campos
``*_centavos`` inteiros ganham um irmão ``*_reais`` já formatado.
"""

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from notificacoes.dominio.erros import DadosDoEventoInsuficientes

_SUFIXO_CENTAVOS = "_centavos"
_QUEBRAS_E_CONTROLE = frozenset({"Cc", "Zl", "Zp"})
_RODAPE = (
    "\n\n--\nEquipe 5 - Financeiro e Pós - Plataforma de Delivery\n"
    "Este é um e-mail automático; não responda."
)


_CONFERIR_PAGAMENTO = (
    "Confira o pagamento e os estornos em Pagamentos (GET /v1/pagamentos?pedido_id="
    "{pedido_id} e GET /v1/pagamentos/<id>/estornos) e trate o caso manualmente."
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
    # Texto alternativo (assunto, corpo) conforme o valor de ``dados[campo_variante]``.
    campo_variante: str | None = None
    variantes: Mapping[str, tuple[str, str]] = field(default_factory=dict)

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
        modelo_assunto, modelo_corpo = self._textos(dados)
        assunto = modelo_assunto.format_map(campos)
        if any(unicodedata.category(caractere) in _QUEBRAS_E_CONTROLE for caractere in assunto):
            # Quebra de linha no Subject permitiria injetar cabeçalhos (e o
            # EmailMessage recusa com ValueError): repetir não resolve.
            raise DadosDoEventoInsuficientes("O assunto teria quebra de linha ou controle.")
        return EmailRenderizado(assunto=assunto, corpo=modelo_corpo.format_map(campos))

    def _textos(self, dados: Mapping[str, Any]) -> tuple[str, str]:
        if self.campo_variante is not None:
            variante = self.variantes.get(str(dados.get(self.campo_variante)))
            if variante is not None:
                return variante
        return self.assunto, self.corpo


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
        ModeloEmail(  # motivo: código da recusa de Pagamentos ou RESULTADO_INCERTO
            "disputa.estorno_falhou",
            "[Ação necessária] Estorno da disputa {disputa_id} recusado por Pagamentos",
            "Olá, {nome}!\n\nPagamentos recusou definitivamente o estorno da disputa "
            "{disputa_id} (pedido {pedido_id}), com o código {motivo}. Nenhum valor foi "
            "estornado por esta disputa.\n" + _CONFERIR_PAGAMENTO + _RODAPE,
            campo_destinatario=None,
            campo_variante="motivo",
            variantes={
                "RESULTADO_INCERTO": (
                    "[Ação necessária] Estorno da disputa {disputa_id}: resultado incerto",
                    "Olá, {nome}!\n\nO estorno da disputa {disputa_id} (pedido "
                    "{pedido_id}) terminou com resultado incerto: as tentativas se "
                    "esgotaram com falhas transitórias em Pagamentos (timeout ou "
                    "indisponibilidade).\n\nATENÇÃO: o estorno pode ter sido efetuado. "
                    "Antes de qualquer ação manual, confira em Pagamentos:\n"
                    "- GET /v1/pagamentos?pedido_id={pedido_id} (para achar o pagamento);\n"
                    "- GET /v1/pagamentos/<id>/estornos (para ver os estornos feitos).\n"
                    "Não estorne de novo sem essa conferência: o cliente seria "
                    "reembolsado em dobro." + _RODAPE,
                ),
                "PAGAMENTO_NAO_ESTORNAVEL": (
                    "[Ação necessária] Estorno da disputa {disputa_id} recusado por Pagamentos",
                    "Olá, {nome}!\n\nPagamentos recusou o estorno da disputa {disputa_id} "
                    "(pedido {pedido_id}): o pagamento não pode ser estornado (foi recusado "
                    "ou já está totalmente estornado). Nenhum valor foi estornado por esta "
                    "disputa.\n" + _CONFERIR_PAGAMENTO + _RODAPE,
                ),
                "VALOR_EXCEDE_SALDO_ESTORNAVEL": (
                    "[Ação necessária] Estorno da disputa {disputa_id} recusado por Pagamentos",
                    "Olá, {nome}!\n\nPagamentos recusou o estorno da disputa {disputa_id} "
                    "(pedido {pedido_id}): o valor aprovado é maior que o saldo estornável "
                    "do pagamento (provavelmente já houve outro estorno). Nenhum valor foi "
                    "estornado por esta disputa.\n" + _CONFERIR_PAGAMENTO + _RODAPE,
                ),
            },
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
