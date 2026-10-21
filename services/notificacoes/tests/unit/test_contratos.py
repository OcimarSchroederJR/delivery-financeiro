import json
from pathlib import Path

from pydantic import SecretStr

from notificacoes.adaptadores.mensageria.especificacao import criar_broker_documentado
from notificacoes.api import criar_app
from notificacoes.config import Config
from notificacoes.contratos import artefatos, main
from plataforma.contratos import asyncapi_json, openapi_json

RAIZ = Path(__file__).resolve().parents[4]


def test_contratos_versionados_estao_em_dia() -> None:
    assert main(["--verificar", "--raiz", str(RAIZ)]) == 0, (
        "Rode `uv run python -m notificacoes.contratos` e versione docs/openapi e docs/asyncapi."
    )


def test_artefatos_geram_openapi_e_asyncapi(tmp_path: Path) -> None:
    arquivos = artefatos(tmp_path)
    assert {caminho.relative_to(tmp_path).as_posix() for caminho in arquivos} == {
        "docs/openapi/notificacoes.json",
        "docs/asyncapi/notificacoes.json",
    }
    assert main(["--raiz", str(tmp_path)]) == 0
    assert main(["--verificar", "--raiz", str(tmp_path)]) == 0


def test_asyncapi_documenta_filas_retry_dlq_e_eventos_externos() -> None:
    documento = json.loads(asyncapi_json(criar_broker_documentado(), titulo="x", versao="1"))
    assert {
        "notificacoes.eventos",
        "notificacoes.emails",
        "notificacoes.webhooks",
        "notificacoes.dlq",
        "notificacoes.emails.retry.1",
        "notificacoes.webhooks.retry.5",
        "financeiro.eventos (eventos externos)",
    } <= set(documento["channels"])


def test_openapi_documenta_as_rotas_da_spec() -> None:
    app = criar_app(Config(token_servico_segredo=SecretStr("contratos-" + "x" * 32)))
    caminhos = json.loads(openapi_json(app))["paths"]
    assert {
        "/v1/eventos",
        "/v1/webhooks",
        "/v1/webhooks/{assinatura_id}",
        "/v1/webhooks/{assinatura_id}/entregas",
        "/v1/notificacoes",
    } <= set(caminhos)
    assert {"202", "400", "401", "403"} <= set(caminhos["/v1/eventos"]["post"]["responses"])
    assert "204" in caminhos["/v1/webhooks/{assinatura_id}"]["delete"]["responses"]
