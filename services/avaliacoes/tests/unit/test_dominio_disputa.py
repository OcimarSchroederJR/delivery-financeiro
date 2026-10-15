from datetime import UTC, datetime, timedelta

import pytest

from avaliacoes.dominio.disputa import Decisao, Disputa, MotivoDisputa, StatusDisputa
from avaliacoes.dominio.erros import (
    DisputaInvalida,
    TransicaoInvalida,
    ValorAprovadoInvalido,
    ValorExcedePago,
)

AGORA = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
DEPOIS = AGORA + timedelta(minutes=1)


def _abrir(valor: int = 1000, pago: int = 3200, descricao: str | None = None) -> Disputa:
    return Disputa.abrir(
        pedido_id="ped-4",
        pagamento_id="pag-1",
        cliente_id="cliente-1",
        motivo=MotivoDisputa.ITEM_FALTANDO,
        descricao=descricao,
        valor_solicitado_centavos=valor,
        valor_pago_centavos=pago,
        agora=AGORA,
    )


def _pendente(valor_aprovado: int | None = None) -> Disputa:
    disputa = _abrir()
    disputa.aprovar(
        valor_aprovado_centavos=valor_aprovado,
        parecer="ok",
        agora=DEPOIS,
        primeira_tentativa_em=DEPOIS + timedelta(seconds=30),
    )
    return disputa


def test_abrir_cria_disputa_aberta() -> None:
    disputa = _abrir(descricao="  faltou a bebida ")
    assert disputa.status is StatusDisputa.ABERTA
    assert disputa.descricao == "faltou a bebida"
    assert disputa.tentativas_estorno == 0
    assert disputa.decisao is None
    assert not disputa.terminal
    assert disputa.chave_idempotencia_estorno == f"disputa-{disputa.id}"


def test_valor_igual_ao_pago_e_aceito_e_acima_e_recusado() -> None:
    assert _abrir(valor=3200).valor_solicitado_centavos == 3200
    with pytest.raises(ValorExcedePago) as erro:
        _abrir(valor=3201)
    assert erro.value.status_http == 422
    assert erro.value.detalhes == {"valor_pago_centavos": 3200}


@pytest.mark.parametrize("valor", [0, -5])
def test_valor_solicitado_deve_ser_positivo(valor: int) -> None:
    with pytest.raises(DisputaInvalida):
        _abrir(valor=valor)


def test_descricao_longa_e_recusada() -> None:
    with pytest.raises(DisputaInvalida):
        _abrir(descricao="x" * 2001)


def test_improcedente_e_terminal_com_valor_zero() -> None:
    disputa = _abrir()
    disputa.julgar_improcedente(parecer="sem provas", valor_aprovado_centavos=None, agora=DEPOIS)
    assert disputa.status is StatusDisputa.IMPROCEDENTE
    assert disputa.valor_aprovado_centavos == 0
    assert disputa.decisao is Decisao.IMPROCEDENTE
    assert disputa.terminal
    assert disputa.atualizado_em == DEPOIS


def test_improcedente_nao_aceita_valor_aprovado() -> None:
    with pytest.raises(ValorAprovadoInvalido):
        _abrir().julgar_improcedente(parecer=None, valor_aprovado_centavos=10, agora=DEPOIS)


def test_aprovar_sem_valor_usa_o_solicitado() -> None:
    disputa = _pendente()
    assert disputa.status is StatusDisputa.ESTORNO_PENDENTE
    assert disputa.valor_aprovado_centavos == 1000
    assert disputa.valor_a_estornar() == 1000
    assert disputa.proxima_tentativa_em == DEPOIS + timedelta(seconds=30)
    assert disputa.decisao is Decisao.PROCEDENTE


@pytest.mark.parametrize("valor", [0, 1001])
def test_aprovar_com_valor_invalido(valor: int) -> None:
    disputa = _abrir()
    with pytest.raises(ValorAprovadoInvalido):
        disputa.aprovar(
            valor_aprovado_centavos=valor, parecer=None, agora=DEPOIS, primeira_tentativa_em=DEPOIS
        )
    assert disputa.status is StatusDisputa.ABERTA


def test_concluir_estorno_resolve() -> None:
    disputa = _pendente(valor_aprovado=700)
    disputa.contar_tentativa()
    disputa.concluir_estorno(estorno_id="est-1", agora=DEPOIS)
    assert disputa.status is StatusDisputa.RESOLVIDA
    assert disputa.estorno_id == "est-1"
    assert disputa.tentativas_estorno == 1
    assert disputa.proxima_tentativa_em is None


def test_adiar_e_falhar_estorno() -> None:
    disputa = _pendente()
    disputa.adiar_estorno(proxima_tentativa_em=DEPOIS + timedelta(seconds=5), agora=DEPOIS)
    assert disputa.proxima_tentativa_em == DEPOIS + timedelta(seconds=5)
    disputa.falhar_estorno(motivo="PAGAMENTO_NAO_ESTORNAVEL", agora=DEPOIS)
    assert disputa.status is StatusDisputa.ESTORNO_FALHOU
    assert disputa.motivo_falha_estorno == "PAGAMENTO_NAO_ESTORNAVEL"
    assert disputa.proxima_tentativa_em is None


@pytest.mark.parametrize(
    "operacao",
    [
        lambda d: d.julgar_improcedente(parecer=None, valor_aprovado_centavos=None, agora=DEPOIS),
        lambda d: d.aprovar(
            valor_aprovado_centavos=None, parecer=None, agora=DEPOIS, primeira_tentativa_em=DEPOIS
        ),
    ],
)
def test_decidir_disputa_ja_decidida_e_transicao_invalida(operacao: object) -> None:
    disputa = _pendente()
    with pytest.raises(TransicaoInvalida) as erro:
        operacao(disputa)  # type: ignore[operator]
    assert erro.value.status_http == 409
    assert erro.value.codigo == "TRANSICAO_INVALIDA"
    assert erro.value.detalhes == {"status_atual": "estorno_pendente"}


def test_operacoes_de_estorno_exigem_estorno_pendente() -> None:
    disputa = _abrir()
    with pytest.raises(TransicaoInvalida):
        disputa.contar_tentativa()
    with pytest.raises(TransicaoInvalida):
        disputa.concluir_estorno(estorno_id="x", agora=DEPOIS)
    with pytest.raises(TransicaoInvalida):
        disputa.falhar_estorno(motivo="x", agora=DEPOIS)
    with pytest.raises(TransicaoInvalida):
        disputa.adiar_estorno(proxima_tentativa_em=DEPOIS, agora=DEPOIS)
