import os
import json
import getpass
from instagrapi import Client

BACKUP_FILE = "recetas_saludables_backup.json"

RECIPE_KEYWORDS = ["receta", "ingredientes", "preparación", "paso a paso", "kcal", "calorias", "calorías", "macros"]

def main():
    print("=== Instagram Collection Downloader ===")
    print("Inicia sesión para ver tus carpetas guardadas.")
    print("\nOPCIÓN RECOMENDADA (Evita bloqueos):")
    print("Ve a instagram.com en tu navegador -> Presiona F12 -> Pestaña 'Application' o 'Storage' -> Cookies.")
    print("Busca la cookie llamada 'sessionid' y copia su valor.")
    print("Si prefieres usar contraseña, deja esto en blanco.\n")
    
    session_id = input("Tu 'sessionid' de Instagram (o presiona Enter para usar contraseña): ").strip()
    
    cl = Client()
    
    if session_id:
        try:
            print("Iniciando sesión usando sessionid...")
            cl.login_by_sessionid(session_id)
            print("Login exitoso con sessionid.")
            session_file = None # No necesitamos archivo temporal si usamos sessionid
        except Exception as e:
            print(f"Error iniciando con sessionid: {e}")
            return
    else:
        ig_user = input("Tu usuario de Instagram: ").strip()
        ig_pass = getpass.getpass("Tu contraseña de Instagram (no se guardará): ")
        session_file = f"temp_ig_session_{ig_user}.json"
        try:
            print(f"Iniciando sesión como {ig_user}...")
            cl.login(ig_user, ig_pass)
            cl.dump_settings(session_file)
            print("Login exitoso.")
        except Exception as e:
            print(f"No se pudo iniciar sesión: {e}")
            print("\nSi sale 'ChallengeResolve' significa que Instagram bloqueó el intento por seguridad.")
            print("Solución: Abre Instagram en tu celular, confirma que 'Fui yo' e intenta de nuevo, O usa el método del 'sessionid' de arriba.")
            return
        
    try:
        print("Obteniendo tus carpetas (colecciones)...")
        collections = cl.collections()
        if not collections:
            print("No tienes colecciones guardadas.")
            return
            
        print("\nCarpetas disponibles:")
        for i, col in enumerate(collections):
            print(f"[{i+1}] {col.name}")
            
        choices = input("\nIngresa los números de las carpetas que quieres descargar (separados por coma, ej: 1,2,4,5): ")
        if not choices.strip():
            print("No seleccionaste ninguna carpeta. Saliendo.")
            return
            
        selected_indices = []
        for x in choices.split(","):
            try:
                idx = int(x.strip()) - 1
                if 0 <= idx < len(collections):
                    selected_indices.append(idx)
            except ValueError:
                pass
                
        if not selected_indices:
            print("Selección inválida.")
            return
            
        # Cargar backup existente
        backup_data = {"posts": []}
        if os.path.exists(BACKUP_FILE):
            try:
                with open(BACKUP_FILE, "r", encoding="utf-8-sig") as f:
                    backup_data = json.load(f)
            except Exception as e:
                print(f"Aviso: No se pudo cargar el backup existente ({e}). Se creará uno nuevo.")
                
        existing_posts = backup_data.get("posts", [])
        existing_media_ids = {p.get("media_id", p.get("id")) for p in existing_posts}
        
        new_posts_count = 0
        
        for idx in selected_indices:
            col = collections[idx]
            print(f"\nDescargando posts de la carpeta '{col.name}'...")
            
            try:
                # Obtener hasta 100 items por colección para no tardar tanto
                medias = cl.collection_medias(col.id, amount=100)
                print(f"  Encontrados {len(medias)} posts.")
                
                for media in medias:
                    # En instagrapi, media_type=1 es foto, 2 es video, 8 es album
                    media_id_str = str(media.pk)
                    if hasattr(media, 'id') and "_" in str(media.id):
                        media_id_str = str(media.pk) + "_" + str(media.id).split("_")[1]
                        
                    if media_id_str in existing_media_ids:
                        continue
                        
                    caption_text = media.caption_text if hasattr(media, 'caption_text') else ""
                    caption_lower = caption_text.lower()
                    has_recipe_caption = any(kw in caption_lower for kw in RECIPE_KEYWORDS)
                    
                    video_url = ""
                    thumb_url = ""
                    
                    if media.media_type == 2: # Video
                        video_url = str(media.video_url) if media.video_url else ""
                        thumb_url = str(media.thumbnail_url) if media.thumbnail_url else ""
                    elif media.media_type == 8 and media.resources: # Album (Carousel)
                        # Tomar el primero
                        first_res = media.resources[0]
                        if first_res.media_type == 2:
                            video_url = str(first_res.video_url) if first_res.video_url else ""
                            thumb_url = str(first_res.thumbnail_url) if first_res.thumbnail_url else ""
                        else:
                            thumb_url = str(first_res.thumbnail_url) if first_res.thumbnail_url else ""
                    else: # Imagen normal
                        thumb_url = str(media.thumbnail_url) if media.thumbnail_url else ""
                    
                    post_data = {
                        "media_id": media_id_str,
                        "url": video_url or thumb_url,
                        "video_url": video_url,
                        "thumbnail_url": thumb_url,
                        "caption": caption_text,
                        "media_type": "video" if video_url else "image",
                        "taken_at": media.taken_at.timestamp() if hasattr(media, 'taken_at') and media.taken_at else None,
                        "has_recipe_caption": has_recipe_caption,
                        "workflow": "A_caption" if has_recipe_caption else "B_whisper"
                    }
                    
                    existing_posts.append(post_data)
                    existing_media_ids.add(media_id_str)
                    new_posts_count += 1
                    
            except Exception as e:
                print(f"  Error al descargar la carpeta '{col.name}': {e}")
                
        backup_data["posts"] = existing_posts
        
        print(f"\nGuardando {new_posts_count} posts nuevos en {BACKUP_FILE}...")
        with open(BACKUP_FILE, "w", encoding="utf-8-sig") as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=4)
            
        print("¡Listo! Ya puedes correr batch_processor.py")

    finally:
        if 'session_file' in locals() and session_file and os.path.exists(session_file):
            os.remove(session_file)
            print("(Sesión de IG eliminada por seguridad)")

if __name__ == "__main__":
    main()
