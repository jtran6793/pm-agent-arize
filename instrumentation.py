import os
from arize.otel import register
from openinference.instrumentation.anthropic import AnthropicInstrumentor


def setup_tracing():
    tracer_provider = register(
        space_id=os.environ["ARIZE_SPACE_ID"],
        api_key=os.environ["ARIZE_API_KEY"],
        project_name="feedback-synthesizer",
    )
    AnthropicInstrumentor().instrument(tracer_provider=tracer_provider)
    return tracer_provider
