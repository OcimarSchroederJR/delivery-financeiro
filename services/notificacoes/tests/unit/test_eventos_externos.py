from typing import Any

import pytest

from notificacoes.adaptadores.memoria import ArmazenamentoEmMemoria, UnidadeDeTrabalhoEmMemoria
from notificacoes.aplicacao.eventos_externos import (
    interpretar_corpo,
    receber_evento_externo,
    validar_envelope,
)
from notificacoes.dominio.erros import EnvelopeInvalido, TipoDeEventoReservado
from plataforma.envelope import EnvelopeEvento


def _envelope(**mudancas: Any) -> dict[str, Any]:
    base = EnvelopeEvento.novo(
        "entrega.concluida",
        {"pedido_id": "ped-3", "cliente_id": "cliente-2"},
        correlation_id="cid-1",
    )
    return {**base.para_json(), **mudancas}


async def test_evento_novo_e_gravado_e_duplicata_detectada() -> None:
    armazenamento = ArmazenamentoEmMemoria()
    dados = _envelope()
    primeiro = await receber_evento_externo(UnidadeDeTrabalhoEmMemoria(armazenamento), dados)
    segundo = await receber_evento_externo(UnidadeDeTrabalhoEmMemoria(armazenamento), dados)
    assert primeiro.novo is True
    assert segundo.novo is False
    assert primeiro.mensagem_id == segundo.mensagem_id
    assert list(armazenamento.eventos_externos) == [primeiro.mensagem_id]


@pytest.mark.parametrize(
    "tipo",
    [
        "pagamento.aprovado",
        "disputa.resolvida",
        "avaliacao.registrada",
        "tarefa.email",
        "estorno.criado",
    ],
)
async def test_tipo_reservado_e_recusado(tipo: str) -> None:
    armazenamento = ArmazenamentoEmMemoria()
    with pytest.raises(TipoDeEventoReservado) as erro:
        await receber_evento_externo(
            UnidadeDeTrabalhoEmMemoria(armazenamento), _envelope(tipo=tipo)
        )
    assert erro.value.status_http == 403
    assert armazenamento.eventos_externos == {}


@pytest.mark.parametrize(
    "dados",
    [
        [],
        "texto",
        {},
        _envelope(tipo="SemPonto"),
        _envelope(mensagem_id="nao-uuid"),
        _envelope(ocorrido_em="2026-10-14T14:30:00"),
        _envelope(correlation_id=""),
    ],
)
async def test_envelope_invalido(dados: object) -> None:
    with pytest.raises(EnvelopeInvalido) as erro:
        await receber_evento_externo(UnidadeDeTrabalhoEmMemoria(ArmazenamentoEmMemoria()), dados)
    assert (erro.value.status_http, erro.value.codigo) == (400, "ENVELOPE_INVALIDO")


def test_detalhes_nao_ecoam_a_entrada() -> None:
    with pytest.raises(EnvelopeInvalido) as erro:
        validar_envelope(_envelope(mensagem_id="segredo-123"))
    detalhes = erro.value.detalhes["detalhes"]
    assert detalhes[0]["campo"] == "mensagem_id"
    assert "segredo-123" not in str(detalhes)


def test_interpretar_corpo() -> None:
    assert interpretar_corpo(b'{"a": 1}') == {"a": 1}
    for invalido in (b"{", b"\xff", b" " * (64 * 1024 + 1)):
        with pytest.raises(EnvelopeInvalido):
            interpretar_corpo(invalido)
