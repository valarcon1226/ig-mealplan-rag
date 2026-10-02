"""
backfill_thumbnails.py
======================
Muchas recetas guardaban como thumbnail_url la URL del CDN de Instagram (a veces
la del .mp4), que caduca, así que el Cookbook las mostraba sin imagen. Este script
pide a Instagram la portada actual de cada una y la guarda en static/thumbnails.

Requiere una sesión de Instagram válida: inicia sesión desde el Perfil de la app
antes de correrlo. Uso (desde backend/):

    .\\venv\\Scripts\\python.exe backfill_thumbnails.py valarc0n

Va lento a propósito (una receta cada pocos segundos) para no gatillar el
rate-limit de Instagram. Se puede cortar y volver a correr: salta las ya listas.
"""
import sys
import time

from database import SessionLocal
from ig_media import resolve_media, MediaResolutionError
from models import Recipe
from video_utils import save_remote_image

PAUSE_SECONDS = 4


def main(username: str):
    db = SessionLocal()
    try:
        pending = [r for r in db.query(Recipe).all()
                   if not (r.thumbnail_url or "").startswith("/static/")]
        print(f"{len(pending)} recetas sin imagen local")
        fixed = failed = 0
        for i, recipe in enumerate(pending, 1):
            try:
                media = resolve_media(recipe.media_id, username, None, allow_cache_fallback=False)
            except MediaResolutionError as e:
                if "login_required" in str(e):
                    sys.exit("Sesión de Instagram expirada: inicia sesión desde el Perfil y vuelve a correrlo.")
                print(f"[{i}/{len(pending)}] {recipe.media_id}: {e}")
                failed += 1
                continue
            path = save_remote_image(media.get("thumbnail_url"), recipe.media_id)
            if path:
                recipe.thumbnail_url = path
                db.commit()  # por receta: si se corta, no se pierde lo avanzado
                fixed += 1
                print(f"[{i}/{len(pending)}] ok {recipe.nombre}")
            else:
                failed += 1
                print(f"[{i}/{len(pending)}] sin portada: {recipe.nombre}")
            time.sleep(PAUSE_SECONDS)
        print(f"Listo: {fixed} recuperadas, {failed} sin recuperar (esas muestran el ícono del plato).")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Uso: python backfill_thumbnails.py <usuario_instagram>")
    main(sys.argv[1])
