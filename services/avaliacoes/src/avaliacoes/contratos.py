"""Gera/verifica ``docs/openapi/avaliacoes.json`` e ``docs/asyncapi/avaliacoes.json``.

Uso (na raiz do repositório)::

    uv run python -m avaliacoes.contratos             # regrava os arquivos
    uv run python -m avaliacoes.contratos --verificar # CI: falha se divergirem
"""

import argparse
from pathlib import Path

from pydantic import SecretStr

from avaliacoes.adaptadores.mensageria.especificacao import criar_broker_documentado
from avaliacoes.api import TITULO, VERSAO, criar_app
from avaliacoes.config import Config
from plataforma.contratos import asyncapi_json, openapi_json, sincronizar_contratos

NOME = "avaliacoes"


def artefatos(raiz: Path) -> dict[Path, str]:
    config = Config(token_servico_segredo=SecretStr("contratos-" + "x" * 32), log_nivel="WARNING")
    return {
        raiz / "docs" / "openapi" / f"{NOME}.json": openapi_json(criar_app(config)),
        raiz / "docs" / "asyncapi" / f"{NOME}.json": asyncapi_json(
            criar_broker_documentado(), titulo=f"{TITULO} (eventos)", versao=VERSAO
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verificar", action="store_true", help="só compara (uso no CI)")
    parser.add_argument("--raiz", type=Path, default=Path.cwd(), help="raiz do repositório")
    argumentos = parser.parse_args(argv)
    return sincronizar_contratos(artefatos(argumentos.raiz), verificar=argumentos.verificar)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
