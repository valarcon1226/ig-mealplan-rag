"""
ig_collections.py
==================
Conexión dinámica a las carpetas (colecciones guardadas) de Instagram.

Antes, /collections y /collection-posts/all estaban mockeados: devolvían
siempre la misma carpeta falsa y leían siempre el mismo backup estático,
sin importar qué carpeta pedías ni si tenía cosas nuevas.

Ahora:
  - list_collections_live(): pregunta a Instagram en vivo qué carpetas existen.
  - sync_collection_posts(): trae los posts de UNA carpeta específica y los
    persiste (tagueados con collection_id) en el backup local — pero solo
    si pasó suficiente tiempo desde la última sincronización (TTL), para no
    pegarle a Instagram en cada click del usuario.
"""
import os
import json
import datetime

from database import SessionLocal
from models import CollectionSyncState

BACKUP_FILE = "recetas_saludables_backup.json"
RECIPE_KEYWORDS = ["receta", "ingredientes", "preparación", "paso a paso", "kcal", "calorias", "calorías", "macros"]

DEFAULT_TTL_SECONDS = 30 * 60  # 30 minutos: suficiente para no re-pedir en cada click, corto para no perderse posts nuevos


def list_collections_live(user_cl) -> list:
    """Trae las carpetas (colecciones guardadas) reales del usuario desde Instagram."""
    collections = user_cl.collections()
    return [
        {
            "collection_id": str(c.id),
            "name": c.name,
            "media_count": getattr(c, "media_count", None),
        }
        for c in collections
    ]


def _extract_post(media, collection_id: str) -> dict:
    caption_text = media.caption_text if hasattr(media, "caption_text") else ""
    caption_lower = caption_text.lower()
    has_recipe_caption = any(kw in caption_lower for kw in RECIPE_KEYWORDS)

    video_url = ""
    thumb_url = ""
    if media.media_type == 2:  # Video
        video_url = str(media.video_url) if media.video_url else ""
        thumb_url = str(media.thumbnail_url) if media.thumbnail_url else ""
    elif media.media_type == 8 and media.resources:  # Álbum/carrusel: primer recurso
        first_res = media.resources[0]
        if first_res.media_type == 2:
            video_url = str(first_res.video_url) if first_res.video_url else ""
        thumb_url = str(first_res.thumbnail_url) if first_res.thumbnail_url else ""
    else:  # Imagen
        thumb_url = str(media.thumbnail_url) if media.thumbnail_url else ""

    return {
        "media_id": str(media.pk),
        "collection_id": collection_id,
        "url": video_url or thumb_url,
        "video_url": video_url,
        "thumbnail_url": thumb_url,
        "caption": caption_text,
        "media_type": "video" if video_url else "image",
        "taken_at": media.taken_at.timestamp() if getattr(media, "taken_at", None) else None,
        "has_recipe_caption": has_recipe_caption,
        "workflow": "A_caption" if has_recipe_caption else "B_whisper",
    }


def _load_backup() -> dict:
    if os.path.exists(BACKUP_FILE):
        try:
            with open(BACKUP_FILE, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            pass
    return {"posts": []}


def _save_backup(data: dict):
    with open(BACKUP_FILE, "w", encoding="utf-8-sig") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def sync_collection_posts(
    collection_id: str,
    user_cl,
    collection_name: str = None,
    amount: int = 50,
    force: bool = False,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict:
    """
    Trae los posts de una carpeta desde Instagram y los guarda en el backup
    local, tagueados con collection_id. Si ya se sincronizó hace menos de
    `ttl_seconds`, NO le pega a Instagram (a menos que force=True) — este es
    el mecanismo para reducir consumo innecesario que discutimos.
    """
    db = SessionLocal()
    try:
        state = db.query(CollectionSyncState).filter(CollectionSyncState.collection_id == collection_id).first()
        now = datetime.datetime.utcnow()

        if state and not force and state.last_synced_at:
            elapsed = (now - state.last_synced_at).total_seconds()
            if elapsed < ttl_seconds:
                return {
                    "synced": False,
                    "reason": "cache_fresh",
                    "seconds_since_last_sync": int(elapsed),
                    "last_synced_at": state.last_synced_at.isoformat(),
                }

        medias = user_cl.collection_medias(collection_id, amount=amount)

        backup = _load_backup()
        posts = backup.get("posts", [])
        existing_ids = {p.get("media_id") for p in posts}

        new_count = 0
        for media in medias:
            post = _extract_post(media, collection_id)
            if post["media_id"] in existing_ids:
                continue
            posts.append(post)
            existing_ids.add(post["media_id"])
            new_count += 1

        backup["posts"] = posts
        _save_backup(backup)

        total_for_collection = sum(1 for p in posts if p.get("collection_id") == collection_id)

        if not state:
            state = CollectionSyncState(collection_id=collection_id)
            db.add(state)
        state.collection_name = collection_name or state.collection_name
        state.last_synced_at = now
        state.posts_synced = total_for_collection
        db.commit()

        return {"synced": True, "new_posts": new_count, "total_posts": total_for_collection}
    finally:
        db.close()


def get_posts_for_collection(collection_id: str) -> list:
    backup = _load_backup()
    return [p for p in backup.get("posts", []) if p.get("collection_id") == collection_id]
