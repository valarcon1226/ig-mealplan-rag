"""
backfill_servings_nutrition.py
==============================
Las recetas ya guardadas tienen porciones y nutrición poco creíbles: 196 de
285 quedaron con servings=1 aunque sus macros "por porción" eran los de una
porción normal (ej. tostadas de 4.5 kg = "1 porción de 685 kcal"). Ver
nutrition_calc.py para el cálculo nuevo.

Uso (desde backend/):
  python backfill_servings_nutrition.py              # auditoría, sin LLM ni escrituras
  python backfill_servings_nutrition.py --apply      # recalcula SOLO las no creíbles
  python backfill_servings_nutrition.py --apply --ids 1,62,135
  python backfill_servings_nutrition.py --apply --limit 10

La auditoría es determinística: compara kcal y gramos por porción contra el
rango de su tipo de comida y revisa que las kcal cuadren con los macros.
Las recetas sin cantidades se listan pero no se tocan (no hay con qué calcular).

--apply hace antes una copia de ig_scrapp.db, guarda receta por receta (se
puede cortar y volver a correr: las ya corregidas pasan la auditoría) y
actualiza también recetas_db.json. Después hay que re-indexar la base
vectorial con populate_db.py (el planner filtra por calorías desde ahí).
"""
import argparse
import csv
import json
import shutil
import time
from datetime import datetime

from database import SessionLocal
from ingredient_normalizer import parse_amount_str
from models import NutritionInformation, Recipe
from nutrition_calc import CATEGORIES, calculate, category_for, has_usable_quantities
from shopping_list import to_canonical

DB_FILE = "ig_scrapp.db"
REPORT_FILE = "servings_audit.csv"


def _ingredients(recipe: Recipe) -> list:
    try:
        ings = json.loads(recipe.ingredients_raw or "[]")
    except (TypeError, ValueError):
        return []
    return [i for i in ings if isinstance(i, dict)]


def _tags(recipe: Recipe) -> list:
    return [t.strip() for t in (recipe.tags or "").split(",") if t.strip()]


def audit(recipe: Recipe) -> list:
    """Motivos por los que la receta no es creíble ([] = creíble)."""
    ings = _ingredients(recipe)
    if not has_usable_quantities(ings):
        return ["sin_cantidades"]

    n = recipe.nutrition
    if not n or not n.calories:
        return ["sin_nutricion"]

    servings = recipe.servings or 1
    cat = CATEGORIES[category_for(_tags(recipe))]
    reasons = []
    if not cat["kcal"][0] <= n.calories <= cat["kcal"][1]:
        reasons.append(f"kcal_por_porcion={n.calories:g}")

    # Solo se suman g/ml; "2 pza" no cuenta, por eso solo se mira el máximo.
    grams = 0.0
    for i in ings:
        q, unit = to_canonical(*parse_amount_str(f"{i.get('cantidad') or ''} {i.get('unidad') or ''}".strip()))
        if unit in ("g", "ml"):
            grams += q or 0
    if grams / servings > cat["grams"][1]:
        reasons.append(f"gramos_por_porcion={grams / servings:.0f}")

    from_macros = 4 * (n.proteins or 0) + 4 * (n.carbohydrates or 0) + 9 * (n.fats or 0)
    if from_macros and abs(from_macros - n.calories) > 0.25 * max(n.calories, from_macros):
        reasons.append(f"macros_no_cuadran({from_macros:.0f}≠{n.calories:g})")
    return reasons


def _update_json_backup(media_id: str, servings: int, nutricion: dict):
    from langchain_pipeline import load_recipes_db, save_recipes_db
    db_json = load_recipes_db()
    entry = db_json.get(media_id)
    if not isinstance(entry, dict):
        return
    entry["porciones_originales"] = servings
    entry["porciones_ajustadas"] = servings
    entry["nutricion_por_porcion"] = nutricion
    entry["origen_nutricional"] = "Calculado por IA (por ingrediente)"
    save_recipes_db(db_json)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="recalcula y guarda las recetas no creíbles")
    parser.add_argument("--ids", help="solo estos ids de receta, separados por coma")
    parser.add_argument("--limit", type=int, help="máximo de recetas a recalcular")
    args = parser.parse_args()
    ids = {int(x) for x in args.ids.split(",")} if args.ids else None

    db = SessionLocal()
    try:
        recipes = db.query(Recipe).order_by(Recipe.id).all()
        flagged = []
        with open(REPORT_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "nombre", "servings", "kcal_por_porcion", "categoria", "motivos"])
            for r in recipes:
                reasons = audit(r)
                writer.writerow([r.id, r.nombre, r.servings, r.nutrition.calories if r.nutrition else "",
                                 category_for(_tags(r)), "; ".join(reasons)])
                if reasons:
                    flagged.append((r, reasons))

        sin_cantidades = [r for r, why in flagged if why == ["sin_cantidades"]]
        to_fix = [(r, why) for r, why in flagged if why != ["sin_cantidades"]]
        print(f"Recetas: {len(recipes)} | creíbles: {len(recipes) - len(flagged)} | "
              f"a recalcular: {len(to_fix)} | sin cantidades (no se tocan): {len(sin_cantidades)}")
        print(f"Reporte: {REPORT_FILE}")
        for r in sin_cantidades:
            print(f"  sin cantidades: [{r.id}] {r.nombre}")

        if not args.apply:
            print("\nDry run. Usa --apply para recalcular.")
            return

        if ids:
            to_fix = [(r, why) for r, why in to_fix if r.id in ids]
        if args.limit:
            to_fix = to_fix[:args.limit]

        backup = f"{DB_FILE}.bak-{datetime.now():%Y%m%d-%H%M%S}"
        shutil.copy2(DB_FILE, backup)
        print(f"\nBackup: {backup}\nRecalculando {len(to_fix)} recetas...\n")

        failed = []
        for idx, (r, why) in enumerate(to_fix, 1):
            before = f"{r.servings} porc · {r.nutrition.calories if r.nutrition else 0:g} kcal"
            try:
                calc = calculate(r.nombre, _tags(r), _ingredients(r), texto=r.caption or "")
            except Exception as e:
                failed.append((r.id, r.nombre, str(e)[:120]))
                print(f"[{idx}/{len(to_fix)}] ERROR [{r.id}] {r.nombre}: {str(e)[:120]}")
                continue
            if calc["status"] != "ok":
                continue

            n = calc["nutricion_por_porcion"]
            if not r.nutrition:
                r.nutrition = NutritionInformation()
                db.add(r.nutrition)
            r.servings = calc["porciones"]
            r.nutrition.calories = n["kcal"]
            r.nutrition.proteins = n["proteina_g"]
            r.nutrition.carbohydrates = n["carbohidratos_g"]
            r.nutrition.fats = n["grasa_g"]
            r.nutrition.sugars = n["azucares_g"]
            r.nutrition.fiber = n["fibra_g"]
            db.commit()
            _update_json_backup(r.media_id, calc["porciones"], {
                "calorias": n["kcal"], "proteina_g": n["proteina_g"], "carbohidratos_g": n["carbohidratos_g"],
                "grasa_g": n["grasa_g"], "azucares_g": n["azucares_g"], "fibra_g": n["fibra_g"],
            })
            print(f"[{idx}/{len(to_fix)}] [{r.id}] {r.nombre} ({'; '.join(why)})\n"
                  f"    antes: {before}  ->  ahora: {r.servings} porc · {n['kcal']:g} kcal, "
                  f"{n['proteina_g']:g}p/{n['carbohidratos_g']:g}c/{n['grasa_g']:g}g "
                  f"(total {calc['totales']['kcal']:g} kcal, {calc['totales']['gramos']} g, {calc['categoria']})")
            time.sleep(4)  # cortesía para el rate limit de Gemini

        if failed:
            print(f"\n{len(failed)} con error (se pueden reintentar volviendo a correr el script):")
            for row in failed:
                print("  ", row)
        print("\nListo. Re-indexa la base vectorial con: python populate_db.py")
    finally:
        db.close()


if __name__ == "__main__":
    main()
