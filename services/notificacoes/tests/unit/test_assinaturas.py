import uuid
from datetime import UTC, datetime

import pytest

from notificacoes.adaptadores.memoria import ArmazenamentoEmMemoria, UnidadeDeTrabalhoEmMemoria
from notificacoes.aplicacao.assinaturas import (
    criar_assinatura,
    listar_assinaturas,
    listar_entregas,
    remover_assinatura,
)
from notificacoes.aplicacao.consultas import listar_notificacoes
from notificacoes.aplicacao.solicitante import PoliticaDeUrl, Solicitante
from notificacoes.dominio.assinatura import AssinaturaWebhook
from notificacoes.dominio.entrega import EntregaWebhook
from notificacoes.dominio.erros import AssinaturaNaoEncontrada, UrlDeWebhookInvalida
from notificacoes.dominio.notificacao import Notificacao
from plataforma.erros import ErroAcessoNegado

AGORA = datetime(2026, 10, 14, 14, 30, tzinfo=UTC)
CLIENTE = Solicitante(id="cliente-1", admin=False)
OUTRO = Solicitante(id="cliente-2", admin=False)
ADMIN = Solicitante(id="admin-1", admin=True)
LOCAL = PoliticaDeUrl(permitir_http=True, permitir_rede_interna=True)
PRODUCAO = PoliticaDeUrl(permitir_http=False, permitir_rede_interna=False)


def _uow(armazenamento: ArmazenamentoEmMemoria) -> UnidadeDeTrabalhoEmMemoria:
    return UnidadeDeTrabalhoEmMemoria(armazenamento)


async def _criar(
    armazenamento: ArmazenamentoEmMemoria,
    solicitante: Solicitante = CLIENTE,
    *,
    url: str = "https://exemplo.com/hook",
    politica: PoliticaDeUrl = PRODUCAO,
) -> AssinaturaWebhook:
    return await criar_assinatura(
        _uow(armazenamento),
        solicitante,
        url=url,
        eventos=["pagamento.*"],
        politica=politica,
        gerar_segredo=lambda: "segredo-fixo",
        agora=lambda: AGORA,
    )


async def test_criar_assinatura_persiste_com_segredo_e_escopo() -> None:
    armazenamento = ArmazenamentoEmMemoria()
    do_cliente = await _criar(armazenamento)
    do_admin = await _criar(armazenamento, ADMIN)
    assert do_cliente.segredo == "segredo-fixo"
    assert armazenamento.assinaturas[do_cliente.id].criado_por == "cliente-1"
    assert (do_cliente.somente_proprios, do_admin.somente_proprios) == (True, False)


async def test_criar_valida_url_conforme_politica() -> None:
    armazenamento = ArmazenamentoEmMemoria()
    with pytest.raises(UrlDeWebhookInvalida):
        await _criar(armazenamento, url="http://localhost:9099/hook")
    assert (await _criar(armazenamento, url="http://localhost:9099/hook", politica=LOCAL)).ativa
    assert len(armazenamento.assinaturas) == 1


async def test_listar_so_as_proprias_e_admin_ve_todas() -> None:
    armazenamento = ArmazenamentoEmMemoria()
    primeira = await _criar(armazenamento)
    await _criar(armazenamento, OUTRO)
    removida = await _criar(armazenamento)
    await remover_assinatura(_uow(armazenamento), CLIENTE, removida.id)
    itens, total = await listar_assinaturas(_uow(armazenamento), CLIENTE, deslocamento=0, limite=20)
    assert ([item.id for item in itens], total) == ([primeira.id], 1)
    _, total_admin = await listar_assinaturas(_uow(armazenamento), ADMIN, deslocamento=0, limite=20)
    assert total_admin == 2


async def test_remover_assinatura_propria_e_depois_404() -> None:
    armazenamento = ArmazenamentoEmMemoria()
    assinatura = await _criar(armazenamento)
    await remover_assinatura(_uow(armazenamento), CLIENTE, assinatura.id)
    assert armazenamento.assinaturas[assinatura.id].ativa is False
    with pytest.raises(AssinaturaNaoEncontrada):
        await remover_assinatura(_uow(armazenamento), CLIENTE, assinatura.id)


async def test_remover_de_outro_usuario_e_403_inexistente_404_e_admin_pode() -> None:
    armazenamento = ArmazenamentoEmMemoria()
    assinatura = await _criar(armazenamento)
    with pytest.raises(ErroAcessoNegado):
        await remover_assinatura(_uow(armazenamento), OUTRO, assinatura.id)
    with pytest.raises(AssinaturaNaoEncontrada):
        await remover_assinatura(_uow(armazenamento), CLIENTE, uuid.uuid4())
    await remover_assinatura(_uow(armazenamento), ADMIN, assinatura.id)
    assert armazenamento.assinaturas[assinatura.id].ativa is False


async def test_listar_entregas_respeita_o_dono() -> None:
    armazenamento = ArmazenamentoEmMemoria()
    assinatura = await _criar(armazenamento)
    outra = await _criar(armazenamento, OUTRO)
    for tentativa, alvo in ((1, assinatura), (2, assinatura), (3, assinatura), (1, outra)):
        armazenamento.entregas.append(
            EntregaWebhook.registrar(
                assinatura_id=alvo.id,
                mensagem_id=uuid.uuid4(),
                tentativa=tentativa,
                status_http=500,
                duracao_ms=1,
                erro=None,
                agora=AGORA,
            )
        )
    itens, total = await listar_entregas(
        _uow(armazenamento), CLIENTE, assinatura.id, deslocamento=0, limite=2
    )
    assert (len(itens), total) == (2, 3)
    with pytest.raises(ErroAcessoNegado):
        await listar_entregas(_uow(armazenamento), OUTRO, assinatura.id, deslocamento=0, limite=2)
    with pytest.raises(AssinaturaNaoEncontrada):
        await listar_entregas(_uow(armazenamento), CLIENTE, uuid.uuid4(), deslocamento=0, limite=2)


async def test_listar_notificacoes_do_proprio_usuario_e_admin() -> None:
    armazenamento = ArmazenamentoEmMemoria()
    for destinatario in ("cliente-1", "cliente-1", "cliente-2"):
        notificacao = Notificacao.para_email(
            mensagem_id_origem=uuid.uuid4(),
            tipo_evento="pagamento.aprovado",
            destinatario_id=destinatario,
            destino=None,
            agora=AGORA,
        )
        armazenamento.notificacoes[notificacao.id] = notificacao

    async def total(solicitante: Solicitante, destinatario_id: str | None) -> int:
        _, quantidade = await listar_notificacoes(
            _uow(armazenamento),
            solicitante,
            destinatario_id=destinatario_id,
            deslocamento=0,
            limite=20,
        )
        return quantidade

    assert await total(CLIENTE, None) == 2
    assert await total(CLIENTE, "cliente-1") == 2
    with pytest.raises(ErroAcessoNegado):
        await total(CLIENTE, "cliente-2")
    assert await total(ADMIN, None) == 3
    assert await total(ADMIN, "cliente-2") == 1
