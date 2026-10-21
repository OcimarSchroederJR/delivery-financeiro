"""Regra de dependência da spec §3.7, verificada pelos imports de cada camada."""

import ast
import sys
from pathlib import Path

import pytest

PACOTE = Path(__file__).resolve().parents[2] / "src" / "pagamentos"
PERMITIDOS: dict[str, tuple[str, ...]] = {
    "dominio": ("pagamentos.dominio", "plataforma.erros"),
    "aplicacao": (
        "pagamentos.dominio",
        "pagamentos.aplicacao",
        "plataforma.erros",
        "plataforma.tempo",
        "plataforma.logs",
    ),
}


def _importacoes(arquivo: Path) -> set[str]:
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
    nomes: set[str] = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            nomes.update(apelido.name for apelido in no.names)
        elif isinstance(no, ast.ImportFrom) and no.module and no.level == 0:
            nomes.add(no.module)
    return nomes


@pytest.mark.parametrize("camada", sorted(PERMITIDOS))
def test_camada_so_importa_o_permitido(camada: str) -> None:
    arquivos = sorted((PACOTE / camada).rglob("*.py"))
    assert arquivos
    violacoes = [
        f"{arquivo.name}: {nome}"
        for arquivo in arquivos
        for nome in sorted(_importacoes(arquivo))
        if nome.split(".")[0] not in sys.stdlib_module_names
        and not nome.startswith(PERMITIDOS[camada])
    ]
    assert violacoes == []
