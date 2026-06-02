"""
Optional OpenTelemetry tracing and metrics for temporal-build-worker.

Disabled by default. Enable by setting OTEL_EXPORTER_OTLP_ENDPOINT.
When disabled, all functions are no-ops and opentelemetry packages are
not required.
"""

import contextlib
import os
from collections.abc import Iterator

_otel_enabled: bool = False
_tracer = None
_meter = None


def init_observability() -> None:
    """
    Initialise OTel SDK if OTEL_EXPORTER_OTLP_ENDPOINT is set.
    Safe to call when opentelemetry packages are absent — silently skips.
    """
    global _otel_enabled, _tracer, _meter

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return

    try:
        from opentelemetry import trace, metrics
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

        service_name = os.environ.get("OTEL_SERVICE_NAME", "temporal-build-worker")

        tracer_provider = TracerProvider()
        tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
        )
        trace.set_tracer_provider(tracer_provider)

        metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=endpoint))
        meter_provider = MeterProvider(metric_readers=[metric_reader])
        metrics.set_meter_provider(meter_provider)

        _tracer = trace.get_tracer(service_name)
        _meter = metrics.get_meter(service_name)
        _otel_enabled = True
    except ImportError:
        pass


@contextlib.contextmanager
def activity_span(name: str, **attrs: str) -> Iterator[None]:
    """
    Context manager that creates an OTel span for an activity.
    No-op when OTel is disabled or packages are absent.
    """
    if not _otel_enabled or _tracer is None:
        yield
        return

    with _tracer.start_as_current_span(name, attributes=attrs):
        yield


def inc_counter(name: str, labels: dict[str, str]) -> None:
    """
    Increment a counter metric.
    No-op when OTel is disabled or packages are absent.
    """
    if not _otel_enabled or _meter is None:
        return

    counter = _meter.create_counter(name)
    counter.add(1, labels)
