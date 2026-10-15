import json
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

from plataforma.contratos import asyncapi_json, openapi_json, sincronizar_contratos
from plataforma.mensageria import EXCHANGE_EVENTOS, criar_broker_especificacao


def test_openapi_json_estavel() -> None:
    app = FastAPI(title="X", version="1.0.0")
    texto = openapi_json(app)
    assert texto.endswith("\n")
    assert json.loads(texto)["info"] == {"title": "X", "version": "1.0.0"}
    assert openapi_json(app) == texto


def test_asyncapi_json_lista_publicacoes_declaradas_sem_credenciais() -> None:
    class DadosPagamentoAprovado(BaseModel):
        pagamento_id: str

    broker = criar_broker_especificacao("Eventos de teste")
    broker.publisher(
        routing_key="pagamento.aprovado",
        exchange=EXCHANGE_EVENTOS,
        title="pagamento.aprovado",
        schema=DadosPagamentoAprovado,
    )
    documento = json.loads(asyncapi_json(broker, titulo="Teste", versao="1.0.0"))
    assert documento["info"]["title"] == "Teste"
    assert "pagamento.aprovado" in documento["channels"]
    assert "guest" not in json.dumps(documento)


def test_sincronizar_escreve_e_depois_verifica(tmp_path: Path) -> None:
    arquivo = tmp_path / "docs" / "openapi" / "x.json"
    assert sincronizar_contratos({arquivo: "{}\n"}, verificar=True) == 1
    assert sincronizar_contratos({arquivo: "{}\n"}, verificar=False) == 0
    assert arquivo.read_text(encoding="utf-8") == "{}\n"
    assert sincronizar_contratos({arquivo: "{}\n"}, verificar=True) == 0
    assert sincronizar_contratos({arquivo: '{"a": 1}\n'}, verificar=True) == 1
