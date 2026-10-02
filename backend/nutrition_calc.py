"""
nutrition_calc.py
=================
Calcula porciones y nutrición POR PORCIÓN de una receta de forma coherente
con sus ingredientes.

Antes, el LLM adivinaba por separado las porciones (casi siempre 1) y unos
macros "por porción" que no cuadraban con los ingredientes (ej. unas tostadas
de 4.5 kg guardadas como "1 porción de 685 kcal"). Ahora:

  1. El LLM solo estima lo que sabe estimar: gramos y macros de CADA
     ingrediente (valores de referencia tipo USDA), y si el texto dice
     explícitamente cuántas porciones rinde.
  2. Python suma los totales, elige las porciones (las explícitas, o las que
     dejan cada porción dentro del rango típico de su tipo de comida) y divide.

Si los ingredientes no tienen cantidades usables no se inventa nada:
se devuelve status "sin_cantidades".
"""
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

MACROS = ("kcal", "proteina_g", "carbohidratos_g", "grasa_g", "azucares_g", "fibra_g")

# Rangos por porción: kcal (min, max), gramos/ml (min, max) y kcal típicas de una porción.
CATEGORIES = {
    "condimento": {"kcal": (0, 250), "grams": (5, 80), "typical_kcal": 60},
    "bebida": {"kcal": (0, 400), "grams": (100, 600), "typical_kcal": 150},
    "suplemento": {"kcal": (0, 300), "grams": (3, 600), "typical_kcal": 100},
    "comida": {"kcal": (250, 1000), "grams": (150, 800), "typical_kcal": 550},
    "desayuno": {"kcal": (150, 800), "grams": (80, 600), "typical_kcal": 400},
    "postre_snack": {"kcal": (80, 500), "grams": (30, 350), "typical_kcal": 250},
}
CONDIMENT_TAGS = {"condimento", "salsa", "aderezo", "dip", "untable", "topping", "mermelada"}


def category_for(tags: List[str]) -> str:
    """El tag más restrictivo gana: una salsa con tag 'cena' sigue siendo salsa."""
    tags = {t.strip().lower() for t in tags or []}
    if tags & CONDIMENT_TAGS:
        return "condimento"
    if "bebida" in tags:
        return "bebida"
    if "suplemento" in tags:
        return "suplemento"
    if tags & {"almuerzo", "cena"}:
        return "comida"
    if "desayuno" in tags:
        return "desayuno"
    if tags & {"postre", "snack", "merienda", "aperitivo"}:
        return "postre_snack"
    return "comida"


def has_usable_quantities(ingredients: List[Dict[str, Any]]) -> bool:
    """False si no hay cantidades o si todas son el placeholder '1 g' que deja el LLM."""
    qtys = []
    for ing in ingredients or []:
        try:
            q = float(ing.get("cantidad"))
        except (TypeError, ValueError):
            continue
        if q > 0:
            qtys.append((q, str(ing.get("unidad") or "").strip().lower()))
    if not qtys:
        return False
    return not (len(qtys) >= 2 and all(q == 1 and u in ("g", "gr", "") for q, u in qtys))


def in_range(per_serving_kcal: float, per_serving_grams: float, category: str) -> bool:
    c = CATEGORIES[category]
    ok_kcal = c["kcal"][0] <= per_serving_kcal <= c["kcal"][1]
    ok_grams = per_serving_grams <= 0 or c["grams"][0] <= per_serving_grams <= c["grams"][1]
    return ok_kcal and ok_grams


def choose_servings(total_kcal: float, total_grams: float, category: str,
                    explicit: Optional[int], suggested: Optional[int]) -> int:
    """Las porciones explícitas de la receta mandan; si no, la sugerencia del LLM
    solo se acepta si deja cada porción dentro del rango de su categoría."""
    if explicit and explicit >= 1:
        return int(explicit)
    if suggested and suggested >= 1 and in_range(total_kcal / suggested, total_grams / suggested, category):
        return int(suggested)
    return max(1, round(total_kcal / CATEGORIES[category]["typical_kcal"]))


def per_serving(totals: Dict[str, float], servings: int) -> Dict[str, float]:
    out = {k: round(totals.get(k, 0.0) / servings, 1) for k in MACROS}
    # Si las kcal no cuadran con 4p + 4c + 9g (>25%), se confía en los macros.
    from_macros = 4 * out["proteina_g"] + 4 * out["carbohidratos_g"] + 9 * out["grasa_g"]
    if from_macros > 0 and abs(from_macros - out["kcal"]) > 0.25 * max(out["kcal"], from_macros):
        out["kcal"] = round(from_macros, 1)
    return out


# ── LLM: valores por ingrediente ──────────────────────────────────────────────

class IngredientNutrition(BaseModel):
    nombre: str
    gramos: float = Field(description="peso o volumen total del ingrediente en g/ml")
    kcal: float
    proteina_g: float
    carbohidratos_g: float
    grasa_g: float
    azucares_g: float
    fibra_g: float


class RecipeNutrition(BaseModel):
    ingredientes: List[IngredientNutrition]
    porciones_explicitas: Optional[int] = Field(None, description="solo si el texto dice cuántas porciones rinde")
    porciones_sugeridas: int


NUTRITION_PROMPT = """Eres un nutricionista. Para la receta de abajo:
1. Para CADA ingrediente, con la cantidad indicada (que es para la receta COMPLETA): convierte a gramos (o ml) y da sus kcal, proteína, carbohidratos, grasa, azúcares y fibra PARA ESA CANTIDAD, usando valores de referencia estándar (tipo USDA) del ingrediente tal como se lista (crudo si es crudo, cocido si dice cocido). Estima el peso de unidades ("2 huevos" = 100 g, "1 taza de arroz" = 185 g). No omitas ingredientes; agua y sal llevan 0.
2. porciones_explicitas: el número de porciones SOLO si el texto lo dice explícitamente; si no, null.
3. porciones_sugeridas: cuántas porciones normales de una persona rinde la receta completa (una comida principal ~400-700 kcal, un snack o postre ~150-350 kcal, una salsa o aderezo ~30 g, una bebida ~250 ml).
No calcules totales ni divisiones: solo los valores de cada ingrediente."""


def _ask_llm(nombre: str, tags: List[str], ingredients: List[Dict[str, Any]], texto: str = "",
             api_key: str = "", max_retries: int = 4) -> RecipeNutrition:
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_pipeline import get_env_var

    api_key = api_key or get_env_var("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Falta GEMINI_API_KEY.")
    llm = ChatGoogleGenerativeAI(model="gemini-flash-latest", google_api_key=api_key, temperature=0)
    lines = "\n".join(f"- {i.get('nombre')}: {i.get('cantidad') or '?'} {i.get('unidad') or ''}".rstrip()
                      for i in ingredients)
    human = f"Receta: {nombre}\nTags: {', '.join(tags or [])}\nIngredientes:\n{lines}"
    if texto:
        human += f"\n\nTexto original:\n{texto[:4000]}"

    wait = 15
    for attempt in range(max_retries):
        try:
            result = llm.with_structured_output(RecipeNutrition).invoke(
                [SystemMessage(content=NUTRITION_PROMPT), HumanMessage(content=human)])
            if result is None or not result.ingredientes:
                raise ValueError("El LLM no devolvió valores por ingrediente.")
            return result
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                if attempt < max_retries - 1:
                    time.sleep(wait)
                    wait *= 2
                    continue
            raise


def calculate(nombre: str, tags: List[str], ingredients: List[Dict[str, Any]],
              texto: str = "", porciones_explicitas: Optional[int] = None, api_key: str = "") -> Dict[str, Any]:
    """
    Devuelve {"status": "ok", "porciones", "categoria", "totales", "nutricion_por_porcion"}
    o {"status": "sin_cantidades"} si no hay cantidades con qué calcular.
    """
    if not has_usable_quantities(ingredients):
        return {"status": "sin_cantidades"}

    llm_result = _ask_llm(nombre, tags, ingredients, texto, api_key)
    totals = {k: sum(max(getattr(i, k), 0.0) for i in llm_result.ingredientes) for k in MACROS}
    total_grams = sum(max(i.gramos, 0.0) for i in llm_result.ingredientes)
    category = category_for(tags)
    servings = choose_servings(totals["kcal"], total_grams, category,
                               porciones_explicitas or llm_result.porciones_explicitas,
                               llm_result.porciones_sugeridas)
    return {
        "status": "ok",
        "porciones": servings,
        "categoria": category,
        "totales": {**{k: round(v, 1) for k, v in totals.items()}, "gramos": round(total_grams)},
        "nutricion_por_porcion": per_serving(totals, servings),
    }


if __name__ == "__main__":
    assert category_for(["almuerzo", "cena", "salsa"]) == "condimento"
    assert category_for(["desayuno", "snack"]) == "desayuno"
    assert category_for([]) == "comida"
    assert not has_usable_quantities([{"cantidad": None}, {"cantidad": None}])
    assert not has_usable_quantities([{"cantidad": 1, "unidad": "g"}, {"cantidad": 1, "unidad": "g"}])
    assert has_usable_quantities([{"cantidad": 400, "unidad": "g"}])
    # 4.5 kg / 4000 kcal de tostadas: la sugerencia "1" no pasa el rango y se recalcula.
    assert choose_servings(4000, 4500, "comida", None, 1) == 7
    assert choose_servings(4000, 4500, "comida", None, 6) == 6
    assert choose_servings(4000, 4500, "comida", 4, 1) == 4  # explícitas mandan
    assert choose_servings(12, 800, "bebida", None, None) == 1
    ps = per_serving({"kcal": 1000, "proteina_g": 50, "carbohidratos_g": 100, "grasa_g": 40,
                      "azucares_g": 10, "fibra_g": 8}, 2)
    assert ps == {"kcal": 500, "proteina_g": 25, "carbohidratos_g": 50, "grasa_g": 20,
                  "azucares_g": 5, "fibra_g": 4}, ps
    assert per_serving({"kcal": 100, "proteina_g": 10, "carbohidratos_g": 10, "grasa_g": 10}, 1)["kcal"] == 170
    print("ok")
