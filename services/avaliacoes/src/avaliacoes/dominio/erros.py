"""Erros de negócio do serviço de Avaliações (viram o formato de erro padrão na API)."""

from plataforma.erros import ErroAcessoNegado, ErroConflito, ErroNaoEncontrado, ErroRegraDeNegocio


class AvaliacaoInvalida(ErroRegraDeNegocio):
    codigo_padrao = "AVALIACAO_INVALIDA"
    mensagem_padrao = "Dados da avaliação inválidos."


class AvaliacaoDuplicada(ErroConflito):
    codigo_padrao = "AVALIACAO_DUPLICADA"
    mensagem_padrao = "Este pedido já foi avaliado."


class AvaliacaoNaoEncontrada(ErroNaoEncontrado):
    codigo_padrao = "AVALIACAO_NAO_ENCONTRADA"
    mensagem_padrao = "Avaliação não encontrada."


class PedidoInexistente(ErroRegraDeNegocio):
    codigo_padrao = "PEDIDO_INEXISTENTE"
    mensagem_padrao = "O pedido informado não existe."


class PedidoNaoEntregue(ErroRegraDeNegocio):
    codigo_padrao = "PEDIDO_NAO_ENTREGUE"
    mensagem_padrao = "O pedido ainda não foi entregue."


class PedidoDeOutroCliente(ErroAcessoNegado):
    codigo_padrao = "PEDIDO_DE_OUTRO_CLIENTE"
    mensagem_padrao = "O pedido pertence a outro cliente."


class DisputaInvalida(ErroRegraDeNegocio):
    codigo_padrao = "DISPUTA_INVALIDA"
    mensagem_padrao = "Dados da disputa inválidos."


class PagamentoNaoEncontrado(ErroRegraDeNegocio):
    codigo_padrao = "PAGAMENTO_NAO_ENCONTRADO"
    mensagem_padrao = "Não há pagamento aprovado ou parcialmente estornado para este pedido."


class DisputaJaAberta(ErroConflito):
    codigo_padrao = "DISPUTA_JA_ABERTA"
    mensagem_padrao = "Já existe uma disputa em andamento para este pedido."


class ValorExcedePago(ErroRegraDeNegocio):
    codigo_padrao = "VALOR_EXCEDE_PAGO"
    mensagem_padrao = "O valor solicitado excede o valor pago."


class DisputaNaoEncontrada(ErroNaoEncontrado):
    codigo_padrao = "DISPUTA_NAO_ENCONTRADA"
    mensagem_padrao = "Disputa não encontrada."


class DisputaDeOutroCliente(ErroAcessoNegado):
    codigo_padrao = "DISPUTA_DE_OUTRO_CLIENTE"
    mensagem_padrao = "A disputa pertence a outro cliente."


class TransicaoInvalida(ErroConflito):
    codigo_padrao = "TRANSICAO_INVALIDA"
    mensagem_padrao = "A disputa não está em um estado que permita esta operação."


class ValorAprovadoInvalido(ErroRegraDeNegocio):
    codigo_padrao = "VALOR_APROVADO_INVALIDO"
    mensagem_padrao = "Valor aprovado inválido para esta decisão."
