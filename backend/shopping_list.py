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
  2. compare_with_pantry(aggregated, pantry_items): devuelve TODO lo que pide
     el plan con la cantidad necesitada, y marca cuánto FALTA tras restar el
     pantry (covered=True si ya alcanza). El frontend lo muestra como checklist.

Por qué no queda todo en manos de un LLM: sumar/restar cantidades es
aritmética exacta, no algo semántico - un LLM con una lista larga de
ingredientes eventualmente se equivoca en una suma. Se usa LLM solo donde
hace falta (interpretar "leche entera" vs "leche" como el mismo ingrediente
ya lo resuelve normalize_ingredient_name con reglas, sin necesidad de IA).
"""
import re
from typing import Any, Dict, List
from collections import defaultdict

from ingredient_normalizer import normalize_ingredient_name, parse_amount_str

# unidad -> (unidad canonica, factor). Permite sumar/restar "1 kg" del pantry
# contra "200 g" de una receta. "" = cantidad sin unidad (ej. "12" huevos),
# que se trata como piezas.
UNIT_ALIASES = {
    **{u: ("g", 1) for u in ("g", "gr", "grs", "gramo", "gramos")},
    **{u: ("g", 1000) for u in ("kg", "kgs", "kilo", "kilos", "kilogramo", "kilogramos")},
    **{u: ("ml", 1) for u in ("ml", "mililitro", "mililitros")},
    **{u: ("g", 453.592) for u in ("lb", "lbs", "libra", "libras")},
    **{u: ("g", 28.3495) for u in ("oz", "onza", "onzas")},
    **{u: ("ml", 1) for u in ("ml", "mililitro", "mililitros")},
    **{u: ("ml", 1000) for u in ("l", "lt", "lts", "litro", "litros")},
    **{u: ("pza", 1) for u in ("", "u", "un", "unidad", "unidades", "pza", "pzas", "pieza", "piezas")},
}


def to_canonical(cantidad: float, unit: str):
    """(1, 'kg') -> (1000.0, 'g'). Unidades desconocidas quedan tal cual."""
    unit = (unit or "").strip().lower().rstrip(".")
    canon, factor = UNIT_ALIASES.get(unit, (unit, 1))
    return cantidad * factor, canon


_FREE_TEXT_RE = re.compile(r"^(\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?)\s*([^\W\d_]+\.?)?\s*(.*)$")


def parse_free_text(text: str):
    """
    "1lb de arroz" -> ("arroz", "1 lb"); "2 huevos" -> ("huevos", "2");
    "1/2 kg pollo" -> ("pollo", "0.5 kg"); "arroz" -> ("arroz", "").
    Si la palabra tras el número no es una unidad conocida, es parte del nombre.
    """
    text = (text or "").strip()
    m = _FREE_TEXT_RE.match(text)
    if not m:
        return text, ""
    num, word, rest = m.groups()
    num = num.replace(",", ".").replace(" ", "")
    if "/" in num:
        a, b = num.split("/")
        if float(b) == 0:
            return text, ""
        qty = float(a) / float(b)
    else:
        qty = float(num)
    unit = ""
    if word and word.lower().rstrip(".") in UNIT_ALIASES:
        unit = word.lower().rstrip(".")
    elif word:
        rest = f"{word} {rest}"
    name = re.sub(r"^de\s+", "", rest.strip(), flags=re.I).strip()
    if not name:
        return text, ""
    return name, f"{qty:g} {unit}".strip()


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

            cantidad, unidad_canonica = to_canonical(*parse_amount_str(str(raw_amount)))
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
        cantidad, unidad_canonica = to_canonical(*parse_amount_str(str(item.amount or "")))
        lookup[normalized][unidad_canonica] = lookup[normalized].get(unidad_canonica, 0.0) + cantidad
    return lookup


def compare_with_pantry(aggregated: Dict[str, Dict[str, Any]], pantry_items: List) -> List[Dict[str, Any]]:
    """
    Devuelve TODO lo que pide el plan (como si el pantry estuviera vacío), y
    por cada item cuánto falta tras restar el pantry:
      {"item", "amount": necesitado, "missing": faltante ("" si ya alcanza), "covered": bool}
    """
    pantry_lookup = _load_pantry_lookup(pantry_items)
    shopping_list = []

    for key, data in aggregated.items():
        name = data["display_name"]
        unidad = data["unidad"]
        necesitado = data["cantidad"]

        if data["sin_cantidad"]:
            # No hay cantidad numerica confiable (ej. "al gusto"): cubierto si
            # el ingrediente está en el pantry en cualquier cantidad.
            covered = name in pantry_lookup
            shopping_list.append({"item": name, "amount": "al gusto",
                                  "missing": "" if covered else "al gusto", "covered": covered})
            continue

        disponible = pantry_lookup.get(name, {}).get(unidad, 0.0)
        faltante = round(necesitado - disponible, 1)
        shopping_list.append({
            "item": name,
            "amount": f"{round(necesitado, 1):g} {unidad}".strip(),
            "missing": f"{faltante:g} {unidad}".strip() if faltante > 0 else "",
            "covered": faltante <= 0,
        })

    return shopping_list


def generate_shopping_list(meal_plan: Any, pantry_items: List) -> List[Dict[str, Any]]:
    aggregated = aggregate_ingredients(meal_plan)
    return compare_with_pantry(aggregated, pantry_items)


if __name__ == "__main__":
    from types import SimpleNamespace as P
    meals = [{"ingredients": [{"name": "huevo", "amount": "2 pza"}, {"name": "arroz", "amount": "200 g"},
                              {"name": "leche", "amount": "300 ml"}, {"name": "sal", "amount": "1 pizca"}]}]
    pantry = [P(name="Huevos", amount="12"), P(name="arroz", amount="1 kg"), P(name="leche", amount="0.25 l")]
    missing = {i["item"]: i["missing"] for i in generate_shopping_list(meals, pantry)}
    assert missing == {"huevo": "", "arroz": "", "leche": "50 ml"}, missing  # sal se excluye
    assert all(not i["covered"] for i in generate_shopping_list(meals, []))  # pantry vacío = todo por comprar
    for text, expected in [("1lb de arroz", ("arroz", "1 lb")), ("2 huevos", ("huevos", "2")),
                           ("1/2 kg pollo", ("pollo", "0.5 kg")), ("1,5 L de leche", ("leche", "1.5 l")),
                           ("arroz", ("arroz", "")), ("3", ("3", ""))]:
        assert parse_free_text(text) == expected, (text, parse_free_text(text))
    assert generate_shopping_list([{"ingredients": [{"name": "arroz", "amount": "500 g"}]}],
                                  [P(name="arroz", amount="1 lb")])[0]["missing"] == "46.4 g"
    print("ok")
