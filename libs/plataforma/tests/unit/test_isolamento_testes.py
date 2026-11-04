from pathlib import Path

import plataforma
from plataforma.testes.isolamento import importacoes_de_testes


def _escrever(raiz: Path, relativo: str, conteudo: str) -> None:
    arquivo = raiz / relativo
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(conteudo, encoding="utf-8")


def test_acha_importacoes_de_testes_fora_do_pacote_testes(tmp_path: Path) -> None:
    _escrever(tmp_path, "app.py", "from plataforma.testes.tokens import GeradorDeTokens\n")
    _escrever(tmp_path, "sub/modulo.py", "import servico.testes.fakes\n")
    _escrever(tmp_path, "relativo.py", "from .testes import fakes\n")
    _escrever(tmp_path, "pacote.py", "from servico import testes\nfrom . import testes\n")
    _escrever(tmp_path, "ok.py", "from plataforma.logs import obter_logger\nimport testesx\n")
    _escrever(tmp_path, "testes/fakes.py", "from plataforma.testes.tokens import X\n")
    assert importacoes_de_testes(tmp_path) == [
        "app.py: plataforma.testes.tokens",
        "pacote.py: .testes",
        "pacote.py: servico.testes",
        "relativo.py: .testes",
        "sub/modulo.py: servico.testes.fakes",
    ]


def test_codigo_de_producao_da_plataforma_nao_importa_testes() -> None:
    assert importacoes_de_testes(Path(plataforma.__file__).parent) == []
