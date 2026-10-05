"""
backfill_reextract.py
=====================
Re-procesa las recetas importadas antes de que se guardara el texto extraído:
vuelve a ver cada video + caption con el pipeline actual (extracción detallada,
categoría, tiempos, tipo de comida, origen), recalcula la nutrición, guarda el
texto crudo y el JSON (raw_text / structured_json) y vectoriza.

Después de esto ya no hace falta volver a Instagram: para mejorar recetas en el
futuro se usa reprocess_recipes.py, que trabaja con el texto guardado.

Requiere sesión de Instagram válida. Uso (desde backend/):

    python backfill_reextract.py valarcon.zip --limit 3   # probar con 3
    python backfill_reextract.py valarcon.zip             # todas

Se puede cortar y volver a correr: salta las que ya tienen raw_text.
"""
import argparse
import sys
import time

from database import SessionLocal
from ig_media import resolve_media, MediaResolutionError
from langchain_pipeline import run_recipe_pipeline, save_recipe, get_env_var
from models import Recipe
from recipe_store import persist_recipe_to_sqlite

PAUSE_SECONDS = 5  # Instagram + Gemini: ir lento evita el rate-limit


def main(username: str, limit: int | None):
    api_key = get_env_var("GEMINI_API_KEY")
    if not api_key:
        sys.exit("Falta GEMINI_API_KEY en backend/.env")

    db = SessionLocal()
    try:
        pending = [(r.media_id, r.nombre) for r in db.query(Recipe).order_by(Recipe.id).all() if not r.raw_text]
    finally:
        db.close()
    if limit:
        pending = pending[:limit]
    print(f"{len(pending)} recetas por re-procesar")
    ok = failed = 0

    for i, (media_id, nombre) in enumerate(pending, 1):
        tag = f"[{i}/{len(pending)}] {nombre}"
        try:
            media = resolve_media(media_id, username, None, allow_cache_fallback=False)
        except MediaResolutionError as e:
            if "login_required" in str(e):
                sys.exit("Sesión de Instagram expirada: inicia sesión desde el Perfil y vuelve a correrlo.")
            print(f"{tag}: no se pudo resolver ({e})")
            failed += 1
            continue

        try:
            recipe = run_recipe_pipeline(media_id=media_id, video_url=media["url"], gemini_api_key=api_key,
                                         caption=media.get("caption", ""), save_to_db=False)
        except Exception as e:
            if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e):
                sys.exit("Sin cuota de Gemini por ahora: vuelve a correrlo más tarde (retoma donde quedó).")
            print(f"{tag}: error en el pipeline ({e})")
            failed += 1
            continue

        # No reemplazar una receta buena por un resultado vacío.
        if not recipe.get("is_recipe") or not recipe.get("ingredientes"):
            print(f"{tag}: el modelo no encontró la receta, se mantiene la actual")
            failed += 1
            continue

        save_recipe(media_id, recipe)
        saved = persist_recipe_to_sqlite(media_id, recipe, {"caption": media.get("caption", "")})
        ok += 1
        print(f"{tag}: ok -> {recipe.get('categoria')}, {len(recipe.get('instrucciones', []))} pasos"
              + ("" if saved.get("indexed") else " (sin vectorizar)"))
        time.sleep(PAUSE_SECONDS)

    print(f"Listo: {ok} re-procesadas, {failed} sin cambios (se reintentan al volver a correrlo).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("username", help="usuario de Instagram con sesión guardada")
    parser.add_argument("--limit", type=int, help="procesar solo N recetas (para probar)")
    args = parser.parse_args()
    main(args.username, args.limit)
