from typing import Any

import pytest

from notificacoes.adaptadores.memoria import ArmazenamentoEmMemoria, UnidadeDeTrabalhoEmMemoria
from notificacoes.aplicacao.eventos_externos import (
    interpretar_corpo,
    receber_evento_externo,
    validar_envelope,
)
from notificacoes.dominio.erros import (
    EnvelopeInvalido,
    TipoDeEventoNaoPermitido,
    TipoDeEventoReservado,
)
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
    primeiro = await receber_evento_externo(
        UnidadeDeTrabalhoEmMemoria(armazenamento), dados, papel="entregador"
    )
    segundo = await receber_evento_externo(
        UnidadeDeTrabalhoEmMemoria(armazenamento), dados, papel="entregador"
    )
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
            UnidadeDeTrabalhoEmMemoria(armazenamento), _envelope(tipo=tipo), papel="admin"
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
        await receber_evento_externo(
            UnidadeDeTrabalhoEmMemoria(ArmazenamentoEmMemoria()), dados, papel="admin"
        )
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


@pytest.mark.parametrize(
    "corpo",
    [
        rb'{"dados": {"a\u0000": 1}}',
        rb'{"dados": {"a": "x\u0000y"}}',
        rb'{"dados": {"lista": [{"b": ["\u0000"]}]}}',
        rb'{"tipo\u0000": "a.b"}',
    ],
)
def test_caractere_nulo_e_recusado_em_qualquer_lugar(corpo: bytes) -> None:
    # O Postgres não guarda \u0000 em JSONB nem em texto
    with pytest.raises(EnvelopeInvalido) as erro:
        interpretar_corpo(corpo)
    assert erro.value.status_http == 400


def test_barra_invertida_seguida_de_u0000_literal_e_aceita() -> None:
    assert interpretar_corpo(rb'{"dados": {"a": "\\u0000"}}') == {"dados": {"a": "\\u0000"}}


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("cliente_id", "c" * 129),
        ("pedido_id", "ped-1\nBcc: vitima@exemplo.com"),
        ("entregador_id", "ent\r1"),
        ("pedido_id", "ped\x00"),
        ("pedido_id", ""),
        ("cliente_id", 123),
    ],
)
def test_ids_dos_dados_precisam_caber_no_banco_e_nao_ter_controle(
    campo: str, valor: object
) -> None:
    dados = {"pedido_id": "ped-3", "cliente_id": "cliente-2", campo: valor}
    with pytest.raises(EnvelopeInvalido) as erro:
        validar_envelope(_envelope(dados=dados))
    assert erro.value.status_http == 400
    assert erro.value.detalhes["detalhes"][0]["campo"] == f"dados.{campo}"
    if isinstance(valor, str) and valor:
        assert valor not in str(erro.value.detalhes)  # não ecoa a entrada


def test_id_com_128_caracteres_e_aceito() -> None:
    envelope = validar_envelope(_envelope(dados={"cliente_id": "c" * 128, "pedido_id": "p"}))
    assert envelope.dados["cliente_id"] == "c" * 128


@pytest.mark.parametrize(
    ("papel", "tipo", "permitido"),
    [
        ("entregador", "entrega.concluida", True),
        ("entregador", "pedido.criado", False),
        ("loja", "pedido.criado", True),
        ("loja", "entrega.concluida", False),
        ("admin", "qualquer.coisa", True),
        ("cliente", "pedido.criado", False),
    ],
)
async def test_tipos_permitidos_por_papel(papel: str, tipo: str, permitido: bool) -> None:
    armazenamento = ArmazenamentoEmMemoria()
    uow = UnidadeDeTrabalhoEmMemoria(armazenamento)
    if permitido:
        assert (await receber_evento_externo(uow, _envelope(tipo=tipo), papel=papel)).novo
        return
    with pytest.raises(TipoDeEventoNaoPermitido) as erro:
        await receber_evento_externo(uow, _envelope(tipo=tipo), papel=papel)
    assert (erro.value.status_http, erro.value.codigo) == (403, "TIPO_DE_EVENTO_NAO_PERMITIDO")
    assert erro.value.detalhes == {"tipo": tipo, "papel": papel}
    assert armazenamento.eventos_externos == {}


async def test_tipo_reservado_vence_a_regra_de_papel() -> None:
    with pytest.raises(TipoDeEventoReservado):
        await receber_evento_externo(
            UnidadeDeTrabalhoEmMemoria(ArmazenamentoEmMemoria()),
            _envelope(tipo="pagamento.aprovado"),
            papel="entregador",
        )
