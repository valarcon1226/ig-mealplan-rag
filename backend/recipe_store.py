"""
recipe_store.py
================
Persiste una receta ya procesada por el pipeline de LangChain en la base
relacional (SQLite) que /api/recipes y el Cookbook realmente consumen.

Antes de esto, run_recipe_pipeline() solo guardaba en recetas_db.json, y la
única forma de que una receta llegara a SQLite era correr manualmente
migrate_data.py o sync_backup_to_sqlite.py contra ese JSON. El pipeline en
vivo (usado por /analyze-langchain-by-id y el procesamiento en lote de
carpetas) nunca tocaba SQLite, así que una receta recién analizada no
aparecía en el Cookbook hasta que alguien corriera ese script a mano.
"""
import json

from database import SessionLocal
from models import Recipe, NutritionInformation
from recipe_search import canon_cuisine


def persist_recipe_to_sqlite(media_id: str, final_recipe: dict, post: dict = None) -> dict:
    """Crea o actualiza el Recipe en SQLite a partir del resultado del pipeline."""
    post = post or {}
    if not final_recipe.get("is_recipe"):
        return {"saved": False, "reason": "not_a_recipe"}

    db = SessionLocal()
    try:
        nut_data = final_recipe.get("nutricion_por_porcion", {}) or {}
        nutrition_fields = dict(
            calories=float(nut_data.get("kcal", nut_data.get("calorias", 0)) or 0),
            proteins=float(nut_data.get("proteina_g", 0) or 0),
            carbohydrates=float(nut_data.get("carbohidratos_g", 0) or 0),
            fats=float(nut_data.get("grasas_g", nut_data.get("grasa_g", 0)) or 0),
            sugars=float(nut_data["azucares_g"]) if nut_data.get("azucares_g") is not None else None,
            fiber=float(nut_data["fibra_g"]) if nut_data.get("fibra_g") is not None else None,
        )

        time_prep = final_recipe.get("tiempo_preparacion_min")
        try:
            time_prep = int(float(time_prep)) if time_prep is not None else None
        except (ValueError, TypeError):
            time_prep = None

        servings_val = final_recipe.get("porciones_ajustadas") or final_recipe.get("porciones_originales") or 1
        try:
            servings_val = int(round(float(servings_val)))
        except (ValueError, TypeError):
            servings_val = 1

        ingredientes = final_recipe.get("ingredientes_ajustados") or final_recipe.get("ingredientes", [])
        tags = final_recipe.get("tags", []) or []

        recipe = db.query(Recipe).filter(Recipe.media_id == media_id).first()
        if recipe:
            if recipe.nutrition:
                # Si esta vez no se pudo calcular (sin cantidades), no pisar la nutrición que ya había con ceros.
                if nut_data:
                    for field, value in nutrition_fields.items():
                        setattr(recipe.nutrition, field, value)
            else:
                nutrition = NutritionInformation(**nutrition_fields)
                db.add(nutrition)
                recipe.nutrition = nutrition
        else:
            nutrition = NutritionInformation(**nutrition_fields)
            db.add(nutrition)
            recipe = Recipe(media_id=media_id, nutrition=nutrition)
            db.add(recipe)

        recipe.nombre = final_recipe.get("nombre") or "Sin nombre"
        # Se guarda el texto original del post para poder re-extraer más adelante sin Instagram.
        recipe.caption = post.get("caption") or recipe.caption
        # Al re-procesar, no pisar lo que ya había si esta vez no salió nada.
        recipe.video_url = final_recipe.get("video_url") or post.get("url") or post.get("video_url") or recipe.video_url
        recipe.thumbnail_url = final_recipe.get("thumbnail_url") or post.get("thumbnail_url") or recipe.thumbnail_url
        recipe.category = final_recipe.get("categoria") or recipe.category
        recipe.raw_text = final_recipe.get("texto_extraido") or recipe.raw_text
        if final_recipe.get("estructura"):
            recipe.structured_json = json.dumps(final_recipe["estructura"], ensure_ascii=False)
        recipe.tiempo_preparacion_min = time_prep
        if nut_data or not recipe.servings:  # las porciones van con la nutrición por porción que se conserva
            recipe.servings = servings_val
        recipe.tags = ", ".join(str(t).lower().strip() for t in tags) if tags else None
        recipe.instructions = json.dumps(final_recipe.get("instrucciones", []), ensure_ascii=False)
        recipe.ingredients_raw = json.dumps(ingredientes, ensure_ascii=False)
        recipe.cuisine_type = canon_cuisine(final_recipe.get("tipo_cocina"))
        recipe.dificultad = (final_recipe.get("dificultad") or "").lower().strip() or None

        db.commit()
        recipe_id = recipe.id
    finally:
        db.close()

    # Vectorizar en el mismo paso: antes había que correr populate_db.py a mano
    # y las recetas nuevas no aparecían en la búsqueda ni en el planner.
    indexed = False
    try:
        from vector_db import index_recipes
        index_recipes([media_id])
        indexed = True
    except Exception as e:
        print(f"[recipe_store] Aviso: '{media_id}' guardada pero no vectorizada ({e}). Corre populate_db.py.")
    return {"saved": True, "recipe_id": recipe_id, "indexed": indexed}
