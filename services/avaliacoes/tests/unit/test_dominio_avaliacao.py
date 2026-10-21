from datetime import UTC, datetime

import pytest

from avaliacoes.dominio.avaliacao import Avaliacao, exigir_pedido_avaliavel
from avaliacoes.dominio.erros import AvaliacaoInvalida, PedidoDeOutroCliente, PedidoNaoEntregue

AGORA = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def _registrar(**alteracoes: object) -> Avaliacao:
    dados: dict[str, object] = {
        "pedido_id": "ped-4",
        "cliente_id": "cliente-1",
        "restaurante_id": "rest-1",
        "nota_restaurante": 5,
        "nota_entrega": 4,
        "comentario": "  Chegou quente.  ",
        "agora": AGORA,
    }
    dados.update(alteracoes)
    return Avaliacao.registrar(**dados)  # type: ignore[arg-type]


def test_registrar_copia_dados_e_normaliza_comentario() -> None:
    avaliacao = _registrar()
    assert avaliacao.pedido_id == "ped-4"
    assert avaliacao.restaurante_id == "rest-1"
    assert avaliacao.comentario == "Chegou quente."
    assert avaliacao.criado_em == AGORA


def test_nota_entrega_e_comentario_sao_opcionais() -> None:
    avaliacao = _registrar(nota_entrega=None, comentario="   ")
    assert avaliacao.nota_entrega is None
    assert avaliacao.comentario is None


@pytest.mark.parametrize("nota", [0, 6, -1, True])
def test_nota_restaurante_fora_da_faixa(nota: int) -> None:
    with pytest.raises(AvaliacaoInvalida) as erro:
        _registrar(nota_restaurante=nota)
    assert erro.value.status_http == 422
    assert erro.value.detalhes == {"campo": "nota_restaurante"}


def test_nota_entrega_fora_da_faixa() -> None:
    with pytest.raises(AvaliacaoInvalida):
        _registrar(nota_entrega=6)


def test_comentario_com_mais_de_1000_caracteres() -> None:
    assert _registrar(comentario="x" * 1000).comentario == "x" * 1000
    with pytest.raises(AvaliacaoInvalida):
        _registrar(comentario="x" * 1001)


def test_pedido_avaliavel_exige_dono_e_entrega() -> None:
    exigir_pedido_avaliavel(cliente_do_pedido="cliente-1", entregue=True, cliente_id="cliente-1")
    with pytest.raises(PedidoDeOutroCliente) as outro:
        exigir_pedido_avaliavel(
            cliente_do_pedido="cliente-2", entregue=True, cliente_id="cliente-1"
        )
    assert outro.value.status_http == 403
    with pytest.raises(PedidoNaoEntregue) as nao_entregue:
        exigir_pedido_avaliavel(
            cliente_do_pedido="cliente-1", entregue=False, cliente_id="cliente-1"
        )
    assert nao_entregue.value.codigo == "PEDIDO_NAO_ENTREGUE"
