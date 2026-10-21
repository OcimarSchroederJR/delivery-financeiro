from datetime import UTC, datetime, timedelta

import pytest

from pagamentos.dominio.erros import IdempotencyKeyAusente, IdempotencyKeyInvalida
from pagamentos.dominio.idempotencia import (
    TEMPO_MAXIMO_PROCESSAMENTO,
    VALIDADE,
    Decisao,
    RegistroIdempotencia,
    StatusChave,
    calcular_hash,
    validar_chave,
)

AGORA = datetime(2026, 10, 14, 14, 30, tzinfo=UTC)
CHAVE_HASH = b"segredo-de-hash-0123456789abcdef"


def _registro(
    status: StatusChave = StatusChave.CONCLUIDA, criado_em: datetime = AGORA
) -> RegistroIdempotencia:
    concluida = status == StatusChave.CONCLUIDA
    return RegistroIdempotencia(
        escopo="POST /v1/pagamentos",
        chave="k-1",
        hash_requisicao="h1",
        status=status,
        criado_em=criado_em,
        status_resposta=201 if concluida else None,
        corpo_resposta={"id": "p1"} if concluida else None,
    )


def test_hash_nao_depende_da_ordem_das_chaves() -> None:
    a = calcular_hash({"a": 1, "b": {"c": 2, "d": "é"}}, chave=CHAVE_HASH)
    b = calcular_hash({"b": {"d": "é", "c": 2}, "a": 1}, chave=CHAVE_HASH)
    assert a == b


def test_hash_muda_com_o_corpo_e_com_a_chave_secreta() -> None:
    base = calcular_hash({"a": 1}, chave=CHAVE_HASH)
    assert calcular_hash({"a": 2}, chave=CHAVE_HASH) != base
    assert calcular_hash({"a": 1}, chave=b"outra-chave-secreta-0123456789ab") != base


def test_hash_e_hexadecimal_de_64_caracteres() -> None:
    resultado = calcular_hash({"numero": "4111111111110000"}, chave=CHAVE_HASH)
    assert len(resultado) == 64
    int(resultado, 16)


def test_reservar_cria_registro_em_processamento() -> None:
    registro = RegistroIdempotencia.reservar(
        escopo="e", chave="k", hash_requisicao="h", agora=AGORA
    )
    assert registro.status == StatusChave.EM_PROCESSAMENTO
    assert registro.criado_em == AGORA
    assert (registro.status_resposta, registro.corpo_resposta) == (None, None)


def test_concluida_com_mesmo_corpo_repete_a_resposta() -> None:
    registro = _registro()
    assert registro.decidir("h1", AGORA + timedelta(hours=1)) is Decisao.REPETIR_RESPOSTA
    assert registro.resposta() == (201, {"id": "p1"})


def test_concluida_com_corpo_diferente() -> None:
    assert _registro().decidir("h2", AGORA) is Decisao.CORPO_DIFERENTE


def test_em_processamento_recente_bloqueia() -> None:
    registro = _registro(StatusChave.EM_PROCESSAMENTO)
    instante = AGORA + TEMPO_MAXIMO_PROCESSAMENTO - timedelta(seconds=1)
    assert registro.decidir("h1", instante) is Decisao.EM_PROCESSAMENTO


def test_em_processamento_abandonado_pode_ser_reassumido() -> None:
    registro = _registro(StatusChave.EM_PROCESSAMENTO)
    assert timedelta(seconds=60) == TEMPO_MAXIMO_PROCESSAMENTO
    assert registro.decidir("h1", AGORA + TEMPO_MAXIMO_PROCESSAMENTO) is Decisao.PROCESSAR


def test_chave_vale_por_24_horas() -> None:
    registro = _registro()
    assert timedelta(hours=24) == VALIDADE
    assert not registro.expirado(AGORA + VALIDADE - timedelta(seconds=1))
    assert registro.expirado(AGORA + VALIDADE)
    assert registro.decidir("h1", AGORA + VALIDADE) is Decisao.PROCESSAR


def test_chave_expirada_aceita_corpo_diferente() -> None:
    assert _registro().decidir("h2", AGORA + VALIDADE) is Decisao.PROCESSAR


def test_resposta_de_registro_em_processamento_e_erro() -> None:
    with pytest.raises(ValueError, match="não concluída"):
        _registro(StatusChave.EM_PROCESSAMENTO).resposta()


@pytest.mark.parametrize("chave", ["k", "disputa-3f2a9c", "a" * 255, "A~!#$%"])
def test_chave_valida(chave: str) -> None:
    assert validar_chave(chave) == chave


@pytest.mark.parametrize("chave", [None, "", "   "])
def test_chave_ausente(chave: str | None) -> None:
    with pytest.raises(IdempotencyKeyAusente):
        validar_chave(chave)


@pytest.mark.parametrize("chave", ["a" * 256, "com espaco", "chave\u00e7", "tab\tchave"])
def test_chave_fora_do_formato(chave: str) -> None:
    with pytest.raises(IdempotencyKeyInvalida):
        validar_chave(chave)
