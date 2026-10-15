"""Dependências FastAPI compartilhadas pelas rotas."""

from typing import Annotated

from fastapi import Depends, Request

from avaliacoes.aplicacao.portas import Solicitante
from avaliacoes.composicao import Dependencias
from plataforma.auth import Papel, Usuario


def obter_dependencias(requisicao: Request) -> Dependencias:
    dependencias: Dependencias = requisicao.app.state.dependencias
    return dependencias


Deps = Annotated[Dependencias, Depends(obter_dependencias)]


def solicitante(usuario: Usuario) -> Solicitante:
    return Solicitante(id=usuario.id, token=usuario.token, admin=usuario.papel is Papel.ADMIN)
