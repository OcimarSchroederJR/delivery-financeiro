import json
from datetime import UTC, datetime

from avaliacoes.adaptadores.mensageria.especificacao import EVENTOS, criar_broker_documentado
from avaliacoes.aplicacao.eventos import (
    AVALIACAO_REGISTRADA,
    DISPUTA_ABERTA,
    DISPUTA_ESTORNO_FALHOU,
    DISPUTA_RESOLVIDA,
    dados_avaliacao_registrada,
    dados_disputa_aberta,
    dados_disputa_estorno_falhou,
    dados_disputa_resolvida,
)
from avaliacoes.dominio.avaliacao import Avaliacao
from avaliacoes.dominio.disputa import Disputa, MotivoDisputa
from plataforma.contratos import asyncapi_json
from plataforma.envelope import EnvelopeEvento

AGORA = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def _disputa() -> Disputa:
    return Disputa.abrir(
        pedido_id="ped-4",
        pagamento_id="pag-1",
        cliente_id="cliente-1",
        motivo=MotivoDisputa.NAO_ENTREGUE,
        descricao=None,
        valor_solicitado_centavos=3200,
        valor_pago_centavos=3200,
        agora=AGORA,
    )


def _exemplos() -> dict[str, object]:
    avaliacao = Avaliacao.registrar(
        pedido_id="ped-4",
        cliente_id="cliente-1",
        restaurante_id="rest-1",
        nota_restaurante=5,
        nota_entrega=None,
        comentario=None,
        agora=AGORA,
    )
    aberta = _disputa()
    improcedente = _disputa()
    improcedente.julgar_improcedente(parecer=None, valor_aprovado_centavos=None, agora=AGORA)
    falhou = _disputa()
    falhou.aprovar(
        valor_aprovado_centavos=None, parecer=None, agora=AGORA, primeira_tentativa_em=AGORA
    )
    falhou.falhar_estorno(motivo="TENTATIVAS_ESGOTADAS", agora=AGORA)
    return {
        AVALIACAO_REGISTRADA: dados_avaliacao_registrada(avaliacao),
        DISPUTA_ABERTA: dados_disputa_aberta(aberta),
        DISPUTA_RESOLVIDA: dados_disputa_resolvida(improcedente),
        DISPUTA_ESTORNO_FALHOU: dados_disputa_estorno_falhou(falhou),
    }


def test_dados_montados_batem_exatamente_com_o_asyncapi() -> None:
    for tipo, dados in _exemplos().items():
        evento, modelo_dados, _ = EVENTOS[tipo]
        assert set(dados) == set(modelo_dados.model_fields), tipo  # type: ignore[arg-type]
        envelope = EnvelopeEvento.novo(tipo, dados)  # type: ignore[arg-type]
        evento.model_validate(envelope.para_json())


def test_asyncapi_tem_os_quatro_canais_no_exchange_de_eventos() -> None:
    especificacao = json.loads(
        asyncapi_json(criar_broker_documentado(), titulo="Avaliações (eventos)", versao="0.1.0")
    )
    assert set(especificacao["channels"]) == set(EVENTOS)
    for canal in especificacao["channels"].values():
        assert canal["bindings"]["amqp"]["exchange"]["name"] == "financeiro.eventos"


def test_asyncapi_explica_os_motivos_de_estorno_falhou() -> None:
    texto = asyncapi_json(criar_broker_documentado(), titulo="Avaliações (eventos)", versao="0.1.0")
    assert "RESULTADO_INCERTO" in texto
