"""
llm_chain.py
============
Cadena de modelos gratuitos (idea tomada de jobHunter/llm_chain.py). En el plan
gratis de Gemini cada modelo tiene su propio cupo diario (ej. 20 requests/día en
los flash), así que un batch de cientos de recetas se frena en minutos si usa
uno solo. Aquí cada llamada prueba los modelos en orden; si uno responde 429 se
salta al siguiente en la misma llamada y queda "en pausa" una hora para no gastar
requests golpeando un cupo agotado.

Orden: modelos Gemini (los pedidos primero) -> 3 modelos Groq -> OpenRouter. Groq y
OpenRouter son opcionales: solo se usan si GROQ_API_KEY / OPENROUTER_API_KEY
están en el .env. Si todos fallan se levanta AllProvidersExhausted, cuyo mensaje
incluye RESOURCE_EXHAUSTED para que los scripts de backfill se detengan limpios.

El video solo lo puede ver Gemini: para eso está gemini_models(), que devuelve
la lista a rotar llamando la API REST directamente.
"""
import time
from typing import Optional, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# Calidad primero (nutrición) vs. volumen primero (extraer/estructurar).
GEMINI_FLASH = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"]
GEMINI_LITE = ["gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
# Cada modelo de Groq tiene su propio cupo gratis (~200k tokens/día).
GROQ_MODELS = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]

PAUSE_SECONDS = 3600  # un modelo que dio 429 no se vuelve a probar en esta hora
_paused_until: dict = {}


class AllProvidersExhausted(Exception):
    pass


def is_quota_error(e: Exception) -> bool:
    s = str(e).lower()
    return any(m in s for m in ("resource_exhausted", "429", "quota", "rate limit", "rate_limit", "too many requests"))


def _available(name: str) -> bool:
    return _paused_until.get(name, 0) < time.time()


def _pause(name: str):
    _paused_until[name] = time.time() + PAUSE_SECONDS
    print(f"   [llm_chain] {name} sin cupo, pasando al siguiente")


def gemini_models(lite: bool = True) -> list:
    """Modelos Gemini a rotar para llamadas REST (video), los no pausados primero."""
    order = GEMINI_LITE + GEMINI_FLASH if lite else GEMINI_FLASH + GEMINI_LITE
    return [m for m in order if _available(m)]


def mark_exhausted(model: str):
    _pause(model)


def _providers(lite: bool):
    from langchain_pipeline import get_env_var
    gemini_key = get_env_var("GEMINI_API_KEY")
    if gemini_key:
        from langchain_google_genai import ChatGoogleGenerativeAI
        for m in gemini_models(lite):
            # max_retries=1: sin esto langchain reintenta un 429 por minutos y cuelga la cadena
            yield m, "native", lambda m=m: ChatGoogleGenerativeAI(model=m, google_api_key=gemini_key,
                                                                  temperature=0, max_retries=1, timeout=90)
    groq_key = get_env_var("GROQ_API_KEY")
    if groq_key:
        from langchain_groq import ChatGroq
        for m in GROQ_MODELS:
            if _available(m):
                # json_schema: Groq obliga al modelo a respetar el schema (con JSON por prompt,
                # en recetas largas a veces no calzaba y se perdía la llamada).
                yield m, "json_schema", lambda m=m: ChatGroq(model=m, api_key=groq_key, temperature=0, max_retries=1)
    router_key = get_env_var("OPENROUTER_API_KEY")
    if router_key and _available("openrouter"):
        from langchain_openai import ChatOpenAI
        yield "openrouter", "prompt", lambda: ChatOpenAI(model="google/gemma-4-31b-it:free", api_key=router_key,
                                                          base_url="https://openrouter.ai/api/v1", temperature=0)


def invoke_structured(messages: list, schema: Type[T], lite: bool = False) -> T:
    """Devuelve un objeto `schema`. Gemini usa structured output nativo; Groq/OpenRouter, JSON por prompt."""
    from langchain_core.messages import SystemMessage
    from langchain_core.output_parsers import PydanticOutputParser
    parser = PydanticOutputParser(pydantic_object=schema)
    last: Optional[Exception] = None
    for name, mode, build in _providers(lite):
        try:
            if mode == "native":
                result = build().with_structured_output(schema).invoke(messages)
            elif mode == "json_schema":
                result = build().with_structured_output(schema, method="json_schema").invoke(messages)
            else:
                hint = SystemMessage(content="Responde SOLO con JSON válido, sin markdown:\n" + parser.get_format_instructions())
                result = parser.invoke(build().invoke([*messages, hint]))
            if result is not None:
                return result
        except Exception as e:
            last = e
            if is_quota_error(e):
                _pause(name)
            else:
                print(f"   [llm_chain] {name} falló ({type(e).__name__}: {str(e)[:120]}), probando el siguiente")
    raise AllProvidersExhausted(f"RESOURCE_EXHAUSTED: ningún modelo disponible. Último error: {last}")


def invoke_json(prompt, variables: dict, lite: bool = True) -> dict:
    """Corre un ChatPromptTemplate que pide JSON y devuelve el dict parseado."""
    from langchain_core.output_parsers import JsonOutputParser
    last: Optional[Exception] = None
    for name, _mode, build in _providers(lite):
        try:
            return (prompt | build() | JsonOutputParser()).invoke(variables)
        except Exception as e:
            last = e
            if is_quota_error(e):
                _pause(name)
            else:
                print(f"   [llm_chain] {name} falló ({type(e).__name__}: {str(e)[:120]}), probando el siguiente")
    raise AllProvidersExhausted(f"RESOURCE_EXHAUSTED: ningún modelo disponible. Último error: {last}")
