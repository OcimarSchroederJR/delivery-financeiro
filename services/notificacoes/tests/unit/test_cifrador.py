import pytest

from notificacoes.adaptadores.cifrador import CifradorFernet, SegredoIlegivel

TEXTO = "segredo-do-webhook"


def test_cifra_e_decifra() -> None:
    cifrador = CifradorFernet.de_segredo("x" * 32)
    cifrado = cifrador.cifrar(TEXTO)
    assert cifrado != TEXTO
    assert cifrado.startswith("gAAAA")
    assert cifrador.decifrar(cifrado) == TEXTO


def test_mesmo_texto_gera_cifras_diferentes() -> None:
    cifrador = CifradorFernet.de_segredo("x" * 32)
    assert cifrador.cifrar(TEXTO) != cifrador.cifrar(TEXTO)


def test_chave_errada_nao_decifra() -> None:
    cifrado = CifradorFernet.de_segredo("x" * 32).cifrar(TEXTO)
    with pytest.raises(SegredoIlegivel):
        CifradorFernet.de_segredo("y" * 32).decifrar(cifrado)


def test_chave_derivada_e_estavel_entre_processos() -> None:
    cifrado = CifradorFernet.de_segredo("x" * 32).cifrar(TEXTO)
    assert CifradorFernet.de_segredo("x" * 32).decifrar(cifrado) == TEXTO
