"""
ig_media.py
===========
Punto único para dos cosas que antes estaban duplicadas (con lógica distinta
y divergente) entre ig_recetas.py y langchain_pipeline.py:

  1. resolve_media()   -> obtener la URL real de un post de Instagram
  2. download_media()  -> bajar ese video a disco de forma confiable

Por qué existía un bug real antes de esto:
  Las video_url de Instagram son URLs firmadas de su CDN con expiración
  corta (horas). /analyze-langchain-by-id resolvía la URL leyendo un backup
  estático (recetas_saludables_backup.json) en vez de preguntarle a
  Instagram en vivo, así que cualquier post con URL vencida o no presente
  en ese backup fallaba (o, peor, usaba por error el primer post del
  backup - ver el fallback roto que tenía antes con `posts[0]`).

Ahora:
  - resolve_media() SIEMPRE intenta Instagram en vivo primero (vía
    instagrapi, reusando la sesión persistente de ig_auth). El backup local
    solo se usa como fallback explícito si Instagram no está disponible
    (sin sesión, rate limit, etc.), y nunca devuelve un post equivocado.
  - download_media() reintenta con backoff ante fallas de red (la causa
    típica del IncompleteRead documentado en el proyecto), valida el
    tamaño descargado contra Content-Length cuando está disponible, y si
    la URL directa falla del todo, cae a yt-dlp (que resuelve una URL
    fresca a partir del shortcode) como último recurso.
"""
import os
import json
import time
import requests as req_lib

from ig_auth import get_client_for_user

BACKUP_FILE = "recetas_saludables_backup.json"

DOWNLOAD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.instagram.com/",
    "Accept": "*/*",
}


class MediaResolutionError(Exception):
    pass


class MediaDownloadError(Exception):
    pass


def _media_pk(media_id: str) -> str:
    return media_id.split("_")[0] if "_" in media_id else media_id


def _resolve_from_instagram(media_id: str, username: str = None, password: str = None) -> dict:
    user_cl = get_client_for_user(username, password)  # puede lanzar HTTPException si no hay sesión
    media_pk = _media_pk(media_id)
    try:
        media = user_cl.media_info_v1(media_pk)
    except Exception:
        media = user_cl.media_info(media_pk)

    video_url = None
    thumbnail_url = None

    if media.media_type == 2:  # Video
        video_url = str(media.video_url) if media.video_url else None
        thumbnail_url = str(media.thumbnail_url) if media.thumbnail_url else None
    elif media.media_type == 8 and media.resources:  # Álbum/carrusel: usamos el primer recurso
        first = media.resources[0]
        if first.media_type == 2:
            video_url = str(first.video_url) if first.video_url else None
        thumbnail_url = str(first.thumbnail_url) if first.thumbnail_url else None
    else:  # Imagen
        thumbnail_url = str(media.thumbnail_url) if media.thumbnail_url else None

    caption = getattr(media, "caption_text", "") or ""

    return {
        "media_id": media_id,
        "media_type": "video" if video_url else "image",
        "video_url": video_url,
        "thumbnail_url": thumbnail_url,
        "url": video_url or thumbnail_url,
        "caption": caption,
        "source": "live",
    }


def _resolve_from_backup(media_id: str) -> dict:
    if not os.path.exists(BACKUP_FILE):
        raise MediaResolutionError(f"No se encontró {media_id} en Instagram y no existe backup local ({BACKUP_FILE}).")

    with open(BACKUP_FILE, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    post = next((p for p in data.get("posts", []) if p.get("media_id") == media_id), None)
    if not post:
        # Importante: NO caer al primer post del backup. Si no está, es un error real.
        raise MediaResolutionError(f"media_id {media_id} no encontrado en Instagram (en vivo) ni en el backup local.")

    video_url = post.get("video_url") or None
    thumb_url = post.get("thumbnail_url") or None
    url = post.get("url") or video_url or thumb_url

    return {
        "media_id": media_id,
        "media_type": post.get("media_type", "video" if video_url else "image"),
        "video_url": video_url,
        "thumbnail_url": thumb_url,
        "url": url,
        "caption": post.get("caption", post.get("caption_text", "")),
        "source": "cache",
    }


def resolve_media(media_id: str, username: str = None, password: str = None, allow_cache_fallback: bool = True) -> dict:
    """
    Resuelve un media_id de Instagram a sus URLs reales.
    Intenta Instagram en vivo primero; solo usa el backup local como
    fallback explícito (y lo marca con source="cache" para que quien
    consuma esto sepa que la URL podría estar vencida).
    """
    try:
        return _resolve_from_instagram(media_id, username, password)
    except Exception as live_err:
        if not allow_cache_fallback:
            raise MediaResolutionError(f"No se pudo resolver {media_id} en vivo: {live_err}") from live_err
        try:
            result = _resolve_from_backup(media_id)
            print(f"[ig_media] Aviso: {media_id} resuelto desde cache local (Instagram en vivo falló: {live_err}). La URL puede estar vencida.")
            return result
        except MediaResolutionError:
            raise
        except Exception as cache_err:
            raise MediaResolutionError(
                f"No se pudo resolver {media_id}: Instagram en vivo falló ({live_err}) y el fallback a cache también falló ({cache_err})."
            ) from cache_err


def download_media(url: str, dest_path: str, media_id: str = None, retries: int = 4, backoff: float = 2.0, timeout: int = 120) -> dict:
    """
    Descarga `url` a `dest_path` con reintentos y backoff exponencial.
    Verifica el tamaño descargado contra Content-Length cuando el servidor lo envía.
    Si todos los intentos directos fallan y se pasó media_id, cae a yt-dlp
    (re-resuelve una URL fresca a partir del shortcode) como último recurso.
    """
    last_error = None

    if url:
        for attempt in range(1, retries + 1):
            try:
                resp = req_lib.get(url, timeout=timeout, stream=True, headers=DOWNLOAD_HEADERS)
                resp.raise_for_status()

                content_type = resp.headers.get("Content-Type", "")
                if content_type.startswith(("text/html", "text/plain", "application/json")):
                    # La URL es una página normal (ej. tiktok.com/@user/video/...), no un
                    # link directo al archivo. No hay nada que reintentar acá - hace
                    # falta yt-dlp para resolver la URL real del video.
                    raise MediaDownloadError(f"La URL devolvió {content_type}, no un archivo de media directo.")

                expected_size = resp.headers.get("Content-Length")
                expected_size = int(expected_size) if expected_size and expected_size.isdigit() else None

                bytes_written = 0
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            bytes_written += len(chunk)

                if expected_size is not None and bytes_written < expected_size:
                    raise MediaDownloadError(
                        f"Descarga incompleta: se esperaban {expected_size} bytes, se recibieron {bytes_written}."
                    )
                if bytes_written == 0:
                    raise MediaDownloadError("Descarga vacía (0 bytes).")

                return {"path": dest_path, "bytes": bytes_written, "attempts": attempt, "method": "direct"}

            except Exception as e:
                last_error = e
                print(f"[ig_media] Intento {attempt}/{retries} de descarga directa falló para {media_id or url}: {e}")
                if os.path.exists(dest_path):
                    try:
                        os.remove(dest_path)
                    except OSError:
                        pass
                if attempt < retries:
                    time.sleep(backoff * attempt)

    # Fallback 1: yt-dlp directo sobre la URL original. Funciona para cualquier
    # sitio que yt-dlp soporte (TikTok, YouTube, IG público, etc.) - no asume
    # nada especifico de Instagram, solo necesita una URL de video/post real.
    if url:
        try:
            from ig_downloader import download_via_ytdlp
            print(f"[ig_media] Cayendo a yt-dlp sobre la URL para {media_id or url}.")
            download_via_ytdlp(url, dest_path)
            if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
                return {"path": dest_path, "bytes": os.path.getsize(dest_path), "attempts": retries + 1, "method": "yt-dlp-url"}
        except Exception as e:
            last_error = e

    # Fallback 2: reconstruir una URL de instagram.com a partir del media_id
    # (solo tiene sentido para posts de IG cuya video_url directa expiró).
    if media_id:
        try:
            from ig_downloader import download_ig_video
            print(f"[ig_media] Cayendo a yt-dlp por shortcode de IG para {media_id}.")
            download_ig_video(media_id, dest_path)
            if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
                return {"path": dest_path, "bytes": os.path.getsize(dest_path), "attempts": retries + 1, "method": "yt-dlp-ig-shortcode"}
            raise MediaDownloadError("yt-dlp no produjo un archivo válido.")
        except Exception as ytdlp_err:
            last_error = ytdlp_err

    raise MediaDownloadError(f"No se pudo descargar el media (media_id={media_id}). Último error: {last_error}")


def download_bytes(url: str, retries: int = 4, backoff: float = 2.0, timeout: int = 60) -> bytes:
    """Igual que download_media pero en memoria, para imágenes (sin fallback yt-dlp)."""
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            resp = req_lib.get(url, timeout=timeout, headers=DOWNLOAD_HEADERS)
            resp.raise_for_status()
            if not resp.content:
                raise MediaDownloadError("Descarga vacía (0 bytes).")
            return resp.content
        except Exception as e:
            last_error = e
            print(f"[ig_media] Intento {attempt}/{retries} de descarga de imagen falló: {e}")
            if attempt < retries:
                time.sleep(backoff * attempt)
    raise MediaDownloadError(f"No se pudo descargar la imagen. Último error: {last_error}")


def transcribe_media(local_path: str, gemini_api_key: str, prompt: str, mime_type: str = "video/mp4", poll_attempts: int = 12, poll_interval: int = 5) -> str:
    """
    Sube un archivo local a la Gemini Files API, espera a que quede ACTIVE, y
    le pide a Gemini que responda `prompt` sobre su contenido (transcripción,
    descripción, lo que sea). Genérico a propósito: no asume nada sobre el
    dominio del contenido (recetas, tech, etc.) - eso lo decide el prompt.
    """
    with open(local_path, "rb") as f:
        media_bytes = f.read()

    boundary = "bound_ig_media_transcribe"
    metadata = json.dumps({"file": {"display_name": os.path.basename(local_path)}}).encode()
    body = (
        f"--{boundary}\r\nContent-Type: application/json\r\n\r\n"
    ).encode() + metadata + (
        f"\r\n--{boundary}\r\nContent-Type: {mime_type}\r\n\r\n"
    ).encode() + media_bytes + f"\r\n--{boundary}--\r\n".encode()

    upload_resp = req_lib.post(
        f"https://generativelanguage.googleapis.com/upload/v1beta/files?uploadType=multipart&key={gemini_api_key}",
        headers={"Content-Type": f"multipart/related; boundary={boundary}"},
        data=body,
        timeout=120,
    )
    upload_resp.raise_for_status()
    file_uri = upload_resp.json()["file"]["uri"]
    file_name = upload_resp.json()["file"]["name"]

    for _ in range(poll_attempts):
        time.sleep(poll_interval)
        try:
            status_resp = req_lib.get(
                f"https://generativelanguage.googleapis.com/v1beta/{file_name}?key={gemini_api_key}",
                timeout=30,
            )
            if status_resp.ok and status_resp.json().get("state") == "ACTIVE":
                break
        except Exception:
            pass

    gen_resp = req_lib.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={gemini_api_key}",
        json={"contents": [{"parts": [
            {"file_data": {"mime_type": mime_type, "file_uri": file_uri}},
            {"text": prompt},
        ]}]},
        timeout=90,
    )
    gen_resp.raise_for_status()
    return gen_resp.json()["candidates"][0]["content"]["parts"][0]["text"]
