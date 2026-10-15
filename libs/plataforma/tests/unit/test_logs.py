import json
import logging

import pytest

from plataforma.correlation import correlation_id_em
from plataforma.logs import REDIGIDO, configurar_logs, obter_logger, redigir_dados_sensiveis

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJh"


def _linhas_json(saida: str) -> list[dict[str, object]]:
    return [json.loads(linha) for linha in saida.splitlines() if linha.strip()]


def test_json_tem_campos_fixos(capsys: pytest.CaptureFixture[str]) -> None:
    configurar_logs("pagamentos", formato="json")
    with correlation_id_em("cid-123"):
        obter_logger("teste").info("algo_aconteceu", valor_centavos=4590)
    linha = _linhas_json(capsys.readouterr().out)[-1]
    assert linha["evento"] == "algo_aconteceu"
    assert linha["nivel"] == "info"
    assert linha["servico"] == "pagamentos"
    assert linha["correlation_id"] == "cid-123"
    assert "trace_id" in linha
    assert linha["valor_centavos"] == 4590


def test_redige_chaves_sensiveis_aninhadas() -> None:
    evento = redigir_dados_sensiveis(
        None,
        "info",
        {
            "event": "x",
            "cartao": {"numero": "4111111111110000", "cvv": "123"},
            "corpo": {"segredo": "abc", "cvv": "999", "ok": "mantido"},
            "Authorization": "Bearer abc.def",
        },
    )
    assert evento["cartao"] == REDIGIDO
    assert evento["corpo"] == {"segredo": REDIGIDO, "cvv": REDIGIDO, "ok": "mantido"}
    assert evento["Authorization"] == REDIGIDO


@pytest.mark.parametrize(
    "texto",
    [
        "cartao 4111111111110000 recusado",
        f"token {JWT} expirado",
        "header Authorization: Bearer qualquer.coisa.aqui",
    ],
)
def test_redige_padroes_em_texto_livre(texto: str) -> None:
    evento = redigir_dados_sensiveis(None, "info", {"event": texto, "lista": [texto]})
    for valor in (evento["event"], evento["lista"][0]):
        assert "4111111111110000" not in valor
        assert JWT not in valor
        assert "qualquer.coisa.aqui" not in valor
        assert REDIGIDO in valor


def test_nao_redige_ids_hexadecimais_com_muitos_digitos() -> None:
    trace_id = "2fa3712345678901234aad92c04cfb791e"
    evento = redigir_dados_sensiveis(None, "info", {"event": "x", "trace_id": trace_id})
    assert evento["trace_id"] == trace_id


def test_excecao_com_dado_sensivel_e_redigida_no_json(capsys: pytest.CaptureFixture[str]) -> None:
    configurar_logs("pagamentos", formato="json")
    try:
        raise ValueError("cartao 4111111111110000 invalido")
    except ValueError:
        obter_logger("teste").exception("falhou")
    saida = capsys.readouterr().out
    assert "4111111111110000" not in saida
    assert "ValueError" in saida


def test_console_nao_mostra_variaveis_locais_nem_dados_sensiveis(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configurar_logs("pagamentos", formato="console")
    numero_cartao_local = "4111111111110000"  # noqa: F841 - não pode aparecer no traceback
    try:
        raise RuntimeError("falha generica")
    except RuntimeError:
        obter_logger("teste").exception("falhou")
    saida = capsys.readouterr().out
    assert "4111111111110000" not in saida
    assert "falha generica" in saida


def test_logs_de_bibliotecas_passam_pela_redacao(capsys: pytest.CaptureFixture[str]) -> None:
    configurar_logs("notificacoes", formato="json")
    logging.getLogger("biblioteca.qualquer").warning("token %s vazou", JWT)
    linha = _linhas_json(capsys.readouterr().out)[-1]
    assert JWT not in json.dumps(linha)
    assert linha["servico"] == "notificacoes"


def test_nivel_filtra_mensagens(capsys: pytest.CaptureFixture[str]) -> None:
    configurar_logs("avaliacoes", formato="json", nivel="WARNING")
    obter_logger("teste").info("invisivel")
    obter_logger("teste").warning("visivel")
    eventos = [linha["evento"] for linha in _linhas_json(capsys.readouterr().out)]
    assert eventos == ["visivel"]
