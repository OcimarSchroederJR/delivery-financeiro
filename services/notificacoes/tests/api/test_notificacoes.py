import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from notificacoes.adaptadores.memoria import ArmazenamentoEmMemoria
from notificacoes.dominio.notificacao import Notificacao

Bearer = Callable[[str, str], dict[str, str]]


def _semear(armazenamento: ArmazenamentoEmMemoria) -> None:
    for destinatario in ("cliente-1", "cliente-1", "cliente-2"):
        notificacao = Notificacao.para_email(
            mensagem_id_origem=uuid.uuid4(),
            tipo_evento="pagamento.aprovado",
            destinatario_id=destinatario,
            destino=None,
            agora=datetime(2026, 10, 14, 14, 30, tzinfo=UTC),
        )
        armazenamento.notificacoes[notificacao.id] = notificacao


async def test_cliente_ve_so_as_proprias_e_admin_filtra(
    api: httpx.AsyncClient, bearer: Bearer, armazenamento: ArmazenamentoEmMemoria
) -> None:
    _semear(armazenamento)
    cliente = bearer("cliente-1", "cliente")
    proprias = (await api.get("/v1/notificacoes", headers=cliente)).json()
    assert proprias["total"] == 2
    item = proprias["itens"][0]
    assert (item["canal"], item["status"], item["destinatario_id"]) == (
        "email",
        "pendente",
        "cliente-1",
    )
    assert item["criado_em"] == "2026-10-14T14:30:00Z"
    de_outro = await api.get("/v1/notificacoes?destinatario_id=cliente-2", headers=cliente)
    assert de_outro.status_code == 403
    admin = bearer("admin-1", "admin")
    assert (await api.get("/v1/notificacoes", headers=admin)).json()["total"] == 3
    filtradas = await api.get("/v1/notificacoes?destinatario_id=cliente-2", headers=admin)
    assert filtradas.json()["total"] == 1


async def test_paginacao_invalida_422(api: httpx.AsyncClient, bearer: Bearer) -> None:
    resposta = await api.get("/v1/notificacoes?tamanho=101", headers=bearer("cliente-1", "cliente"))
    assert resposta.status_code == 422


async def test_sem_token_401(api: httpx.AsyncClient) -> None:
    assert (await api.get("/v1/notificacoes")).status_code == 401
