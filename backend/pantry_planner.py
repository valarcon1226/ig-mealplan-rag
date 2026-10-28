"""
pantry_planner.py
=================
Plan de comidas usando solo lo que hay en la despensa, armado DÍA POR DÍA:
cada día se llena con recetas que alcanzan con lo que queda, y se descuentan
sus ingredientes de una despensa virtual. Se para en el primer día que no se
puede completar, así el resultado dice "con lo que tienes alcanzan N días".

- Candidatos por búsqueda vectorial (tipo de comida + lo que hay en la despensa,
  filtrado por calorías de la comida), con los mismos filtros de dieta del planner.
- La disponibilidad es aritmética exacta (unidades de shopping_list), no un LLM.
- Se permiten faltantes chicos: hasta MAX_MISSING ingredientes, nunca el principal
  (el de más cantidad); la comida trae "faltantes" para mostrar "te falta: limón".
"""
import json
from typing import Any, Dict, List, Optional

from models import PantryItem, Recipe
from rag_planner import RAGMealPlanner, intake_score
from ingredient_normalizer import normalize_ingredient_name
from shelf_life import days_left
from shopping_list import _load_pantry_lookup, aggregate_ingredients
from vector_db import perform_filtered_search

MAX_MISSING = 1
MEAL_WEIGHTS = {"desayuno": 25, "almuerzo": 30, "comida": 30, "cena": 25, "snack": 10, "postre": 10}


def _needs(meal: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Ingredientes de una comida ya normalizados ({nombre|unidad: {...}}), sin sal/agua."""
    return aggregate_ingredients([meal])


STAPLE_MAX = 15  # g/ml: vainilla, canela, polvo de hornear, un chorrito de aceite... no se exigen


def _words(name: str) -> set:
    return {w.rstrip("s") for w in name.lower().split() if len(w) > 2}  # "plátanos maduros" ~ "plátano"


def _pantry_key(name: str, pantry: Dict[str, Dict[str, float]]) -> Optional[str]:
    """Item de la despensa que cubre este ingrediente: mismo nombre, o todas sus palabras
    contenidas ("yogur griego" cubre "yogur griego de vainilla")."""
    if name in pantry:
        return name
    words = _words(name)
    return next((k for k in pantry if _words(k) and _words(k) <= words), None)


def _required(needs: Dict[str, Dict[str, Any]]) -> list:
    """Ingredientes que hay que tener: con cantidad y no un básico de pocos gramos."""
    return [d for d in needs.values()
            if not d["sin_cantidad"] and not (d["unidad"] in ("g", "ml") and d["cantidad"] <= STAPLE_MAX)]


def _missing(needs: Dict[str, Dict[str, Any]], pantry: Dict[str, Dict[str, float]]) -> Optional[List[str]]:
    """
    Ingredientes que faltan para esta comida, o None si falta el principal o demasiados
    (más de 1 de cada 4). "Al gusto" y los básicos de pocos gramos no se exigen.
    """
    required = _required(needs)
    if not required:
        return None  # sin cantidades no se puede saber si alcanza
    main = max(required, key=lambda d: d["cantidad"] if d["unidad"] in ("g", "ml") else 0)
    missing = []
    for d in required:
        key = _pantry_key(d["display_name"], pantry)
        have = pantry.get(key, {}) if key else {}
        # Misma unidad: comparar cantidades. Otra unidad (ej. "2 pza" vs "300 g"): no se puede
        # convertir, así que basta con que esté en la despensa.
        enough = have.get(d["unidad"], 0) >= d["cantidad"] if d["unidad"] in have else any(v > 0 for v in have.values())
        if not enough:
            if d is main:
                return None
            missing.append(d["display_name"])
    return missing if len(missing) <= max(MAX_MISSING, len(required) // 4) else None


def _consume(needs: Dict[str, Dict[str, Any]], pantry: Dict[str, Dict[str, float]]):
    for d in _required(needs):
        key = _pantry_key(d["display_name"], pantry)
        units = pantry.get(key) if key else None
        if units and d["unidad"] in units:
            units[d["unidad"]] = max(0.0, units[d["unidad"]] - d["cantidad"])


URGENT_DAYS = 7  # lo que vence en una semana o menos se prioriza, más mientras antes venza


def _urgency(needs, pantry, expiry: Dict[str, int], day_index: int) -> int:
    """Cuánto usa la receta de lo que se va a dañar pronto (más alto = usarla antes)."""
    score = 0
    for d in _required(needs):
        key = _pantry_key(d["display_name"], pantry)
        if key in expiry:
            score += max(0, URGENT_DAYS - (expiry[key] - day_index))
    return score


def plan_from_pantry(db, meal_types: List[str], targets: Dict[str, float], restrictions: List[str],
                     profile: Dict[str, Any], max_days: int = 7, user_id: Optional[int] = None) -> Dict[str, Any]:
    planner = RAGMealPlanner(db)
    planner.avoid = [a for a in profile.get("avoid") or [] if a.strip()]
    planner.likes = [l for l in profile.get("likes") or [] if l.strip()]

    query = db.query(PantryItem)
    if user_id is not None:
        query = query.filter(PantryItem.user_id == user_id)
    items = query.all()
    pantry = _load_pantry_lookup(items)
    # Días que le quedan a cada item (normalizado como en la despensa); el más corto si hay repetidos.
    expiry: Dict[str, int] = {}
    for it in items:
        key = normalize_ingredient_name(it.name)
        if key:
            expiry[key] = min(expiry.get(key, 10**6), days_left(it.name, it.added_at))
    if not pantry:
        return {"plan": [], "days_possible": 0,
                "message": "Tu despensa está vacía: registra lo que tienes en Pantry para armar un plan con eso."}
    pantry_text = ", ".join(list(pantry)[:30])

    total_weight = sum(MEAL_WEIGHTS.get(m, 10) for m in meal_types) or 1
    kcal_goal = targets.get("calorias") or 2000
    days, used_recipes = [], set()

    for day_n in range(1, max_days + 1):
        # Se confirma solo si el día sale completo. Lo que para ese día ya se habría dañado no se usa.
        day_pantry = {k: dict(v) for k, v in pantry.items() if expiry.get(k, 10**6) >= day_n - 1}
        meals = []
        for meal_type in meal_types:
            meal_kcal = kcal_goal * MEAL_WEIGHTS.get(meal_type, 10) / total_weight
            # Búsqueda vectorial: tipo de comida + ingredientes de la despensa, en un rango de calorías.
            results = perform_filtered_search(
                planner.collection, query=f"{planner._query(meal_type)} con {pantry_text}",
                min_calories=meal_kcal * 0.5, max_calories=meal_kcal * 1.5, n_results=100)
            options = planner._valid(results, meal_type, restrictions, exclude={m["media_id"] for m in meals})

            best = None
            for opt in options:
                recipe = db.query(Recipe).filter(Recipe.media_id == opt["id"]).first()
                if not recipe:
                    continue
                meal = planner._build_meal(recipe, meal_type)
                needs = _needs(meal)
                missing = _missing(needs, day_pantry)
                if missing is None:
                    continue
                # Primero lo que usa comida por vencer (no desperdiciar); luego menos faltantes,
                # no repetir recetas de días anteriores y calorías cercanas.
                rank = (-_urgency(needs, day_pantry, expiry, day_n - 1), len(missing),
                        recipe.id in used_recipes, abs(meal["calorias"] - meal_kcal))
                if best is None or rank < best[0]:
                    best = (rank, meal, needs, missing)
            if best is None:
                break
            _, meal, needs, missing = best
            meal["faltantes"] = missing
            _consume(needs, day_pantry)
            meals.append(meal)

        if len(meals) < len(meal_types):
            break  # este día ya no alcanza: el plan termina en el anterior
        pantry = day_pantry
        used_recipes |= {m["recipe_id"] for m in meals}
        totals = {k: sum(m[k] for m in meals) for k in ("calorias", "proteinas", "carbohidratos", "grasas", "fibra", "azucar")}
        day_targets = {**targets, "fibra": round(planner.fiber_target(totals["proteinas"], targets))}
        score = intake_score(totals, day_targets, goal=profile.get("goal") or "maintain",
                             is_pregnant=bool(profile.get("is_pregnant")))
        days.append({"day": day_n, "score": score["total"], "score_breakdown": score["breakdown"],
                     "totals": totals, "targets": day_targets, "meals": meals})

    n = len(days)
    if n == 0:
        message = ("Con lo que tienes no alcanza para un día completo de "
                   f"{', '.join(meal_types)}. Haz mercado o prueba con menos comidas por día.")
    elif n < max_days:
        message = f"Con lo que tienes alcanza para {n} día{'s' if n > 1 else ''}. Para más días, haz mercado."
    else:
        message = f"Con lo que tienes alcanza para los {n} días que pediste."
    # Perecibles que vencen dentro del plan y quedan sin usar: avisar para no botarlos.
    horizon = max(n, 1)
    wasted = sorted(k for k, units in pantry.items()
                    if expiry.get(k, 10**6) < horizon + URGENT_DAYS and expiry.get(k, 10**6) <= URGENT_DAYS
                    and any(q > 0 for q in units.values()))
    if wasted:
        many = len(wasted) > 1
        message += (f" Ojo: {', '.join(wasted)} {'vencen' if many else 'vence'} pronto y no se "
                    f"{'alcanzan' if many else 'alcanza'} a usar en el plan: úsa{'los' if many else 'lo'} aparte o congéla{'los' if many else 'lo'}.")
    return {"plan": days, "days_possible": n, "message": message, "por_vencer_sin_usar": wasted}


if __name__ == "__main__":
    # Chequeo de la aritmética de disponibilidad: python pantry_planner.py
    need = _needs({"ingredients": [{"name": "arroz", "amount": "200 g"}, {"name": "limón", "amount": "1"},
                                   {"name": "sal", "amount": "al gusto"}]})
    assert _missing(need, {"arroz": {"g": 500}, "limón": {"pza": 2}}) == []
    assert _missing(need, {"arroz": {"g": 500}}) == ["limón"]          # falta uno chico: se permite
    assert _missing(need, {"limón": {"pza": 2}}) is None                # falta el principal: no
    assert _missing(need, {"arroz": {"g": 100}, "limón": {"pza": 2}}) is None  # no alcanza el principal
    p = {"arroz": {"g": 500}, "limón": {"pza": 2}}
    _consume(need, p)
    assert p == {"arroz": {"g": 300}, "limón": {"pza": 1}}
    bowl = _needs({"ingredients": [{"name": "yogur griego de vainilla", "amount": "200 g"},
                                   {"name": "canela", "amount": "5 g"}]})
    assert _missing(bowl, {"yogur griego": {"g": 500}}) == []  # nombre flexible; canela es básico
    print("ok")
