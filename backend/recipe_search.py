"""
recipe_search.py
================
Búsqueda en lenguaje natural del Cookbook ("postre sin azúcar", "cena rápida
con pollo", "algo asiático alto en proteína").

Solo con embeddings no alcanza: "comida china" devolvía polos de fresa y
"postre sin azúcar" un helado con chocolate, porque la similitud vectorial no
entiende negaciones ni categorías. Por eso:

  1. El LLM convierte la búsqueda en filtros estructurados (cocina, tipo de
     comida, kcal/proteína/azúcar, dietas, ingredientes a incluir/excluir) y
     un texto para la parte semántica.
  2. Chroma aplica los filtros numéricos/cocina y ordena por similitud.
  3. Python aplica el resto (tipo de comida, dietas, ingredientes).
"""
from functools import lru_cache
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from diet import DIET_LABELS, avoids, fold

CUISINES = ["internacional", "italiana", "mediterranea", "asiatica", "mexicana", "americana", "india", "latina", "francesa"]
# Países/variantes que el pipeline o el usuario escriben -> una de CUISINES.
CUISINE_ALIASES = {
    **dict.fromkeys(["china", "japonesa", "coreana", "thai", "tailandesa", "vietnamita", "filipina"], "asiatica"),
    **dict.fromkeys(["griega", "espanola", "turca", "libanesa", "arabe", "marroqui"], "mediterranea"),
    **dict.fromkeys(["colombiana", "venezolana", "peruana", "argentina", "cubana", "brasilena"], "latina"),
    **dict.fromkeys(["cajun", "estadounidense", "tex-mex"], "americana"),
}


def canon_cuisine(value: Optional[str]) -> Optional[str]:
    """Cocina en su forma única (sin tildes, de CUISINES). Lo desconocido o "fusión" -> internacional."""
    v = fold(value)
    if not v:
        return None
    v = CUISINE_ALIASES.get(v, v)
    return v if v in CUISINES else "internacional"
MEAL_TYPES = ["desayuno", "almuerzo", "cena", "snack", "postre", "bebida"]


class SearchFilters(BaseModel):
    texto_semantico: str = Field("", description="lo que se busca, sin las restricciones ya puestas en otros campos; vacío si la búsqueda es solo filtros")
    cocina: Optional[Literal[tuple(CUISINES)]] = None
    tipo_comida: Optional[Literal[tuple(MEAL_TYPES)]] = None
    max_calorias: Optional[float] = None
    min_proteina: Optional[float] = None
    max_azucar: Optional[float] = None
    max_tiempo_min: Optional[int] = None
    dietas: List[Literal[tuple(DIET_LABELS)]] = []
    incluir_ingredientes: List[str] = []
    excluir_ingredientes: List[str] = []


PROMPT = f"""Convierte la búsqueda de recetas del usuario en filtros. Reglas:
- cocina: SOLO si el usuario nombra una cocina o país (no la deduzcas de un plato: "pasta" no implica italiana). Una de {CUISINES}. "china", "japonesa", "coreana", "thai" -> "asiatica"; "griega", "española" -> "mediterranea"; "colombiana", "peruana" -> "latina".
- tipo_comida: uno de {MEAL_TYPES} solo si lo pide ("algo dulce" -> postre).
- "sin azúcar" / "bajo en azúcar" -> max_azucar 5. "alto en proteína" / "proteico" -> min_proteina 25. "ligero" / "bajo en calorías" -> max_calorias 400. "rápido" -> max_tiempo_min 20.
- dietas: de {DIET_LABELS} ("vegano", "sin gluten", "para diabéticos" -> "Apto Diabético").
- incluir_ingredientes / excluir_ingredientes: ingredientes concretos, cada uno como "español/inglés" en singular, porque las recetas mezclan idiomas ("con pollo" -> incluir "pollo/chicken"; "sin cebolla" -> excluir "cebolla/onion").
- texto_semantico: el resto de la idea en pocas palabras ("cremoso", "crujiente", "chocolate"). Si la búsqueda ya quedó toda en filtros, déjalo vacío.
No inventes filtros que el usuario no pidió."""


@lru_cache(maxsize=1)
def _collection():
    from vector_db import get_chroma_client, get_or_create_collection
    return get_or_create_collection(get_chroma_client())


def _parse(query: str) -> SearchFilters:
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_pipeline import get_env_var

    api_key = get_env_var("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Falta GEMINI_API_KEY.")
    llm = ChatGoogleGenerativeAI(model="gemini-flash-lite-latest", google_api_key=api_key, temperature=0)
    result = llm.with_structured_output(SearchFilters).invoke([SystemMessage(content=PROMPT), HumanMessage(content=query)])
    return result or SearchFilters(texto_semantico=query)


def _has_structured(f: SearchFilters) -> bool:
    return any([f.cocina, f.tipo_comida, f.max_calorias is not None, f.min_proteina is not None,
                f.max_azucar is not None, f.max_tiempo_min is not None, f.dietas,
                f.incluir_ingredientes, f.excluir_ingredientes])


def filter_and_rank(results: List[dict], f: SearchFilters) -> List[str]:
    """Aplica en Python lo que Chroma no filtra y, si solo hay texto, corta por similitud."""
    kept = []
    for r in results:
        tags = {fold(t) for t in (r.get("tags") or "").split(",")}
        cumple = {fold(d) for d in (r.get("restricciones") or "").split(",")}
        texts = [r.get("nombre"), r.get("ingredientes")]
        if f.tipo_comida and f.tipo_comida not in tags:
            continue
        if any(fold(d) not in cumple for d in f.dietas):
            continue
        # "pollo/chicken": vale cualquiera de las variantes. avoids()=True -> no contiene ninguna.
        if any(avoids(texts, ing.split("/")) for ing in f.incluir_ingredientes):
            continue
        if not avoids(texts, [v for ing in f.excluir_ingredientes for v in ing.split("/")]):
            continue
        kept.append(r)
    if f.texto_semantico and kept:
        # Hay una idea que buscar ("chocolate", "cremoso"): solo lo cercano al mejor
        # resultado, no todos los postres. Si la búsqueda es solo filtros, van todos.
        # ponytail: umbral fijo medido a mano con all-MiniLM-L6-v2; recalibrar si cambia el modelo.
        # Con filtros, el piso absoluto podría vaciar la lista: solo se corta relativo al mejor.
        floor = 0.0 if _has_structured(f) else 0.25
        cutoff = max(floor, kept[0]["similarity_score"] - 0.2)
        kept = [r for r in kept if r["similarity_score"] >= cutoff]
    return [r["id"] for r in kept]


@lru_cache(maxsize=256)
def search(query: str) -> dict:
    """{"media_ids": [...en orden de relevancia], "filters": {...lo que entendió el LLM}}"""
    from vector_db import perform_filtered_search

    f = _parse(query)
    col = _collection()
    results = perform_filtered_search(
        col, query,  # la búsqueda completa da más contexto al ranking que solo texto_semantico
        max_calories=f.max_calorias, min_protein=f.min_proteina, max_sugar=f.max_azucar,
        max_time=f.max_tiempo_min, cuisine_type=f.cocina, n_results=col.count() or 1,
    )
    return {"media_ids": filter_and_rank(results, f), "filters": f.model_dump(exclude_defaults=True)}


if __name__ == "__main__":
    rows = [
        {"id": "a", "nombre": "Pollo crispy", "ingredientes": "200 g de pollo, harina", "tags": "cena", "restricciones": "Sin Lácteos", "similarity_score": 0.6},
        {"id": "b", "nombre": "Ensalada", "ingredientes": "lechuga, cebolla", "tags": "almuerzo", "restricciones": "Vegano, Vegetariano", "similarity_score": 0.5},
        {"id": "c", "nombre": "Brownie", "ingredientes": "chocolate", "tags": "postre", "restricciones": "Vegetariano", "similarity_score": 0.1},
    ]
    assert filter_and_rank(rows, SearchFilters(tipo_comida="cena")) == ["a"]
    assert filter_and_rank(rows, SearchFilters(dietas=["Vegano"])) == ["b"]
    assert filter_and_rank(rows, SearchFilters(incluir_ingredientes=["pollo"])) == ["a"]
    assert filter_and_rank(rows, SearchFilters(excluir_ingredientes=["cebolla/onion"])) == ["a", "c"]
    assert filter_and_rank(rows, SearchFilters(incluir_ingredientes=["pollo/chicken"])) == ["a"]
    rows[1]["ingredientes"] = "lettuce, red onion"
    assert filter_and_rank(rows, SearchFilters(excluir_ingredientes=["cebolla/onion"])) == ["a", "c"]
    assert filter_and_rank(rows, SearchFilters(texto_semantico="crujiente")) == ["a", "b"]  # c bajo el umbral
    assert filter_and_rank(rows, SearchFilters(texto_semantico="crujiente", tipo_comida="postre")) == ["c"]  # el filtro deja solo c
    print("ok")
