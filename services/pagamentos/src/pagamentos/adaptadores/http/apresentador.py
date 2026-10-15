"""Apresentador HTTP: o mesmo corpo vai para a resposta e para a idempotência."""

from typing import Any

from pagamentos.adaptadores.http.esquemas import EstornoCriadoSaida, PagamentoSaida
from pagamentos.dominio.pagamento import Estorno, Pagamento, StatusPagamento
from plataforma.api.erros import corpo_erro
from plataforma.erros import ErroAplicacao


class ApresentadorHttp:
    def pagamento(self, pagamento: Pagamento) -> dict[str, Any]:
        return PagamentoSaida.de_dominio(pagamento).model_dump(mode="json")

    def estorno(self, estorno: Estorno, status_pagamento: StatusPagamento) -> dict[str, Any]:
        return EstornoCriadoSaida.de_estorno(estorno, status_pagamento).model_dump(mode="json")

    def erro(self, erro: ErroAplicacao) -> dict[str, Any]:
        # Mesma forma do tratador global de erros da plataforma.
        return corpo_erro(erro.mensagem, erro.codigo, extras=erro.detalhes)
