"""Dependências FastAPI do serviço."""

from typing import Annotated, cast

from fastapi import Depends, Request

from notificacoes.aplicacao.portas import FabricaUow, UnidadeDeTrabalho
from notificacoes.aplicacao.solicitante import Solicitante
from notificacoes.config import Config
from plataforma.api.auth import exigir_papeis
from plataforma.auth import Papel, Usuario

# Decisão da Fase 3: eventos externos vêm de sistemas (Eq. 3 e Eq. 4), não de clientes.
PAPEIS_PRODUTORES_DE_EVENTOS = (Papel.LOJA, Papel.ENTREGADOR, Papel.ADMIN)


def obter_uow(requisicao: Request) -> UnidadeDeTrabalho:
    fabrica = cast(FabricaUow, requisicao.app.state.fabrica_uow)
    return fabrica()


def obter_config(requisicao: Request) -> Config:
    return cast(Config, requisicao.app.state.config)


def solicitante_de(usuario: Usuario) -> Solicitante:
    return Solicitante(id=usuario.id, admin=usuario.papel is Papel.ADMIN)


Uow = Annotated[UnidadeDeTrabalho, Depends(obter_uow)]
ConfigAtual = Annotated[Config, Depends(obter_config)]
ProdutorDeEventos = Annotated[Usuario, Depends(exigir_papeis(*PAPEIS_PRODUTORES_DE_EVENTOS))]
