from notificacoes.dominio.assinatura_hmac import (
    assinar,
    assinatura_valida,
    cabecalhos_da_entrega,
    gerar_segredo,
)


def test_assinar_vetor_conhecido() -> None:
    # HMAC-SHA256(b"segredo-teste", b'1760000000.{"a":1}'), calculado à parte
    esperado = "sha256=bc1c8f5bb67075789025f455f564d228de58c4b6614409ded036d697efa22a5e"
    assert assinar("segredo-teste", 1760000000, b'{"a":1}') == esperado


def test_assinatura_valida_aceita_e_rejeita() -> None:
    corpo = b'{"a":1}'
    recebida = assinar("s", 100, corpo)
    assert assinatura_valida("s", 100, corpo, recebida, agora=150)
    assert not assinatura_valida("outro", 100, corpo, recebida, agora=150)
    assert not assinatura_valida("s", 100, corpo + b" ", recebida, agora=150)
    assert not assinatura_valida("s", 100, corpo, recebida, agora=100 + 301)


def test_cabecalhos_da_entrega() -> None:
    cabecalhos = cabecalhos_da_entrega(
        segredo="s", timestamp=100, corpo=b"{}", evento_id="id-1", evento_tipo="pagamento.aprovado"
    )
    assert cabecalhos == {
        "Content-Type": "application/json",
        "X-Assinatura": assinar("s", 100, b"{}"),
        "X-Assinatura-Timestamp": "100",
        "X-Evento-Id": "id-1",
        "X-Evento-Tipo": "pagamento.aprovado",
    }


def test_gerar_segredo_e_longo_e_aleatorio() -> None:
    primeiro, segundo = gerar_segredo(), gerar_segredo()
    assert primeiro != segundo
    assert len(primeiro) >= 40
