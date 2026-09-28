"""
export_ia_collection.py
========================
Exporta la carpeta "ia" de Instagram al proyecto YouTube-RAG-Analyzer.

Instagram no tiene transcripts nativos como YouTube, así que por cada post:
  1. Se resuelve la URL en vivo (ig_media.resolve_media) y se descarga
     (ig_media.download_media) - igual que en ig-scrapp-app.
  2. Gemini "ve" el video/imagen y genera una transcripción detallada
     (ig_media.transcribe_media, prompt genérico, no de recetas).
  3. Esa transcripción se pasa por el MISMO pipeline de 4 fases de
     YouTube-RAG-Analyzer (main.py: phase1_extract -> phase2_deduplicate ->
     phase3_synthesize -> phase4_validate) para que el resultado tenga el
     mismo formato que el resto de Results/.
  4. Se guarda {título}.md + {título}_transcript.txt en Results/IG/.

Es resumible: cada media_id procesado se anota en Results/IG/vistos_ig.json
apenas termina, así que podés parar el script (Ctrl+C) y correrlo de nuevo
más tarde sin repetir trabajo ni gastar cuota de más.

Uso (parado en ig-scrapp-app/backend, con el venv activo):
    .\\venv\\Scripts\\python.exe export_ia_collection.py
"""
import os
import sys
import json
import time
import tempfile

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
RAG_PROJECT_DIR = r"C:\Users\valentina.alarcon\Documents\Cursos\Claudio\Portfolio Gemini\YouTube-RAG-Analyzer"
OUTPUT_DIR = os.path.join(RAG_PROJECT_DIR, "Results", "IG")
VISTOS_FILE = os.path.join(OUTPUT_DIR, "vistos_ig.json")

COLLECTION_ID = "18009659414702518"  # carpeta "ia"
IG_USERNAME = "valarcon.zip"  # la sesión ya guardada (ig_session_valarcon.zip.json)

sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, RAG_PROJECT_DIR)

from ig_auth import get_client_for_user
from ig_media import resolve_media, download_media, transcribe_media, MediaResolutionError, MediaDownloadError
from ig_collections import sync_collection_posts, get_posts_for_collection

from main import (  # del proyecto YouTube-RAG-Analyzer
    create_client, phase1_extract, phase2_deduplicate, phase3_synthesize,
    phase4_validate, detect_language, sanitize_filename, Fact,
    MAX_CHARS_PER_CHUNK, token_usage,
)


def _get_gemini_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    env_path = os.path.join(BACKEND_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("GEMINI_API_KEY="):
                    return line.strip().split("=", 1)[1]
    raise RuntimeError("No se encontró GEMINI_API_KEY (ni en el entorno ni en backend/.env).")


TRANSCRIPTION_PROMPT = (
    "Eres un transcriptor experto. Observa este video o imagen de Instagram y describe TODO "
    "lo que se dice y se muestra, de la forma más completa y detallada posible: cualquier "
    "texto en pantalla, lo que se explica verbalmente, herramientas, comandos, código o links "
    "mencionados. Redactá como si fuera la transcripción completa del contenido (no un resumen). "
    "Si el contenido está en español, respondé en español; si está en inglés, en inglés. "
    "Si el contenido no tiene nada de valor informativo (ej. solo música o un meme sin texto), "
    "respondé únicamente: 'SIN_CONTENIDO_INFORMATIVO'."
)

TITLE_PROMPT_TEMPLATE = (
    "En base a esta transcripción, generá un título corto (6-12 palabras), descriptivo y "
    "específico de qué trata el contenido, en el mismo idioma de la transcripción. "
    "Respondé ÚNICAMENTE con el título, sin comillas ni texto adicional.\n\nTranscripción:\n{transcript}"
)


def load_vistos() -> set:
    if os.path.exists(VISTOS_FILE):
        try:
            with open(VISTOS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def save_vistos(vistos: set):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(VISTOS_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(vistos), f, ensure_ascii=False, indent=2)


def process_post(rag_client, post: dict, gemini_api_key: str) -> str:
    media_id = post["media_id"]

    resolved = resolve_media(media_id, IG_USERNAME)  # URL fresca, no la vieja del sync inicial
    url = resolved.get("url")
    if not url:
        return "skipped: sin URL resoluble"

    mime_type = "video/mp4" if resolved.get("media_type") == "video" else "image/jpeg"
    suffix = ".mp4" if mime_type == "video/mp4" else ".jpg"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name

    try:
        download_media(url, tmp_path, media_id=media_id)
        transcript = transcribe_media(tmp_path, gemini_api_key, TRANSCRIPTION_PROMPT, mime_type=mime_type)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    transcript = (transcript or "").strip()
    if not transcript or "SIN_CONTENIDO_INFORMATIVO" in transcript.upper():
        return "skipped: sin contenido informativo"

    title_raw = call_llm_text(rag_client, TITLE_PROMPT_TEMPLATE.format(transcript=transcript[:4000]))
    title = sanitize_filename(str(title_raw).strip()) or f"IG_{media_id}"

    lang = detect_language(transcript)

    chunks = [transcript[i:i + MAX_CHARS_PER_CHUNK] for i in range(0, len(transcript), MAX_CHARS_PER_CHUNK)] or [transcript]

    all_facts = []
    for chunk in chunks:
        res = phase1_extract(rag_client, chunk, title)
        if hasattr(res, "facts"):
            all_facts.extend(res.facts)
        elif isinstance(res, dict) and "facts" in res:
            all_facts.extend([Fact(**f) for f in res["facts"]])

    if len(chunks) > 1:
        all_facts = phase2_deduplicate(rag_client, all_facts)

    document = phase3_synthesize(rag_client, all_facts, title, channel="Instagram", duration=0, lang=lang)
    final_doc = phase4_validate(rag_client, document, transcript)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, f"{title}.md"), "w", encoding="utf-8") as f:
        f.write(final_doc)
    with open(os.path.join(OUTPUT_DIR, f"{title}_transcript.txt"), "w", encoding="utf-8") as f:
        f.write(transcript)

    return f"done: {title}"


def call_llm_text(client, prompt: str) -> str:
    """main.py's call_llm sin response_schema devuelve directo el texto."""
    from main import call_llm
    return call_llm(client, prompt)


def main():
    gemini_api_key = _get_gemini_key()
    os.environ["GEMINI_API_KEY"] = gemini_api_key  # main.py's create_client() lo lee de acá (forzar, no setdefault: puede haber una var de entorno vieja del sistema)

    print("Conectando con Instagram...")
    user_cl = get_client_for_user(IG_USERNAME)

    print("Sincronizando carpeta 'ia'...")
    sync_result = sync_collection_posts(COLLECTION_ID, user_cl, collection_name="ia", force=True, amount=250)
    print("  ->", sync_result)

    posts = get_posts_for_collection(COLLECTION_ID)
    vistos = load_vistos()
    pending = [p for p in posts if p["media_id"] not in vistos]

    print(f"Total en la carpeta: {len(posts)} | Ya procesados: {len(vistos)} | Pendientes: {len(pending)}")
    if not pending:
        print("Nada pendiente. Listo.")
        return

    rag_client = create_client()

    done, skipped, failed = 0, 0, 0
    t0 = time.time()

    for i, post in enumerate(pending, 1):
        media_id = post["media_id"]
        print(f"\n[{i}/{len(pending)}] media_id={media_id}")
        try:
            result = process_post(rag_client, post, gemini_api_key)
            print("  ->", result)
            if result.startswith("done"):
                done += 1
            else:
                skipped += 1
        except Exception as e:
            failed += 1
            print(f"  -> ERROR: {e}")
        finally:
            # Se marca como visto en TODOS los casos (incluso error) para no
            # trabarse reintentando siempre el mismo post problemático. Si
            # querés reintentar los que fallaron, borralos de vistos_ig.json.
            vistos.add(media_id)
            save_vistos(vistos)

    elapsed = time.time() - t0
    print(f"\n{'=' * 60}")
    print(f"Terminado. Completados: {done} | Saltados: {skipped} | Fallidos: {failed}")
    print(f"Tiempo total: {elapsed / 60:.1f} min")
    total_tokens = token_usage["input"] + token_usage["output"]
    print(f"Tokens usados (pipeline 4 fases): {total_tokens:,} ({token_usage['calls']} llamadas)")
    print(f"Resultados en: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
