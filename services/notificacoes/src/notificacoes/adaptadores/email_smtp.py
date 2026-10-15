"""Envio de e-mail por SMTP (Mailpit no ambiente local; spec §4.2)."""

import time
from email.message import EmailMessage

import aiosmtplib

from notificacoes.aplicacao.portas import FalhaNoEnvioDeEmail
from plataforma.logs import obter_logger

_log = obter_logger(__name__)


def montar_mensagem(*, remetente: str, para: str, assunto: str, corpo: str) -> EmailMessage:
    mensagem = EmailMessage()
    mensagem["From"] = remetente
    mensagem["To"] = para
    mensagem["Subject"] = assunto
    mensagem.set_content(corpo)
    return mensagem


class EnviadorSmtp:
    """Implementa ``EnviadorDeEmail``. Não loga o endereço nem o conteúdo."""

    def __init__(
        self, *, host: str, porta: int, remetente: str, timeout_segundos: float = 5.0
    ) -> None:
        self._host = host
        self._porta = porta
        self._remetente = remetente
        self._timeout = timeout_segundos

    async def enviar(self, *, para: str, assunto: str, corpo: str) -> None:
        mensagem = montar_mensagem(
            remetente=self._remetente, para=para, assunto=assunto, corpo=corpo
        )
        servidor = f"{self._host}:{self._porta}"
        inicio = time.perf_counter()
        try:
            await aiosmtplib.send(
                mensagem, hostname=self._host, port=self._porta, timeout=self._timeout
            )
        except (aiosmtplib.SMTPException, OSError, TimeoutError) as erro:
            _log.warning(
                "smtp_falhou",
                servidor=servidor,
                erro=type(erro).__name__,
                duracao_ms=round((time.perf_counter() - inicio) * 1000, 1),
            )
            raise FalhaNoEnvioDeEmail(f"Falha no SMTP ({type(erro).__name__}).") from erro
        _log.info(
            "smtp_enviado",
            servidor=servidor,
            duracao_ms=round((time.perf_counter() - inicio) * 1000, 1),
        )
