from plataforma.erros import ErroConflito, ErroDependenciaIndisponivel, ErroNaoEncontrado


def test_erro_usa_padroes_da_classe() -> None:
    erro = ErroNaoEncontrado()
    assert erro.status_http == 404
    assert erro.codigo == "RECURSO_NAO_ENCONTRADO"
    assert erro.mensagem == "Recurso não encontrado."


def test_erro_aceita_codigo_mensagem_e_detalhes() -> None:
    erro = ErroConflito("Pagamento recusado.", codigo="PAGAMENTO_RECUSADO", detalhes={"id": "p1"})
    assert (erro.status_http, erro.codigo) == (409, "PAGAMENTO_RECUSADO")
    assert erro.detalhes == {"id": "p1"}
    assert str(erro) == "Pagamento recusado."


def test_subclasse_de_servico_define_codigo_padrao() -> None:
    class PedidoJaPago(ErroConflito):
        codigo_padrao = "PEDIDO_JA_PAGO"
        mensagem_padrao = "O pedido já possui pagamento aprovado."

    assert PedidoJaPago().codigo == "PEDIDO_JA_PAGO"
    assert PedidoJaPago().status_http == 409


def test_dependencia_indisponivel_informa_dependencia() -> None:
    erro = ErroDependenciaIndisponivel("pedidos")
    assert erro.status_http == 503
    assert erro.codigo == "DEPENDENCIA_INDISPONIVEL"
    assert erro.dependencia == "pedidos"
    assert erro.detalhes == {"dependencia": "pedidos"}
