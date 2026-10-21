"""Exportação e verificação de drift dos contratos OpenAPI e AsyncAPI (spec §8)."""

import json
import sys
from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI
from faststream.rabbit import RabbitBroker
from faststream.specification import AsyncAPI


def _json_estavel(dados: object) -> str:
    return json.dumps(dados, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def openapi_json(app: FastAPI) -> str:
    return _json_estavel(app.openapi())


def asyncapi_json(broker: RabbitBroker, *, titulo: str, versao: str) -> str:
    especificacao = AsyncAPI(broker, title=titulo, version=versao).to_specification()
    return _json_estavel(json.loads(especificacao.to_json()))


def sincronizar_contratos(artefatos: Mapping[Path, str], *, verificar: bool) -> int:
    """Escreve os artefatos ou, com ``verificar=True``, só compara.

    Retorna 0 se tudo está em dia; 1 se algum arquivo diverge (modo verificação).
    """
    divergentes: list[Path] = []
    for caminho, conteudo in artefatos.items():
        atual = caminho.read_text(encoding="utf-8") if caminho.exists() else None
        if atual == conteudo:
            continue
        if verificar:
            divergentes.append(caminho)
            continue
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(conteudo, encoding="utf-8", newline="\n")
        print(f"Contrato atualizado: {caminho}")
    for caminho in divergentes:
        print(f"Contrato desatualizado: {caminho}", file=sys.stderr)
    return 1 if divergentes else 0
