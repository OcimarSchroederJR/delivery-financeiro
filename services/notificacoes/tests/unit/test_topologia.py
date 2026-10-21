from notificacoes.adaptadores.mensageria.topologia import (
    FILA_DLQ,
    FILA_EMAILS,
    FILA_EVENTOS,
    FILA_WEBHOOKS,
    FILAS_DE_TAREFA,
    fila_de_tarefas,
    fila_dlq,
    fila_eventos,
    filas_retry,
    nome_fila_retry,
)


def test_nomes_das_filas_da_spec() -> None:
    assert (FILA_EVENTOS, FILA_EMAILS, FILA_WEBHOOKS, FILA_DLQ) == (
        "notificacoes.eventos",
        "notificacoes.emails",
        "notificacoes.webhooks",
        "notificacoes.dlq",
    )
    assert nome_fila_retry(FILA_WEBHOOKS, 3) == "notificacoes.webhooks.retry.3"
    assert FILAS_DE_TAREFA == {"tarefa.email": FILA_EMAILS, "tarefa.webhook": FILA_WEBHOOKS}


def test_fila_de_eventos_assina_tudo_e_rejeitadas_vao_para_a_dlq() -> None:
    fila = fila_eventos()
    assert (fila.name, fila.durable, fila.routing_key) == (FILA_EVENTOS, True, "#")
    assert fila.arguments is not None
    assert fila.arguments["x-dead-letter-exchange"] == ""
    assert fila.arguments["x-dead-letter-routing-key"] == FILA_DLQ
    assert fila_de_tarefas(FILA_WEBHOOKS).arguments["x-dead-letter-routing-key"] == FILA_DLQ
    assert fila_dlq().durable is True


def test_filas_de_retry_com_ttl_e_retorno_para_a_principal() -> None:
    filas = filas_retry(FILA_WEBHOOKS, (1000, 5000, 30000, 120000, 600000))
    assert [fila.name for fila in filas] == [
        f"notificacoes.webhooks.retry.{n}" for n in range(1, 6)
    ]
    assert [fila.arguments["x-message-ttl"] for fila in filas] == [
        1000,
        5000,
        30000,
        120000,
        600000,
    ]
    for fila in filas:
        assert fila.durable is True
        assert fila.arguments["x-dead-letter-exchange"] == ""
        assert fila.arguments["x-dead-letter-routing-key"] == FILA_WEBHOOKS
