"""Erros de negócio do serviço de Pagamentos (spec §4.1).

Herdam das exceções da plataforma (Python puro), que carregam status HTTP,
código e detalhes; o tratador global da API os converte no formato de erro.
"""

from uuid import UUID

from plataforma.erros import (
    ErroAcessoNegado,
    ErroConflito,
    ErroNaoEncontrado,
    ErroRegraDeNegocio,
    ErroRequisicaoInvalida,
)


class PagamentoNaoEncontrado(ErroNaoEncontrado):
    codigo_padrao = "PAGAMENTO_NAO_ENCONTRADO"
    mensagem_padrao = "Pagamento não encontrado."


class PedidoInexistente(ErroRegraDeNegocio):
    codigo_padrao = "PEDIDO_INEXISTENTE"
    mensagem_padrao = "O pedido informado não existe."


class PedidoDeOutroCliente(ErroAcessoNegado):
    mensagem_padrao = "O pedido pertence a outro cliente."


class PedidoCancelado(ErroRegraDeNegocio):
    codigo_padrao = "PEDIDO_CANCELADO"
    mensagem_padrao = "O pedido está cancelado e não pode ser pago."


class PedidoSemValor(ErroRegraDeNegocio):
    codigo_padrao = "PEDIDO_SEM_VALOR"
    mensagem_padrao = "O pedido não tem valor a pagar."


class PedidoJaPago(ErroConflito):
    codigo_padrao = "PEDIDO_JA_PAGO"
    mensagem_padrao = "O pedido já possui um pagamento aprovado."


class PagamentoRecusado(ErroConflito):
    codigo_padrao = "PAGAMENTO_RECUSADO"
    mensagem_padrao = "Pagamento recusado."

    def __init__(self, pagamento_id: UUID, motivo: str) -> None:
        super().__init__(detalhes={"pagamento_id": str(pagamento_id), "motivo": motivo})
        self.pagamento_id = pagamento_id
        self.motivo = motivo


class PagamentoNaoEstornavel(ErroConflito):
    codigo_padrao = "PAGAMENTO_NAO_ESTORNAVEL"
    mensagem_padrao = "O pagamento não pode ser estornado (recusado ou totalmente estornado)."


class ValorExcedeSaldoEstornavel(ErroRegraDeNegocio):
    codigo_padrao = "VALOR_EXCEDE_SALDO_ESTORNAVEL"
    mensagem_padrao = "O valor solicitado excede o saldo estornável do pagamento."

    def __init__(self, saldo_estornavel_centavos: int) -> None:
        super().__init__(detalhes={"saldo_estornavel_centavos": saldo_estornavel_centavos})
        self.saldo_estornavel_centavos = saldo_estornavel_centavos


class ValorDeEstornoInvalido(ErroRegraDeNegocio):
    codigo_padrao = "VALOR_DE_ESTORNO_INVALIDO"
    mensagem_padrao = "O valor do estorno deve ser maior que zero."


class IdempotencyKeyAusente(ErroRequisicaoInvalida):
    codigo_padrao = "IDEMPOTENCY_KEY_AUSENTE"
    mensagem_padrao = "O header Idempotency-Key é obrigatório nesta operação."


class IdempotencyKeyInvalida(ErroRequisicaoInvalida):
    codigo_padrao = "IDEMPOTENCY_KEY_INVALIDA"
    mensagem_padrao = "O header Idempotency-Key deve ter de 1 a 255 caracteres ASCII visíveis."


class IdempotencyKeyReutilizada(ErroRegraDeNegocio):
    codigo_padrao = "IDEMPOTENCY_KEY_REUTILIZADA"
    mensagem_padrao = "Esta Idempotency-Key já foi usada com outro corpo de requisição."


class IdempotencyEmProcessamento(ErroConflito):
    codigo_padrao = "IDEMPOTENCY_EM_PROCESSAMENTO"
    mensagem_padrao = "Uma requisição com esta Idempotency-Key ainda está em processamento."
