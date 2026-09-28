"""
shopping_list.py
=================
Genera la lista de compras a partir de un plan de comidas YA GENERADO,
sumando ingredientes de forma determinística (Python, no un LLM adivinando
sumas) y comparando contra el pantry.

Flujo:
  1. aggregate_ingredients(meals): junta todos los ingredientes de todas las
     recetas del plan (día o semana) y SUMA las cantidades de un mismo
     ingrediente entre recetas (si 3 recetas piden 300ml de leche cada una,
     el total es 900ml - no una lista con 3 líneas de "300ml de leche").
  2. compare_with_pantry(aggregated, pantry_items): resta lo que ya hay en
     el pantry. Si falta parte o todo, se agrega a la lista de compras con
     la cantidad FALTANTE (no la cantidad total necesitada).

Por qué no queda todo en manos de un LLM: sumar/restar cantidades es
aritmética exacta, no algo semántico - un LLM con una lista larga de
ingredientes eventualmente se equivoca en una suma. Se usa LLM solo donde
hace falta (interpretar "leche entera" vs "leche" como el mismo ingrediente
ya lo resuelve normalize_ingredient_name con reglas, sin necesidad de IA).
"""
from typing import Any, Dict, List
from collections import defaultdict

from ingredient_normalizer import normalize_ingredient_name, parse_amount_str

# Unidades que consideramos "iguales" entre si para poder sumar directo.
# Los prompts de estructuracion de recetas ya piden normalizar a g/ml, asi
# que en la practica casi todo llega en estas unidades.
COMPATIBLE_UNIT_GROUPS = [
    {"g", "gr", "gramo", "gramos"},
    {"ml", "mililitro", "mililitros"},
    {"unidad", "unidades", "u", "pza", "pzas"},
]


def _canonical_unit(unit: str) -> str:
    unit = (unit or "").strip().lower()
    for group in COMPATIBLE_UNIT_GROUPS:
        if unit in group:
            return sorted(group)[0]  # representante estable del grupo
    return unit


def _iter_meals(meal_plan: Any):
    """Acepta {"meals": [...]}  (dia), [{"meals": [...]}, ...] (semana), o ya un [...] plano de meals."""
    if meal_plan is None:
        return
    if isinstance(meal_plan, dict) and "meals" in meal_plan:
        yield from meal_plan["meals"]
    elif isinstance(meal_plan, list):
        for entry in meal_plan:
            if isinstance(entry, dict) and "meals" in entry:
                yield from entry["meals"]
            elif isinstance(entry, dict) and ("name" in entry or "ingredients" in entry):
                yield entry  # ya es un meal individual


def aggregate_ingredients(meal_plan: Any) -> Dict[str, Dict[str, Any]]:
    """
    Devuelve {normalized_name: {"cantidad": float, "unidad": str, "display_name": str, "sin_cantidad": bool}}
    Suma cantidades del mismo ingrediente+unidad entre todas las recetas del plan.
    Si el mismo ingrediente aparece con unidades incompatibles, se guardan como
    entradas separadas (normalized_name + unidad) para no sumar cosas distintas.
    """
    totals: Dict[str, Dict[str, Any]] = {}

    for meal in _iter_meals(meal_plan):
        for ing in meal.get("ingredients", []):
            raw_name = ing.get("name") or ing.get("nombre") or ""
            raw_amount = ing.get("amount") or ""

            normalized = normalize_ingredient_name(raw_name)
            if not normalized:
                continue  # agua, sal, etc. - no van a la lista de compras

            cantidad, unidad = parse_amount_str(str(raw_amount))
            unidad_canonica = _canonical_unit(unidad)
            sin_cantidad = cantidad == 0.0  # "al gusto", "una pizca", etc.

            key = f"{normalized}|{unidad_canonica}"
            if key not in totals:
                totals[key] = {
                    "cantidad": 0.0,
                    "unidad": unidad_canonica,
                    "display_name": normalized,
                    "sin_cantidad": False,
                }

            if sin_cantidad:
                totals[key]["sin_cantidad"] = True
            else:
                totals[key]["cantidad"] += cantidad

    return totals


def _load_pantry_lookup(pantry_items: List) -> Dict[str, Dict[str, float]]:
    """pantry_items: lista de objetos con .name y .amount (PantryItem de SQL)."""
    lookup: Dict[str, Dict[str, float]] = defaultdict(dict)
    for item in pantry_items:
        normalized = normalize_ingredient_name(item.name)
        if not normalized:
            continue
        cantidad, unidad = parse_amount_str(str(item.amount or ""))
        unidad_canonica = _canonical_unit(unidad)
        lookup[normalized][unidad_canonica] = lookup[normalized].get(unidad_canonica, 0.0) + cantidad
    return lookup


def compare_with_pantry(aggregated: Dict[str, Dict[str, Any]], pantry_items: List) -> List[Dict[str, Any]]:
    """Resta lo que ya hay en el pantry. Devuelve solo lo que falta comprar."""
    pantry_lookup = _load_pantry_lookup(pantry_items)
    shopping_list = []

    for key, data in aggregated.items():
        name = data["display_name"]
        unidad = data["unidad"]
        necesitado = data["cantidad"]

        if data["sin_cantidad"]:
            # No hay cantidad numerica confiable (ej. "al gusto") - se agrega
            # como recordatorio, sin intentar restar del pantry.
            shopping_list.append({"item": name, "amount": "al gusto / cantidad no especificada"})
            continue

        disponible = pantry_lookup.get(name, {}).get(unidad, 0.0)
        faltante = round(necesitado - disponible, 1)

        if faltante > 0:
            shopping_list.append({"item": name, "amount": f"{faltante} {unidad}".strip()})
        # si faltante <= 0, ya hay suficiente en el pantry - no se agrega

    return shopping_list


def generate_shopping_list(meal_plan: Any, pantry_items: List) -> List[Dict[str, Any]]:
    aggregated = aggregate_ingredients(meal_plan)
    return compare_with_pantry(aggregated, pantry_items)
