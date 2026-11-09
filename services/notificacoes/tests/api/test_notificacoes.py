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


async def test_consulta_por_id_do_dono_e_do_admin(
    api: httpx.AsyncClient, bearer: Bearer, armazenamento: ArmazenamentoEmMemoria
) -> None:
    _semear(armazenamento)
    notificacao = next(
        n for n in armazenamento.notificacoes.values() if n.destinatario_id == "cliente-2"
    )
    url = f"/v1/notificacoes/{notificacao.id}"
    do_dono = await api.get(url, headers=bearer("cliente-2", "cliente"))
    assert do_dono.status_code == 200
    corpo = do_dono.json()
    assert (corpo["id"], corpo["status"], corpo["destinatario_id"]) == (
        str(notificacao.id),
        "pendente",
        "cliente-2",
    )
    assert (await api.get(url, headers=bearer("admin-1", "admin"))).status_code == 200


async def test_consulta_por_id_de_outro_cliente_403(
    api: httpx.AsyncClient, bearer: Bearer, armazenamento: ArmazenamentoEmMemoria
) -> None:
    _semear(armazenamento)
    notificacao = next(
        n for n in armazenamento.notificacoes.values() if n.destinatario_id == "cliente-2"
    )
    resposta = await api.get(
        f"/v1/notificacoes/{notificacao.id}", headers=bearer("cliente-1", "cliente")
    )
    assert resposta.status_code == 403
    assert resposta.json()["codigo"] == "ACESSO_NEGADO"


async def test_consulta_por_id_inexistente_404_no_formato_padrao(
    api: httpx.AsyncClient, bearer: Bearer
) -> None:
    resposta = await api.get(
        f"/v1/notificacoes/{uuid.uuid4()}", headers=bearer("cliente-1", "cliente")
    )
    erro = resposta.json()
    assert resposta.status_code == 404
    assert (erro["erro"], erro["codigo"]) == (True, "NOTIFICACAO_NAO_ENCONTRADA")
    assert erro["mensagem"]
    assert erro["correlation_id"]


async def test_consulta_por_id_invalido_422_e_sem_token_401(
    api: httpx.AsyncClient, bearer: Bearer
) -> None:
    invalido = await api.get("/v1/notificacoes/abc", headers=bearer("cliente-1", "cliente"))
    assert invalido.status_code == 422
    assert (await api.get(f"/v1/notificacoes/{uuid.uuid4()}")).status_code == 401
