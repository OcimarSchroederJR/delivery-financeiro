import re
import tomllib
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[4]


def _exclusoes() -> list[re.Pattern[str]]:
    configuracao = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    return [
        re.compile(padrao) for padrao in configuracao["tool"]["coverage"]["report"]["exclude_also"]
    ]


def test_exclusao_de_cobertura_nao_pega_assinatura_com_reticencias() -> None:
    assinatura = "def exigir_papeis(*papeis: Papel) -> Callable[..., Awaitable[Usuario]]:"
    assert not any(padrao.search(assinatura) for padrao in _exclusoes())


def test_exclusao_de_cobertura_pega_corpo_so_com_reticencias() -> None:
    assert any(padrao.search("    ...") for padrao in _exclusoes())
