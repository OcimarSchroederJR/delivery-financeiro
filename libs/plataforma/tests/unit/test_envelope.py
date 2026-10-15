import uuid

import pytest
from pydantic import ValidationError

from plataforma.correlation import correlation_id_em, definir_correlation_id
from plataforma.envelope import EnvelopeEvento


def test_envelope_novo_preenche_campos() -> None:
    with correlation_id_em("cid-env"):
        envelope = EnvelopeEvento.novo("pagamento.aprovado", {"pagamento_id": "p1"})
    assert envelope.versao == 1
    assert envelope.correlation_id == "cid-env"
    assert envelope.ocorrido_em.tzinfo is not None
    serializado = envelope.para_json()
    assert serializado["mensagem_id"] == str(envelope.mensagem_id)
    assert serializado["ocorrido_em"].endswith("Z")
    assert serializado["dados"] == {"pagamento_id": "p1"}


def test_envelope_gera_correlation_id_quando_ausente() -> None:
    definir_correlation_id(None)
    envelope = EnvelopeEvento.novo("disputa.aberta", {})
    uuid.UUID(envelope.correlation_id)


@pytest.mark.parametrize("tipo", ["pagamento", "Pagamento.Aprovado", "pagamento.", "a.b.c", ""])
def test_envelope_rejeita_tipo_fora_do_padrao(tipo: str) -> None:
    with pytest.raises(ValidationError):
        EnvelopeEvento.novo(tipo, {})


def test_envelope_ignora_campos_desconhecidos_e_valida_ida_e_volta() -> None:
    original = EnvelopeEvento.novo("entrega.concluida", {"pedido_id": "x"})
    recebido = EnvelopeEvento.model_validate({**original.para_json(), "campo_novo": 1})
    assert recebido.mensagem_id == original.mensagem_id
    assert recebido.para_json() == original.para_json()


def test_envelope_exige_fuso_em_ocorrido_em() -> None:
    dados = EnvelopeEvento.novo("entrega.concluida", {}).para_json()
    dados["ocorrido_em"] = "2026-10-14T14:30:00"
    with pytest.raises(ValidationError):
        EnvelopeEvento.model_validate(dados)
