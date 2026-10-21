from pagamentos.adaptadores.clientes.gateway_simulado import GatewaySimulado
from pagamentos.aplicacao.consultas import ConsultasPagamentos
from pagamentos.aplicacao.criar_pagamento import CriarPagamento
from pagamentos.aplicacao.estornar_pagamento import EstornarPagamento
from pagamentos.aplicacao.idempotencia import ExecutorIdempotente
from pagamentos.composicao import derivar_chave_hash, montar_casos_de_uso
from pagamentos.testes.fakes import ApresentadorFake, ConsultaPedidosFake, EstadoFake, fabrica_fake


def test_chave_hash_e_deterministica_e_depende_do_segredo() -> None:
    chave = derivar_chave_hash("s" * 32)
    assert chave == derivar_chave_hash("s" * 32)
    assert len(chave) == 32
    assert chave != derivar_chave_hash("t" * 32)
    assert chave != ("s" * 32).encode()


def test_monta_os_casos_de_uso() -> None:
    apresentador = ApresentadorFake()
    casos = montar_casos_de_uso(
        fabrica_uow=fabrica_fake(EstadoFake()),
        pedidos=ConsultaPedidosFake(),
        gateway=GatewaySimulado(),
        apresentador=apresentador,
        segredo="s" * 32,
    )
    assert casos.apresentador is apresentador
    assert isinstance(casos.idempotencia, ExecutorIdempotente)
    assert isinstance(casos.criar_pagamento, CriarPagamento)
    assert isinstance(casos.estornar_pagamento, EstornarPagamento)
    assert isinstance(casos.consultas, ConsultasPagamentos)
