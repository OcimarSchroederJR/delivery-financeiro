from pathlib import Path

import pagamentos
from plataforma.testes.isolamento import importacoes_de_testes


def test_codigo_de_producao_nao_importa_testes() -> None:
    """A imagem de produção apaga pagamentos/testes e plataforma/testes (ver o Dockerfile)."""
    assert importacoes_de_testes(Path(pagamentos.__file__).parent) == []
