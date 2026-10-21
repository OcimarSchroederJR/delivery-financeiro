"""Adapter da Eq. 3 (Pedidos): ``GET {PEDIDOS_URL}/pedidos/{id}`` (spec §4.3, regra 1)."""

from urllib.parse import quote

from avaliacoes.aplicacao.portas import PedidoExterno
from avaliacoes.dominio.erros import PedidoDeOutroCliente
from plataforma.cliente_http import ClienteHttp
from plataforma.erros import ErroDependenciaIndisponivel
from plataforma.logs import obter_logger

_log = obter_logger(__name__)

# Status da Eq. 3 que contam como "entregue" (premissa da spec §12: mapear aqui).
STATUS_ENTREGUE = frozenset({"entregue"})


class PedidosHttp:
    def __init__(self, cliente: ClienteHttp) -> None:
        self._cliente = cliente

    async def obter(self, pedido_id: str, *, token: str) -> PedidoExterno | None:
        resposta = await self._cliente.get(f"/pedidos/{quote(pedido_id, safe='')}", token=token)
        if resposta.status_code == 404:
            return None
        if resposta.status_code == 403:
            raise PedidoDeOutroCliente()
        if resposta.status_code != 200:
            _log.warning("pedidos_resposta_inesperada", status=resposta.status_code)
            raise ErroDependenciaIndisponivel("pedidos")
        try:
            corpo = resposta.json()
            return PedidoExterno(
                id=str(corpo["id"]),
                cliente_id=str(corpo["cliente_id"]),
                restaurante_id=str(corpo["restaurante_id"]),
                entregue=str(corpo["status"]) in STATUS_ENTREGUE,
            )
        except (ValueError, KeyError, TypeError) as erro:
            _log.warning("pedidos_resposta_invalida", erro=type(erro).__name__)
            raise ErroDependenciaIndisponivel(
                "pedidos", "Resposta inválida do serviço de Pedidos."
            ) from erro
