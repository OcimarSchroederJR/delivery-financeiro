"""Exceções base com status HTTP e código de erro (spec §3.4).

Módulo em Python puro: pode ser importado pelo domínio dos serviços.
Para criar um erro de negócio, herde da classe com o status desejado e
defina ``codigo_padrao`` e ``mensagem_padrao``.
"""

from collections.abc import Mapping
from typing import Any, ClassVar


class ErroAplicacao(Exception):
    """Raiz de todos os erros tratados. Vira ``{"erro": true, ...}`` na API."""

    status_http: ClassVar[int] = 500
    codigo_padrao: ClassVar[str] = "ERRO_INTERNO"
    mensagem_padrao: ClassVar[str] = "Erro interno do servidor."

    def __init__(
        self,
        mensagem: str | None = None,
        *,
        codigo: str | None = None,
        detalhes: Mapping[str, Any] | None = None,
    ) -> None:
        self.mensagem = mensagem or self.mensagem_padrao
        self.codigo = codigo or self.codigo_padrao
        self.detalhes: dict[str, Any] = dict(detalhes or {})
        super().__init__(self.mensagem)


class ErroRequisicaoInvalida(ErroAplicacao):
    status_http = 400
    codigo_padrao = "REQUISICAO_INVALIDA"
    mensagem_padrao = "Requisição inválida."


class ErroNaoAutenticado(ErroAplicacao):
    status_http = 401
    codigo_padrao = "NAO_AUTENTICADO"
    mensagem_padrao = "Credenciais ausentes ou inválidas."


class ErroAcessoNegado(ErroAplicacao):
    status_http = 403
    codigo_padrao = "ACESSO_NEGADO"
    mensagem_padrao = "Acesso negado."


class ErroNaoEncontrado(ErroAplicacao):
    status_http = 404
    codigo_padrao = "RECURSO_NAO_ENCONTRADO"
    mensagem_padrao = "Recurso não encontrado."


class ErroConflito(ErroAplicacao):
    status_http = 409
    codigo_padrao = "CONFLITO"
    mensagem_padrao = "O recurso está em um estado que impede a operação."


class ErroRegraDeNegocio(ErroAplicacao):
    status_http = 422
    codigo_padrao = "REGRA_DE_NEGOCIO_VIOLADA"
    mensagem_padrao = "A operação viola uma regra de negócio."


class ErroDependenciaIndisponivel(ErroAplicacao):
    """Outra equipe (ou infraestrutura) fora do ar: 503 sem derrubar o processo."""

    status_http = 503
    codigo_padrao = "DEPENDENCIA_INDISPONIVEL"
    mensagem_padrao = "Uma dependência externa está indisponível."

    def __init__(self, dependencia: str, mensagem: str | None = None) -> None:
        self.dependencia = dependencia
        super().__init__(
            mensagem or f"A dependência '{dependencia}' está indisponível no momento.",
            detalhes={"dependencia": dependencia},
        )
