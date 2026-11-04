"""Guarda: código de produção não importa pacotes ``testes``.

As imagens de produção apagam os subpacotes ``testes`` (ver os Dockerfiles). Cada
pacote tem um teste que chama ``importacoes_de_testes`` sobre o próprio código, para
que uma importação esquecida falhe no CI, e não no boot do container.
"""

import ast
from pathlib import Path

PACOTE_DE_TESTES = "testes"


def _importados(arvore: ast.AST) -> list[str]:
    nomes: list[str] = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            nomes.extend(alias.name for alias in no.names)
        elif isinstance(no, ast.ImportFrom):
            base = "." * no.level + (no.module or "")
            nomes.append(base)
    return nomes


def _importa_testes(nome: str) -> bool:
    return PACOTE_DE_TESTES in nome.lstrip(".").split(".")


def importacoes_de_testes(raiz: Path) -> list[str]:
    """Lista ``"<arquivo>: <módulo>"`` para cada importação de ``testes`` fora de ``testes/``."""
    achados: set[str] = set()
    for arquivo in raiz.rglob("*.py"):
        relativo = arquivo.relative_to(raiz)
        if PACOTE_DE_TESTES in relativo.parts[:-1]:
            continue
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
        for nome in _importados(arvore):
            if _importa_testes(nome):
                achados.add(f"{relativo.as_posix()}: {nome}")
    return sorted(achados)
