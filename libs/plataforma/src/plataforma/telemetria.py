"""OpenTelemetry opcional, ligado por ``OTEL_HABILITADO=true`` (spec §6).

- HTTP de entrada: telemetria nativa do FastAPI (ativa quando há TracerProvider global).
- HTTP de saída: instrumentação do httpx (propaga ``traceparent``).
- Banco: instrumentação do SQLAlchemy, por engine.
- Mensageria: ``RabbitTelemetryMiddleware`` do FastStream (ver ``plataforma.mensageria``).
"""

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from sqlalchemy.ext.asyncio import AsyncEngine

_configurada = False


def configurar_telemetria(
    servico: str,
    *,
    habilitada: bool,
    endpoint_otlp: str,
    exportador: SpanExporter | None = None,
) -> bool:
    """Registra o TracerProvider global e instrumenta o httpx. Idempotente.

    ``exportador`` substitui o OTLP (testes usam ``InMemorySpanExporter``).
    """
    global _configurada
    if not habilitada:
        return False
    if _configurada:
        return True
    provedor = TracerProvider(resource=Resource.create({"service.name": servico}))
    if exportador is None:
        exportador = OTLPSpanExporter(endpoint=f"{endpoint_otlp.rstrip('/')}/v1/traces")
    provedor.add_span_processor(BatchSpanProcessor(exportador))
    trace.set_tracer_provider(provedor)
    HTTPXClientInstrumentor().instrument()
    _configurada = True
    return True


def telemetria_ativa() -> bool:
    return _configurada


def instrumentar_engine(engine: AsyncEngine) -> None:
    """Gera spans das queries do engine, se a telemetria estiver ativa."""
    if _configurada:
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)


def trace_id_atual() -> str | None:
    contexto = trace.get_current_span().get_span_context()
    if not contexto.is_valid:
        return None
    return format(contexto.trace_id, "032x")
