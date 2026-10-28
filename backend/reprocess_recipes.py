"""
reprocess_recipes.py
====================
Vuelve a estructurar recetas a partir del texto que ya se extrajo de su video
(columna raw_text), con el prompt y las reglas actuales. No usa Instagram ni
descarga videos: sirve para aplicar mejoras del prompt (nuevos campos, mejores
categorías) a todo el recetario. Recalcula la nutrición y re-vectoriza.

Uso (desde backend/):
    python reprocess_recipes.py --limit 3     # probar con 3
    python reprocess_recipes.py               # todas las que tienen raw_text
    python reprocess_recipes.py --id 42       # una receta por su id
    python reprocess_recipes.py --sin-nutricion   # solo las que quedaron en 0 kcal
"""
import argparse
import sys
import time

from database import SessionLocal
from langchain_pipeline import structure_recipe, calculate_nutrition, save_recipe, get_env_var
from models import Recipe
from recipe_store import persist_recipe_to_sqlite


def main(limit: int | None, recipe_id: int | None, missing_nutrition: bool = False):
    api_key = get_env_var("GEMINI_API_KEY")
    if not api_key:
        sys.exit("Falta GEMINI_API_KEY en backend/.env")

    db = SessionLocal()
    try:
        query = db.query(Recipe).filter(Recipe.raw_text.isnot(None))
        if recipe_id:
            query = query.filter(Recipe.id == recipe_id)
        rows = [(r.media_id, r.nombre, r.raw_text) for r in query.order_by(Recipe.id).all()
                # sin nutrición = 0 kcal: el extractor no encontró cantidades y no se pudo calcular
                if not missing_nutrition or not r.nutrition or not r.nutrition.calories]
    finally:
        db.close()
    if limit:
        rows = rows[:limit]
    print(f"{len(rows)} recetas con texto guardado")
    ok = failed = 0

    for i, (media_id, nombre, raw_text) in enumerate(rows, 1):
        tag = f"[{i}/{len(rows)}] {nombre}"
        try:
            # video_url vacío: no se re-descarga nada; la foto y el video guardados se mantienen.
            state = structure_recipe({"raw_text": raw_text, "media_id": media_id, "video_url": "", "gemini_api_key": api_key})
            recipe = calculate_nutrition({**state, "target_servings": 0})["final_recipe"]
        except Exception as e:
            if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e):
                sys.exit("Sin cuota de Gemini por ahora: vuelve a correrlo más tarde.")
            print(f"{tag}: error ({e})")
            failed += 1
            continue
        if not recipe.get("is_recipe") or not recipe.get("ingredientes"):
            print(f"{tag}: resultado vacío, se mantiene la actual")
            failed += 1
            continue
        save_recipe(media_id, recipe)
        persist_recipe_to_sqlite(media_id, recipe)
        ok += 1
        print(f"{tag}: ok -> {recipe.get('categoria')}")
        time.sleep(1)

    print(f"Listo: {ok} re-procesadas, {failed} sin cambios.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--id", type=int, dest="recipe_id")
    parser.add_argument("--sin-nutricion", action="store_true", dest="missing_nutrition",
                        help="solo las recetas que quedaron sin nutrición (0 kcal)")
    args = parser.parse_args()
    main(args.limit, args.recipe_id, args.missing_nutrition)
