import json
import logging
from dataclasses import dataclass

import pytest
from pydantic import BaseModel

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


class CartaoModelo(BaseModel):
    numero: str
    cvv: str
    bandeira: str


@dataclass
class CartaoDataclass:
    numero: str
    cvv: str
    bandeira: str


class ObjetoQualquer:
    def __str__(self) -> str:
        return "objeto com cartao 4111111111110000"


@pytest.mark.parametrize(
    "objeto",
    [
        CartaoModelo(numero="4111111111110000", cvv="123", bandeira="visa"),
        CartaoDataclass(numero="4111111111110000", cvv="123", bandeira="visa"),
    ],
)
def test_redige_basemodel_e_dataclass(objeto: object) -> None:
    evento = redigir_dados_sensiveis(None, "info", {"event": "x", "pagamento": objeto})
    assert evento["pagamento"]["cvv"] == REDIGIDO
    assert evento["pagamento"]["bandeira"] == "visa"
    assert "4111111111110000" not in str(evento)


def test_redige_objeto_arbitrario_pelo_texto() -> None:
    evento = redigir_dados_sensiveis(None, "info", {"event": "x", "obj": ObjetoQualquer()})
    assert "4111111111110000" not in str(evento)
    assert REDIGIDO in evento["obj"]


def test_redige_numero_de_cartao_inteiro() -> None:
    evento = redigir_dados_sensiveis(None, "info", {"event": "x", "numero": 4111111111110000})
    assert evento["numero"] == REDIGIDO


@pytest.mark.parametrize("numero", ["4111 1111 1111 1111", "4111-1111-1111-1111"])
def test_redige_cartao_com_separadores(numero: str) -> None:
    evento = redigir_dados_sensiveis(None, "info", {"event": f"cartao {numero} recusado"})
    assert numero not in evento["event"]
    assert evento["event"] == f"cartao {REDIGIDO} recusado"


@pytest.mark.parametrize(
    "identificador",
    [
        "12345678-1234-1234-1234-123456789012",
        "550e8400-e29b-41d4-a716-446655440000",
        "pedido-1234567890123",
    ],
)
def test_nao_redige_uuids_e_ids_com_hifen(identificador: str) -> None:
    evento = redigir_dados_sensiveis(None, "info", {"event": "x", "id": identificador})
    assert evento["id"] == identificador


def test_json_com_basemodel_nao_vaza_cartao(capsys: pytest.CaptureFixture[str]) -> None:
    configurar_logs("pagamentos", formato="json")
    modelo = CartaoModelo(numero="4111 1111 1111 1111", cvv="123", bandeira="visa")
    obter_logger("teste").info("pagamento_recebido", pagamento=modelo)
    saida = capsys.readouterr().out
    assert "4111" not in saida
    assert '"cvv": "***"' in saida


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
