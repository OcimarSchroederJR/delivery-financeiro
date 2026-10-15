from pathlib import Path

from avaliacoes.contratos import artefatos, main

RAIZ = Path(__file__).resolve().parents[4]


def test_contratos_versionados_estao_em_dia() -> None:
    assert main(["--verificar", "--raiz", str(RAIZ)]) == 0, (
        "Rode `uv run python -m avaliacoes.contratos` e versione docs/openapi e docs/asyncapi."
    )


def test_artefatos_geram_openapi_e_asyncapi(tmp_path: Path) -> None:
    arquivos = artefatos(tmp_path)
    assert {caminho.relative_to(tmp_path).as_posix() for caminho in arquivos} == {
        "docs/openapi/avaliacoes.json",
        "docs/asyncapi/avaliacoes.json",
    }
    assert main(["--raiz", str(tmp_path)]) == 0
    assert main(["--verificar", "--raiz", str(tmp_path)]) == 0
