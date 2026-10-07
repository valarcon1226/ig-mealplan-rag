"""
ig_media.py
===========
Descarga de medios por URL directa (download_media / download_bytes), con
reintentos, backoff y validación de tamaño; si la URL falla del todo, cae a
yt-dlp como último recurso.

Ya no resuelve posts entrando a una cuenta de Instagram (instagrapi): eso hizo
que Instagram marcara la cuenta. Los guardados se importan desde la exportación
oficial (ig_export.py).
"""
import os
import json
import time
import requests as req_lib


DOWNLOAD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.instagram.com/",
    "Accept": "*/*",
}


class MediaDownloadError(Exception):
    pass


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
