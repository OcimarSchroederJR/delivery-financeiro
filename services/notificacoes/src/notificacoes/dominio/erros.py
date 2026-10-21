"""Erros de negócio do serviço de Notificações."""

from plataforma.erros import (
    ErroAcessoNegado,
    ErroNaoEncontrado,
    ErroRegraDeNegocio,
    ErroRequisicaoInvalida,
)


class EnvelopeInvalido(ErroRequisicaoInvalida):
    codigo_padrao = "ENVELOPE_INVALIDO"
    mensagem_padrao = "Envelope de evento inválido."


class TipoDeEventoReservado(ErroAcessoNegado):
    codigo_padrao = "TIPO_DE_EVENTO_RESERVADO"
    mensagem_padrao = "Eventos deste tipo só podem ser publicados pelos serviços da Equipe 5."


class UrlDeWebhookInvalida(ErroRegraDeNegocio):
    codigo_padrao = "URL_DE_WEBHOOK_INVALIDA"
    mensagem_padrao = "URL de webhook inválida."


class PadraoDeEventoInvalido(ErroRegraDeNegocio):
    codigo_padrao = "PADRAO_DE_EVENTO_INVALIDO"
    mensagem_padrao = "Padrão de evento inválido."


class AssinaturaNaoEncontrada(ErroNaoEncontrado):
    codigo_padrao = "ASSINATURA_NAO_ENCONTRADA"
    mensagem_padrao = "Assinatura de webhook não encontrada."


class DadosDoEventoInsuficientes(ValueError):
    """O evento não traz um campo exigido pelo template (falha definitiva)."""


class TransicaoInvalida(ValueError):
    """Tentativa de alterar uma notificação que já foi finalizada."""
