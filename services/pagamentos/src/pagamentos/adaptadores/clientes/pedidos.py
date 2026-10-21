"""Adapter da Eq. 3 (Pedidos): ``GET {PEDIDOS_URL}/pedidos/{id}``.

Mapeia os nomes de campo da Eq. 3 para o domínio (premissa da spec §12). Timeout,
retry e circuit breaker vêm do ``ClienteHttp`` da plataforma.
"""

from http import HTTPStatus
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, StrictInt, ValidationError

from pagamentos.dominio.pedido import Pedido
from plataforma.cliente_http import ClienteHttp
from plataforma.erros import ErroDependenciaIndisponivel
from plataforma.logs import obter_logger

_log = obter_logger(__name__)
DEPENDENCIA_PEDIDOS = "pedidos"


class _PedidoEq3(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    cliente_id: str
    valor_total_centavos: StrictInt
    status: str


class ClientePedidosHttp:
    def __init__(self, cliente: ClienteHttp) -> None:
        self._cliente = cliente

    async def obter(self, pedido_id: str, *, token: str) -> Pedido | None:
        resposta = await self._cliente.get(f"/pedidos/{quote(pedido_id, safe='')}", token=token)
        if resposta.status_code == HTTPStatus.NOT_FOUND:
            return None
        if resposta.status_code != HTTPStatus.OK:
            _log.warning("pedidos_resposta_inesperada", status=resposta.status_code)
            raise ErroDependenciaIndisponivel(DEPENDENCIA_PEDIDOS)
        try:
            dados = _PedidoEq3.model_validate_json(resposta.content)
        except ValidationError:
            _log.warning("pedidos_resposta_invalida", status=resposta.status_code)
            raise ErroDependenciaIndisponivel(DEPENDENCIA_PEDIDOS) from None
        return Pedido(
            id=dados.id,
            cliente_id=dados.cliente_id,
            valor_total_centavos=dados.valor_total_centavos,
            status=dados.status,
        )
