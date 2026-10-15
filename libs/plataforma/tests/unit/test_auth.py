import httpx
import jwt
import pytest

from plataforma.auth import (
    EMISSOR_INTERNO,
    EmissorTokenServico,
    Papel,
    VerificadorComposto,
    VerificadorJwks,
    VerificadorTokenServico,
    criar_verificador,
)
from plataforma.config import ConfiguracaoBase
from plataforma.erros import ErroDependenciaIndisponivel, ErroNaoAutenticado
from plataforma.testes.tokens import (
    SEGREDO_SERVICO_TESTE,
    GeradorDeTokens,
    criar_verificador_de_teste,
)

URL = "http://identidade.teste/.well-known/jwks.json"


class Relogio:
    def __init__(self) -> None:
        self.agora = 0.0

    def __call__(self) -> float:
        return self.agora


class ServidorJwks:
    """Transporte httpx controlável: conta chamadas e pode simular queda."""

    def __init__(self, gerador: GeradorDeTokens) -> None:
        self.gerador = gerador
        self.fora = False
        self.chamadas = 0

    def __call__(self, _requisicao: httpx.Request) -> httpx.Response:
        self.chamadas += 1
        if self.fora:
            raise httpx.ConnectError("identidade fora")
        return httpx.Response(200, json=self.gerador.jwks())


@pytest.fixture
def gerador() -> GeradorDeTokens:
    return GeradorDeTokens()


@pytest.fixture
def servidor(gerador: GeradorDeTokens) -> ServidorJwks:
    return ServidorJwks(gerador)


def _verificador(servidor: ServidorJwks, relogio: Relogio | None = None) -> VerificadorJwks:
    return VerificadorJwks(
        URL,
        cliente=httpx.AsyncClient(transport=httpx.MockTransport(servidor)),
        ttl_segundos=300,
        intervalo_minimo_recarga=10,
        relogio=relogio or Relogio(),
    )


async def test_token_valido_da_eq1(gerador: GeradorDeTokens, servidor: ServidorJwks) -> None:
    usuario = await _verificador(servidor).verificar(gerador.emitir("cliente-1", "cliente"))
    assert (usuario.id, usuario.papel) == ("cliente-1", Papel.CLIENTE)
    assert usuario.emissor == "mock-identidade"


async def test_claim_de_papel_configuravel_e_lista(
    gerador: GeradorDeTokens, servidor: ServidorJwks
) -> None:
    verificador = VerificadorJwks(
        URL,
        cliente=httpx.AsyncClient(transport=httpx.MockTransport(servidor)),
        claim_papel="roles",
    )
    token = gerador.emitir("u1", "ignorado", claims_extras={"roles": ["desconhecido", "ADMIN"]})
    assert (await verificador.verificar(token)).papel is Papel.ADMIN


async def test_token_da_eq1_nunca_recebe_papel_servico(
    gerador: GeradorDeTokens, servidor: ServidorJwks
) -> None:
    with pytest.raises(ErroNaoAutenticado):
        await _verificador(servidor).verificar(gerador.emitir("x", "servico"))


@pytest.mark.parametrize("token", ["", "nao-e-jwt", "a.b.c"])
async def test_token_malformado(servidor: ServidorJwks, token: str) -> None:
    with pytest.raises(ErroNaoAutenticado):
        await _verificador(servidor).verificar(token)


async def test_token_expirado(gerador: GeradorDeTokens, servidor: ServidorJwks) -> None:
    token = gerador.emitir("x", "cliente", validade_segundos=-120)
    with pytest.raises(ErroNaoAutenticado):
        await _verificador(servidor).verificar(token)


async def test_assinado_por_outra_chave_com_mesmo_kid(servidor: ServidorJwks) -> None:
    impostor = GeradorDeTokens()
    with pytest.raises(ErroNaoAutenticado):
        await _verificador(servidor).verificar(impostor.emitir("x", "admin"))


async def test_rejeita_hs256_contra_jwks(servidor: ServidorJwks) -> None:
    claims = {"sub": "x", "papel": "admin", "exp": 9999999999}
    token = jwt.encode(claims, "k" * 32, algorithm="HS256")
    with pytest.raises(ErroNaoAutenticado):
        await _verificador(servidor).verificar(token)


async def test_cache_evita_buscar_jwks_a_cada_requisicao(
    gerador: GeradorDeTokens, servidor: ServidorJwks
) -> None:
    verificador = _verificador(servidor)
    for _ in range(3):
        await verificador.verificar(gerador.emitir("x", "cliente"))
    assert servidor.chamadas == 1


async def test_eq1_fora_usa_ultima_chave_conhecida_sem_martelar(
    gerador: GeradorDeTokens, servidor: ServidorJwks
) -> None:
    relogio = Relogio()
    verificador = _verificador(servidor, relogio)
    await verificador.verificar(gerador.emitir("x", "cliente"))
    servidor.fora = True
    relogio.agora += 301  # TTL expirou
    for _ in range(3):
        usuario = await verificador.verificar(gerador.emitir("x", "cliente"))
        assert usuario.id == "x"
    assert servidor.chamadas == 2  # uma recarga falha; as próximas esperam o intervalo mínimo


async def test_eq1_fora_sem_cache_vira_503(
    gerador: GeradorDeTokens, servidor: ServidorJwks
) -> None:
    servidor.fora = True
    with pytest.raises(ErroDependenciaIndisponivel):
        await _verificador(servidor).verificar(gerador.emitir("x", "cliente"))


async def test_kid_novo_forca_recarga(servidor: ServidorJwks) -> None:
    relogio = Relogio()
    verificador = _verificador(servidor, relogio)
    await verificador.verificar(servidor.gerador.emitir("x", "cliente"))
    servidor.gerador = GeradorDeTokens(kid="chave-rotacionada")
    relogio.agora += 11
    usuario = await verificador.verificar(servidor.gerador.emitir("y", "loja"))
    assert usuario.papel is Papel.LOJA
    assert servidor.chamadas == 2


async def test_token_de_servico_ida_e_volta() -> None:
    token = EmissorTokenServico(SEGREDO_SERVICO_TESTE, servico="avaliacoes").emitir()
    usuario = await VerificadorTokenServico(SEGREDO_SERVICO_TESTE).verificar(token)
    assert (usuario.id, usuario.papel) == ("avaliacoes", Papel.SERVICO)
    assert usuario.emissor == EMISSOR_INTERNO


async def test_token_de_servico_com_segredo_errado() -> None:
    token = EmissorTokenServico("x" * 40, servico="avaliacoes").emitir()
    with pytest.raises(ErroNaoAutenticado):
        await VerificadorTokenServico(SEGREDO_SERVICO_TESTE).verificar(token)


async def test_token_de_servico_expirado() -> None:
    token = EmissorTokenServico(
        SEGREDO_SERVICO_TESTE, servico="avaliacoes", relogio=lambda: 1000.0
    ).emitir()
    with pytest.raises(ErroNaoAutenticado):
        await VerificadorTokenServico(SEGREDO_SERVICO_TESTE).verificar(token)


async def test_composto_roteia_pelo_emissor(gerador: GeradorDeTokens) -> None:
    verificador = criar_verificador_de_teste(gerador)
    interno = EmissorTokenServico(SEGREDO_SERVICO_TESTE, servico="avaliacoes").emitir()
    assert (await verificador.verificar(interno)).papel is Papel.SERVICO
    assert (await verificador.verificar(gerador.emitir("c1", "cliente"))).papel is Papel.CLIENTE


async def test_composto_rejeita_rs256_que_finge_ser_interno(gerador: GeradorDeTokens) -> None:
    falso = gerador.emitir("x", "servico", claims_extras={"iss": EMISSOR_INTERNO})
    with pytest.raises(ErroNaoAutenticado):
        await criar_verificador_de_teste(gerador).verificar(falso)


async def test_composto_rejeita_lixo() -> None:
    verificador = VerificadorComposto(
        externo=VerificadorTokenServico(SEGREDO_SERVICO_TESTE),
        interno=VerificadorTokenServico(SEGREDO_SERVICO_TESTE),
    )
    with pytest.raises(ErroNaoAutenticado):
        await verificador.verificar("lixo")


def test_criar_verificador_a_partir_da_config() -> None:
    config = ConfiguracaoBase(servico="x", token_servico_segredo=SEGREDO_SERVICO_TESTE)  # type: ignore[arg-type]
    assert isinstance(criar_verificador(config), VerificadorComposto)
