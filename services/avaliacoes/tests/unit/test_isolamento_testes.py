from pathlib import Path

import avaliacoes
from plataforma.testes.isolamento import importacoes_de_testes


def test_codigo_de_producao_nao_importa_testes() -> None:
    """A imagem de produção apaga avaliacoes/testes e plataforma/testes (ver o Dockerfile)."""
    assert importacoes_de_testes(Path(avaliacoes.__file__).parent) == []
