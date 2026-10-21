from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from plataforma import telemetria


def test_telemetria_desligada_nao_faz_nada() -> None:
    ligada = telemetria.configurar_telemetria("x", habilitada=False, endpoint_otlp="http://j")
    assert ligada is False
    assert telemetria.trace_id_atual() is None


def test_telemetria_ligada_gera_trace_id_e_e_idempotente() -> None:
    exportador = InMemorySpanExporter()
    assert telemetria.configurar_telemetria(
        "x", habilitada=True, endpoint_otlp="http://j", exportador=exportador
    )
    assert telemetria.telemetria_ativa()
    assert telemetria.configurar_telemetria("x", habilitada=True, endpoint_otlp="http://j")
    with trace.get_tracer("teste").start_as_current_span("operacao"):
        trace_id = telemetria.trace_id_atual()
    assert trace_id is not None
    assert len(trace_id) == 32
