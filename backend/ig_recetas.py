import os
import re
import json
import time
import tempfile
import threading
import requests as req_lib
from fastapi import FastAPI, HTTPException, BackgroundTasks, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Dict, Literal
from instagrapi.exceptions import LoginRequired, ChallengeRequired

from ig_auth import get_client_for_user
from ig_media import resolve_media, download_media, download_bytes, MediaResolutionError, MediaDownloadError

# LangChain pipeline (import opcional — solo falla si no está instalado)
try:
    from langchain_pipeline import run_recipe_pipeline, get_recipe, load_recipes_db
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False

SESSION_FILE = "ig_session.json"
app = FastAPI(title="Backend para Recetas de IG")

# ─── CORS ─────────────────────────────────────────────────────────────────────
# Permite que el frontend (AI Studio, ngrok, localhost) llame al servidor
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # Acepta cualquier origen
    allow_credentials=True,
    allow_methods=["*"],        # GET, POST, OPTIONS, etc.
    allow_headers=["*"],        # X-IG-Username, X-IG-Password, ngrok-skip-browser-warning, etc.
)
# ──────────────────────────────────────────────────────────────────────────────

# Montar carpeta estática
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Jobs store
JOBS = {}
JOBS_FILE = "ig_jobs.json"
gemini_lock = threading.Lock()

def load_jobs():
    global JOBS
    if os.path.exists(JOBS_FILE):
        try:
            with open(JOBS_FILE, "r") as f:
                JOBS = json.load(f)
            # Limpiar trabajos huérfanos que quedaron en 'processing' o 'pending' tras reinicio
            modified = False
            for jid, job in JOBS.items():
                if job.get("status") in ["processing", "pending"]:
                    job["status"] = "failed"
                    job["error"] = "Trabajo interrumpido por reinicio del servidor."
                    modified = True
            if modified:
                save_jobs()
        except Exception:
            JOBS = {}

def save_jobs():
    try:
        with open(JOBS_FILE, "w") as f:
            json.dump(JOBS, f)
    except Exception:
        pass

def _gemini_post(url, payload, timeout=60, max_retries=4):
    """POST a Gemini con retry automático en 429 y lock de concurrencia."""
    with gemini_lock:
        wait = 15
        for attempt in range(max_retries):
            resp = req_lib.post(url, json=payload, timeout=timeout)
            if resp.status_code == 429:
                time.sleep(wait)
                wait *= 2
                continue
            resp.raise_for_status()
            # Espera de cortesía para respetar el Rate Limit (RPM)
            time.sleep(3)
            return resp
        resp.raise_for_status()
        return resp
# No global client - instantiated dynamically per user

RECIPE_KEYWORDS = [
    "ingredientes", "ingredients", "receta", "recipe", "taza", "cup", "tbsp",
    "tsp", "cucharada", "cucharadita", "gramos", "grams", "oz", "lb",
    "horno", "oven", "mezcla", "mix", "bake", "hornea", "fríe", "fry",
    "hervir", "boil", "picar", "chop", "sal", "salt", "aceite", "oil",
]

def extract_media(item: dict) -> dict:
    media = item.get("media", item)
    video_url = None
    if media.get("video_versions"):
        video_url = media["video_versions"][0].get("url")
    thumb_url = None
    if media.get("image_versions2", {}).get("candidates"):
        thumb_url = media["image_versions2"]["candidates"][0].get("url")
    caption = media.get("caption", {}).get("text", "") if media.get("caption") else ""
    caption_lower = caption.lower()
    has_recipe_caption = any(kw in caption_lower for kw in RECIPE_KEYWORDS)

    return {
        "media_id": str(media.get("id", "")),
        "url": video_url or thumb_url or "",
        "caption": caption,
        "media_type": "video" if video_url else "image",
        "taken_at": media.get("taken_at"),
        "has_recipe_caption": has_recipe_caption,
        "workflow": "A_caption" if has_recipe_caption else "B_whisper",
    }


@app.on_event("startup")
def startup():
    load_jobs()
    # Intentar cargar el cliente por defecto si existen variables de entorno
    try:
        get_client_for_user()
    except Exception:
        pass


@app.post("/login")
def login_endpoint(
    x_ig_username: str = Header(None),
    x_ig_password: str = Header(None)
):
    if x_ig_username == "test" and x_ig_password == "test":
        return {"status": "success", "message": "Sesión iniciada correctamente para test"}
        
    user_cl = get_client_for_user(x_ig_username, x_ig_password)
    return {"status": "success", "message": f"Sesión iniciada correctamente para {x_ig_username or os.environ.get('IG_USERNAME')}"}


@app.get("/collections")
def list_collections(
    x_ig_username: str = Header(None),
    x_ig_password: str = Header(None)
):
    if x_ig_username == "test":
        return {"total": 1, "collections": [{"collection_id": "test_folder", "name": "recetas saludables", "media_count": 10}]}

    from ig_collections import list_collections_live
    user_cl = get_client_for_user(x_ig_username, x_ig_password)
    try:
        collections = list_collections_live(user_cl)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo carpetas de Instagram: {str(e)}")

    return {"total": len(collections), "collections": collections}


STATE_FILE = "ig_state.json"

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def _get_analyzed_media_ids() -> set:
    try:
        from database import SessionLocal
        from models import Recipe
        db = SessionLocal()
        ids = {r.media_id for r in db.query(Recipe).all()}
        db.close()
        return ids
    except Exception as e:
        print(f"Error reading SQLite: {e}")
        return set()


@app.get("/collection-posts")
def get_collection_posts(
    collection_id: str,
    batch_size: int = 20,
    cursor: str = None,
    since: int = None,
    force_sync: bool = False,
    x_ig_username: str = Header(None),
    x_ig_password: str = Header(None)
):
    from ig_collections import sync_collection_posts, get_posts_for_collection

    if collection_id != "test_folder":
        user_cl = get_client_for_user(x_ig_username, x_ig_password)
        try:
            sync_collection_posts(collection_id, user_cl, force=force_sync)
        except Exception as e:
            print(f"[collection-posts] Aviso: no se pudo sincronizar con Instagram ({e}). Usando lo que haya en cache local.")

    all_posts = get_posts_for_collection(collection_id)
    analyzed_ids = _get_analyzed_media_ids()

    unanalyzed = [p for p in all_posts if p.get("media_id") not in analyzed_ids]
    posts_to_return = unanalyzed[:batch_size]

    return {
        "batch_total": len(posts_to_return),
        "workflow_a_count": len(posts_to_return),
        "workflow_b_count": 0,
        "next_cursor": None,
        "has_more": len(unanalyzed) > len(posts_to_return),
        "posts": posts_to_return
    }


@app.get("/collection-posts/all")
def get_all_collection_posts(
    collection_id: str,
    since: int = 0,
    force_sync: bool = False,
    x_ig_username: str = Header(None),
    x_ig_password: str = Header(None)
):
    from ig_collections import sync_collection_posts, get_posts_for_collection

    if collection_id != "test_folder":
        user_cl = get_client_for_user(x_ig_username, x_ig_password)
        try:
            sync_collection_posts(collection_id, user_cl, force=force_sync)
        except Exception as e:
            print(f"[collection-posts/all] Aviso: no se pudo sincronizar con Instagram ({e}). Usando lo que haya en cache local.")

    all_posts = get_posts_for_collection(collection_id)

    # El usuario pidió ver TODAS y mostrar el estado "Saved" en el UI.
    return {
        "total": len(all_posts),
        "workflow_a_count": len(all_posts),
        "workflow_b_count": 0,
        "posts": all_posts,
    }


@app.get("/collection-posts/state/{collection_id}")
def get_collection_state(collection_id: str):
    """Devuelve el último timestamp procesado para esta colección."""
    state = load_state()
    return {"last_processed_at": state.get(collection_id)}


@app.post("/collection-posts/state/{collection_id}")
def update_collection_state(collection_id: str, last_processed_at: int):
    """Guarda el timestamp del post más reciente procesado."""
    state = load_state()
    state[collection_id] = last_processed_at
    save_state(state)
    return {"saved": True, "last_processed_at": last_processed_at}


@app.get("/saved-posts")
def get_saved_posts(
    limit: int = 20,
    x_ig_username: str = Header(None),
    x_ig_password: str = Header(None)
):
    """Devuelve todos los posts guardados (sin filtrar por colección)."""
    user_cl = get_client_for_user(x_ig_username, x_ig_password)
    try:
        results = []
        next_max_id = None

        while len(results) < limit:
            params = {"include_igtv_preview": "false"}
            if next_max_id:
                params["max_id"] = next_max_id

            data = user_cl.private_request("feed/saved/posts/", params=params)
            items = data.get("items", [])

            for item in items:
                results.append(extract_media(item))
                if len(results) >= limit:
                    break

            next_max_id = data.get("next_max_id")
            if not next_max_id or not items:
                break

    except (LoginRequired, ChallengeRequired) as e:
        raise HTTPException(status_code=401, detail=f"Autenticación requerida: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"total": len(results), "posts": results}


class AnalyzeVideoRequest(BaseModel):
    media_id: str
    video_url: str
    gemini_api_key: str

class AnalyzeMediaRequest(BaseModel):
    media_id: str
    gemini_api_key: str

@app.get("/analyze-direct")
def analyze_direct(media_id: str, video_url: str, gemini_api_key: str):
    """
    Recibe media_id y video_url (URL-encoded por n8n) como query params.
    """
    return _do_analyze(media_id, video_url, gemini_api_key)

@app.get("/analyze-media")
def analyze_media(
    media_id: str, 
    gemini_api_key: str,
    x_ig_username: str = Header(None),
    x_ig_password: str = Header(None)
):
    """
    Recibe solo media_id como query param (sin caracteres especiales),
    obtiene la URL directamente desde Instagram (instagrapi),
    y analiza la imagen/video con Gemini.
    """
    try:
        resolved = resolve_media(media_id, x_ig_username, x_ig_password, allow_cache_fallback=False)
    except MediaResolutionError as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo media de Instagram: {str(e)}")

    return _do_analyze(media_id, resolved["url"], gemini_api_key)

@app.post("/analyze-video")
def analyze_video(body: AnalyzeVideoRequest):
    media_id = body.media_id
    video_url = body.video_url
    gemini_api_key = body.gemini_api_key
    return _do_analyze(media_id, video_url, gemini_api_key)

def _do_analyze(media_id: str, video_url: str, gemini_api_key: str):
    """
    Descarga el video de Instagram, lo sube a Gemini Files API,
    espera a que esté listo y llama a generateContent.
    Devuelve el JSON de la receta extraída.
    Si la URL es una imagen, la analiza directamente con Gemini vision.
    """
    GEMINI_KEY = gemini_api_key

    # Detectar si es imagen o video por la URL
    is_image = any(ext in video_url.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"])

    if is_image:
        # Para imágenes: usar URL directamente con Gemini (no necesita Files API)
        try:
            prompt = (
                "Eres un Agente Estructurador y Calculador de Datos Nutricionales. "
                "Analiza esta imagen de receta y extrae la información. "
                "Si el tiempo de preparación o las porciones no se mencionan, usa null. "
                "Calcula nutrición usando: 1g grasa=9kcal, 1g proteína=4kcal, 1g carbohidratos=4kcal, 1g fibra=2kcal. "
                "Valores nutricionales POR PORCIÓN. Estima si no se menciona. "
                "Responde ÚNICAMENTE con JSON válido sin markdown: "
                "{\"nombre\":\"\",\"tiempo_preparacion\":0,\"porciones\":0,"
                "\"ingredientes\":[{\"item\":\"\",\"cantidad\":0,\"unidad\":\"\"}],"
                "\"instrucciones\":[\"\"],"
                "\"nutricion\":{\"kcal\":0,\"proteina_g\":0,\"carbohidratos_g\":0,\"grasas_g\":0,\"azucares_g\":0,\"fibra_g\":0},"
                "\"origen_nutricional\":\"Calculado por IA\"} "
                "Si no es receta devuelve {\"nombre\":null}."
            )
            img_data = __import__('base64').b64encode(download_bytes(video_url)).decode()
            gen_resp = _gemini_post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}",
                {"contents": [{"parts": [
                    {"inline_data": {"mime_type": "image/jpeg", "data": img_data}},
                    {"text": prompt}
                ]}]}
            )
            raw_text = gen_resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            match = re.search(r'\{[\s\S]*\}', raw_text)
            recipe = json.loads(match.group(0)) if match else {"nombre": None}
            return {"media_id": media_id, "recipe": recipe}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error analizando imagen: {str(e)}")

    # 1. Descargar video temporalmente (con reintentos + fallback a yt-dlp si la URL directa falla/expiró)
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        download_media(video_url, tmp_path, media_id=media_id)
    except MediaDownloadError as e:
        raise HTTPException(status_code=500, detail=f"Error descargando video: {str(e)}")

    # 2. Subir a Gemini Files API
    try:
        upload_url = f"https://generativelanguage.googleapis.com/upload/v1beta/files?uploadType=multipart&key={GEMINI_KEY}"
        with open(tmp_path, "rb") as f:
            video_bytes = f.read()

        metadata = json.dumps({"file": {"display_name": media_id}}).encode()
        boundary = "bound_ig_receta"
        body = (
            f"--{boundary}\r\n"
            f"Content-Type: application/json\r\n\r\n"
        ).encode() + metadata + (
            f"\r\n--{boundary}\r\n"
            f"Content-Type: video/mp4\r\n\r\n"
        ).encode() + video_bytes + f"\r\n--{boundary}--\r\n".encode()

        upload_resp = req_lib.post(
            upload_url,
            headers={"Content-Type": f"multipart/related; boundary={boundary}"},
            data=body,
            timeout=120
        )
        upload_resp.raise_for_status()
        file_uri = upload_resp.json()["file"]["uri"]
        file_name = upload_resp.json()["file"]["name"]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error subiendo a Gemini: {str(e)}")

    # 3. Esperar a que Gemini procese el video (estado ACTIVE)
    for _ in range(12):
        time.sleep(5)
        try:
            status_resp = req_lib.get(
                f"https://generativelanguage.googleapis.com/v1beta/{file_name}?key={GEMINI_KEY}",
                timeout=30
            )
            if status_resp.ok and status_resp.json().get("state") == "ACTIVE":
                break
        except Exception:
            pass

    # 4. Llamar a generateContent
    try:
        prompt = (
            "<system_prompt>\n"
            "<role_and_tone>\n"
            "Asume el rol de un Agente Estructurador y Calculador de Datos Nutricionales. Tu tono es estrictamente técnico, matemático, objetivo y determinista.\n"
            "</role_and_tone>\n"
            "<task_definition>\n"
            "Analiza el video para extraer entidades culinarias específicas (nombre, ingredientes, tiempo, porciones, instrucciones). También, identifica en qué segundo (timestamp en formato decimal, ej 3.5) se ve el plato terminado en su mejor presentación para usarlo como foto principal. "
            "Si el video contiene el desglose de macronutrientes, extráelo. Si carece de valores nutricionales, calcúlalos algorítmicamente basándote en los ingredientes, sus cantidades estimadas en gramos y las constantes calóricas proporcionadas.\n"
            "</task_definition>\n"
            "<rules_and_guardrails>\n"
            "1. Extrae los pasos de la receta de forma secuencial y cronológica.\n"
            "2. Si el tiempo de preparación o las porciones no se mencionan explícitamente, usa null o 0.\n"
            "3. Transforma todas las medidas de volumen (tazas, cucharadas) a estimaciones en gramos (g) o mililitros (ml) antes de realizar cálculos nutricionales.\n"
            "4. Calcula las calorías totales sumando los aportes individuales de cada macronutriente.\n"
            "5. Los valores nutricionales deben ser POR PORCIÓN.\n"
            "</rules_and_guardrails>\n"
            "<calculation_constants>\n"
            "Aplica estrictamente las siguientes equivalencias bioquímicas para el cálculo de macronutrientes cuando los datos falten:\n"
            "- 1 gramo de Grasa = 9 kcal\n"
            "- 1 gramo de Proteína = 4 kcal\n"
            "- 1 gramo de Carbohidratos = 4 kcal\n"
            "- 1 gramo de Azúcar = 4 kcal (Subcategoría de carbohidratos)\n"
            "- 1 gramo de Fibra = 2 kcal\n"
            "</calculation_constants>\n"
            "<output_structure>\n"
            "Responde ÚNICAMENTE con un objeto JSON válido sin markdown, sin bloques de código (como ```json), sin texto adicional. "
            "El JSON debe seguir exactamente esta estructura:\n"
            "{\n"
            "  \"nombre\": \"Nombre de la receta o null si no es receta\",\n"
            "  \"tiempo_preparacion\": 0,\n"
            "  \"porciones\": 0,\n"
            "  \"ingredientes\": [{\"item\": \"nombre del ingrediente\", \"cantidad\": 0, \"unidad\": \"g/ml/unidad\"}],\n"
            "  \"instrucciones\": [\"Paso 1\", \"Paso 2\"],\n"
            "  \"nutricion\": {\n"
            "    \"kcal\": 0,\n"
            "    \"proteina_g\": 0,\n"
            "    \"carbohidratos_g\": 0,\n"
            "    \"grasas_g\": 0,\n"
            "    \"azucares_g\": 0,\n"
            "    \"fibra_g\": 0\n"
            "  },\n"
            "  \"origen_nutricional\": \"Extraído del video / Calculado por IA\"\n"
            "}\n"
            "Si el video no es una receta, devuelve únicamente {\"nombre\": null}.\n"
            "</output_structure>\n"
            "</system_prompt>"
        )
        gen_resp = _gemini_post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}",
            {
                "contents": [{
                    "parts": [
                        {"file_data": {"mime_type": "video/mp4", "file_uri": file_uri}},
                        {"text": prompt}
                    ]
                }]
            },
            timeout=60
        )
        raw_text = gen_resp.json()["candidates"][0]["content"]["parts"][0]["text"]

        # Parsear JSON de la respuesta
        match = re.search(r'\{[\s\S]*\}', raw_text)
        if match:
            recipe = json.loads(match.group(0))
        else:
            recipe = {"nombre": None, "raw": raw_text}

        
        # Extraer frame con OpenCV
        try:
            best_timestamp = float(recipe.get("best_frame_timestamp", 0.0))
            import cv2
            cap = cv2.VideoCapture(tmp_path)
            cap.set(cv2.CAP_PROP_POS_MSEC, best_timestamp * 1000)
            success, frame = cap.read()
            if success:
                import os
                os.makedirs("static/thumbnails", exist_ok=True)
                cv2.imwrite(f"static/thumbnails/{media_id}.png", frame)
            cap.release()
        except Exception as cv_err:
            print(f"Error extracting frame with cv2: {cv_err}")

        return {"media_id": media_id, "recipe": recipe}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en generateContent: {str(e)}")
    finally:
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except:
                pass


def run_async_analysis(media_id: str, video_url: str, gemini_api_key: str):
    JOBS[media_id]["status"] = "processing"
    JOBS[media_id]["updated_at"] = time.time()
    save_jobs()
    try:
        result = _do_analyze(media_id, video_url, gemini_api_key)
        JOBS[media_id]["status"] = "completed"
        JOBS[media_id]["result"] = result
        JOBS[media_id]["error"] = None
    except Exception as e:
        JOBS[media_id]["status"] = "failed"
        if hasattr(e, "detail"):
            JOBS[media_id]["error"] = str(e.detail)
        else:
            JOBS[media_id]["error"] = str(e)
    JOBS[media_id]["updated_at"] = time.time()
    save_jobs()


@app.post("/analyze-async")
@app.get("/analyze-async")
def analyze_async(media_id: str, video_url: str, gemini_api_key: str, background_tasks: BackgroundTasks):
    """
    Inicia el procesamiento asíncrono de un post (imagen o video) y retorna inmediatamente.
    """
    # Si ya existe y está completado, lo retornamos directo
    if media_id in JOBS and JOBS[media_id]["status"] == "completed":
        return {"media_id": media_id, "status": "completed", "result": JOBS[media_id]["result"]}
    
    # Si está en progreso, retornamos el estado actual
    if media_id in JOBS and JOBS[media_id]["status"] in ["pending", "processing"]:
        return {"media_id": media_id, "status": JOBS[media_id]["status"]}
        
    JOBS[media_id] = {
        "status": "pending",
        "result": None,
        "error": None,
        "updated_at": time.time()
    }
    save_jobs()
    background_tasks.add_task(run_async_analysis, media_id, video_url, gemini_api_key)
    return {"media_id": media_id, "status": "pending"}


@app.get("/analyze-status/{media_id}")
def analyze_status(media_id: str):
    """
    Retorna el estado de un trabajo de análisis por media_id.
    """
    if media_id not in JOBS:
        return {"media_id": media_id, "status": "not_found"}
    return {
        "media_id": media_id,
        "status": JOBS[media_id]["status"],
        "result": JOBS[media_id].get("result"),
        "error": JOBS[media_id].get("error"),
    }


@app.get("/jobs")
def list_jobs():
    """
    Lista todos los trabajos registrados.
    """
    return JOBS


@app.post("/jobs/clear")
def clear_jobs():
    """
    Limpia todos los trabajos en memoria y disco.
    """
    global JOBS
    JOBS = {}
    save_jobs()
    return {"cleared": True}


# ─────────────────────────────────────────────────────────────────────────────
# LANGCHAIN ENDPOINTS
# Nuevos endpoints que usan el pipeline de LangChain para procesar recetas
# ─────────────────────────────────────────────────────────────────────────────

class LangchainAnalyzeRequest(BaseModel):
    media_id: str
    video_url: str
    gemini_api_key: str
    target_servings: int = 0  # 0 = usar porciones originales de la receta


@app.post("/analyze-langchain")
def analyze_langchain(body: LangchainAnalyzeRequest):
    """
    Procesa un video o imagen de receta usando el pipeline de LangChain (3 pasos):
    1. Gemini extrae texto crudo del video/imagen
    2. LLM estructura la receta (ingredientes, instrucciones, porciones)
    3. LLM calcula nutrición y ajusta cantidades según target_servings

    El resultado se guarda automáticamente en recetas_db.json con media_id como key.

    Body:
        media_id (str): ID único del post (clave en el diccionario de recetas)
        video_url (str): URL directa del video o imagen de Instagram
        gemini_api_key (str): API Key de Google Gemini
        target_servings (int): Para cuántas personas ajustar las cantidades (0 = original)
    """
    if not LANGCHAIN_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="LangChain no está instalado. Ejecuta: pip install -r requirements_langchain.txt"
        )
    # Validar que video_url no esté vacía
    if not body.video_url or not body.video_url.startswith("http"):
        raise HTTPException(
            status_code=400,
            detail="video_url está vacía o es inválida. Usa /analyze-langchain-by-id si solo tienes el media_id."
        )
    try:
        result = run_recipe_pipeline(
            media_id=body.media_id,
            video_url=body.video_url,
            gemini_api_key=body.gemini_api_key,
            target_servings=body.target_servings,
            save_to_db=True,
        )
        return {"status": "success", "recipe": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en pipeline LangChain: {str(e)}")


class LangchainAnalyzeByIdRequest(BaseModel):
    media_id: str
    gemini_api_key: str = None
    target_servings: int = 0
    x_ig_username: str = None
    x_ig_password: str = None


@app.post("/analyze-langchain-by-id")
def analyze_langchain_by_id(body: LangchainAnalyzeByIdRequest):
    """
    Versión robusta de /analyze-langchain que solo necesita media_id.
    Obtiene la URL del video/imagen directamente desde Instagram en vivo
    (vía instagrapi, reutilizando la sesión persistente). Si Instagram no
    está disponible (sin sesión, rate limit, etc.) cae al backup local
    como último recurso — nunca a un post equivocado.

    Útil cuando post.url viene vacío desde /collection-posts, o cuando la
    URL que tenía el frontend ya expiró (las URLs de IG son firmadas y de
    corta duración).

    Body:
        media_id (str): ID único del post de Instagram
        gemini_api_key (str): API Key de Google Gemini
        target_servings (int): Para cuántas personas ajustar (0 = original)
        x_ig_username (str): Usuario de Instagram (opcional si hay sesión)
        x_ig_password (str): Contraseña de Instagram (opcional si hay sesión)
    """
    if not LANGCHAIN_AVAILABLE:
        raise HTTPException(status_code=503, detail="LangChain no está instalado.")

    try:
        resolved = resolve_media(body.media_id, body.x_ig_username, body.x_ig_password)
    except MediaResolutionError as e:
        raise HTTPException(status_code=404, detail=str(e))

    video_url = resolved["url"]
    caption = resolved.get("caption", "")
    if not video_url:
        raise HTTPException(status_code=404, detail=f"No se pudo obtener una URL válida para media_id {body.media_id}")

    # Correr el pipeline con la URL resuelta
    try:
        from langchain_pipeline import run_recipe_pipeline
        result = run_recipe_pipeline(
            media_id=body.media_id,
            video_url=video_url,
            gemini_api_key=body.gemini_api_key,
            target_servings=body.target_servings,
            save_to_db=True,
            caption=caption,
        )
        return {"status": "success", "video_url_used": video_url, "url_source": resolved["source"], "recipe": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en pipeline LangChain: {str(e)}")


@app.get("/recipes")
def list_recipes():
    """
    Lista todas las recetas procesadas y guardadas en recetas_db.json.
    Devuelve un resumen con nombre, porciones y si tiene nutrición calculada.
    """
    if not LANGCHAIN_AVAILABLE:
        raise HTTPException(status_code=503, detail="LangChain no está instalado.")
    db = load_recipes_db()
    mapped_recipes = []
    for media_id, r in db.items():
        nutricion = r.get("nutricion_por_porcion", {})
        
        # Mapear ingredientes al formato del frontend {name, amount}
        ingredientes_raw = r.get("ingredientes_ajustados") or r.get("ingredientes", [])
        ingredientes_mapped = []
        for ing in ingredientes_raw:
            if isinstance(ing, dict):
                name = ing.get("nombre") or ing.get("ingrediente") or ing.get("item") or "Ingrediente"
                
                # Combine cantidad y unidad
                cantidad = str(ing.get("cantidad", "")) if ing.get("cantidad") is not None else ""
                unidad = str(ing.get("unidad", "")) if ing.get("unidad") is not None else ""
                amount_str = f"{cantidad} {unidad}".strip()
                
                ingredientes_mapped.append({
                    "name": name, 
                    "amount": amount_str
                })
            else:
                ingredientes_mapped.append({"name": str(ing), "amount": ""})
                
        # Evitar valores None en macros
        def clean_num(val):
            try:
                if val is None: return 0
                return int(float(val))
            except:
                return 0

        mapped_recipes.append({
            "id": media_id,
            "title": r.get("nombre", "Receta de Instagram"),
            "servings": clean_num(r.get("porciones_ajustadas") or r.get("porciones_originales") or 1),
            "macros": {
                "calories": clean_num(nutricion.get("calorias", nutricion.get("kcal", 0))),
                "protein": clean_num(nutricion.get("proteina_g", 0)),
                "carbs": clean_num(nutricion.get("carbohidratos_g", 0)),
                "fat": clean_num(nutricion.get("grasa_g", nutricion.get("grasas_g", 0))),
                "fiber": clean_num(nutricion.get("fibra_g", 0)),
                "sugar": clean_num(nutricion.get("azucares_g", 0))
            },
            "ingredients": ingredientes_mapped,
            "instructions": r.get("instrucciones", []),
            "categories": r.get("tags") or ["Instagram"],
            "thumbnail_url": r.get("thumbnail_url", "")
        })
    return {"total": len(mapped_recipes), "recipes": mapped_recipes}


@app.get("/recipes/{media_id}")
def get_recipe_by_id(media_id: str, target_servings: int = 0):
    """
    Obtiene una receta específica del diccionario local por su media_id.
    Si se pasa target_servings, ajusta las cantidades de ingredientes en tiempo real.

    Args:
        media_id: ID único del post de Instagram
        target_servings: Para cuántas personas escalar (0 = no ajustar, retorna original)
    """
    if not LANGCHAIN_AVAILABLE:
        raise HTTPException(status_code=503, detail="LangChain no está instalado.")
    recipe = get_recipe(media_id)
    if not recipe:
        raise HTTPException(status_code=404, detail=f"Receta {media_id} no encontrada en la base de datos.")

    # Ajuste de porciones en tiempo real si se solicita
    if target_servings and target_servings > 0:
        original_servings = recipe.get("porciones_originales", 1) or 1
        ratio = target_servings / original_servings
        original_ingredients = recipe.get("ingredientes", [])
        adjusted = [
            {**ing, "cantidad": round(ing["cantidad"] * ratio, 1)}
            for ing in original_ingredients
        ]
        recipe = {
            **recipe,
            "porciones_ajustadas": target_servings,
            "ingredientes_ajustados": adjusted,
        }

    return {"media_id": media_id, "recipe": recipe}


# ─────────────────────────────────────────────────────────────────────────────
# CLOUD SYNC ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

USERS_DB_DIR = "users_db"
os.makedirs(USERS_DB_DIR, exist_ok=True)

class SyncUserDataRequest(BaseModel):
    username: str
    profile: dict
    recipes: list

@app.post("/sync-user-data")
def sync_user_data(data: SyncUserDataRequest):
    """Guarda el perfil y las recetas de un usuario en su archivo JSON."""
    if not data.username:
        raise HTTPException(status_code=400, detail="username es requerido")
    
    file_path = os.path.join(USERS_DB_DIR, f"{data.username}.json")
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({"profile": data.profile, "recipes": data.recipes}, f, ensure_ascii=False, indent=2)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error guardando datos: {str(e)}")

@app.get("/get-user-data/{username}")
def get_user_data(username: str):
    """Obtiene el perfil y las recetas de un usuario."""
    file_path = os.path.join(USERS_DB_DIR, f"{username}.json")
    if not os.path.exists(file_path):
        # Si no existe, no es un error, simplemente retornamos null para indicar que es nuevo
        return {"status": "not_found", "data": None}
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {"status": "success", "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error leyendo datos: {str(e)}")



class MealPlanRequest(BaseModel):
    dailyGoals: dict
    meals: list
    restrictions: list = []
    cycle_phase: str = ""
    num_days: int = 1
    goal: Literal["lose", "maintain", "gain"] = "maintain"
    is_pregnant: bool = False
    avoid: List[str] = []   # no me gusta / alergias (filtro duro)
    likes: List[str] = []   # comidas favoritas (se priorizan)

@app.get("/api/recipes")
def get_all_recipes():
    from database import SessionLocal
    from diet import diet_labels
    from models import Recipe
    db = SessionLocal()
    recipes = db.query(Recipe).all()
    result = []
    for r in recipes:
        ing_raw = []
        if r.ingredients_raw:
            try:
                ing_raw = json.loads(r.ingredients_raw)
            except:
                pass
                
        ing_mapped = []
        for ing in ing_raw:
            if isinstance(ing, dict):
                name = ing.get("nombre") or ing.get("ingrediente") or ing.get("item") or "Ingrediente"
                cantidad = str(ing.get("cantidad", "")) if ing.get("cantidad") is not None else ""
                unidad = str(ing.get("unidad", "")) if ing.get("unidad") is not None else ""
                ing_mapped.append({"name": name, "amount": f"{cantidad} {unidad}".strip()})
            else:
                ing_mapped.append({"name": str(ing), "amount": ""})
                
        instructions = []
        if r.instructions:
            try:
                instructions = json.loads(r.instructions)
            except:
                pass

        result.append({
            "id": r.id,
            "media_id": r.media_id,
            "title": r.nombre,
            "video_url": r.video_url,
            "thumbnail_url": r.thumbnail_url,
            "servings": r.servings,
            "cuisine": r.cuisine_type,
            "categories": r.tags.split(",") if r.tags else [],
            "instructions": instructions,
            "ingredients": ing_mapped,
            "macros": {
                "calories": r.nutrition.calories if r.nutrition else 0,
                "protein": r.nutrition.proteins if r.nutrition else 0,
                "carbs": r.nutrition.carbohydrates if r.nutrition else 0,
                "fat": r.nutrition.fats if r.nutrition else 0,
                "fiber": (r.nutrition.fiber or 0) if r.nutrition else 0,
                "sugar": (r.nutrition.sugars or 0) if r.nutrition else 0,
            },
            # Dietas que cumple (diet.py); el Cookbook filtra con esto según el perfil.
            "diet": diet_labels(
                r.tags.split(",") if r.tags else [],
                [i.get("nombre") or i.get("ingrediente") or "" for i in ing_raw if isinstance(i, dict)],
                r.nutrition.sugars if r.nutrition else None,
            ),
        })
    db.close()
    return result

class RecipeSearchRequest(BaseModel):
    q: str

@app.post("/api/recipes/search")
def search_recipes(req: RecipeSearchRequest):
    """
    Búsqueda en lenguaje natural (ver recipe_search.py): el LLM la convierte en
    filtros y Chroma ordena por similitud. Devuelve ids de SQLite en orden de
    relevancia y los filtros que entendió, para mostrarlos en el Cookbook.
    """
    from database import SessionLocal
    from models import Recipe
    from recipe_search import search

    q = req.q.strip()
    if not q:
        raise HTTPException(status_code=400, detail="La búsqueda está vacía.")
    if len(q) > 200:
        raise HTTPException(status_code=400, detail="La búsqueda es muy larga (máx. 200 caracteres).")
    try:
        result = search(q.lower())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"No se pudo buscar: {e}")

    db = SessionLocal()
    try:
        id_by_media = dict(db.query(Recipe.media_id, Recipe.id).all())
    finally:
        db.close()
    ids = [str(id_by_media[m]) for m in result["media_ids"] if m in id_by_media]
    return {"ids": list(dict.fromkeys(ids)), "filters": result["filters"]}

class IntakeScoreRequest(BaseModel):
    totals: Dict[str, float]   # calorias, proteinas, carbohidratos, grasas, fibra, azucar
    targets: Dict[str, float]  # las metas del día tal como vienen en el plan
    goal: Literal["lose", "maintain", "gain"] = "maintain"
    is_pregnant: bool = False

@app.post("/api/intake-score")
def score_intake(body: IntakeScoreRequest):
    """Puntaje real de lo comido, con la misma fórmula que el puntaje planeado del plan."""
    from rag_planner import intake_score
    return intake_score(body.totals, body.targets, goal=body.goal, is_pregnant=body.is_pregnant)

@app.post("/api/mealplan/generate")
def generate_mealplan(request: MealPlanRequest):
    from database import SessionLocal
    from rag_planner import RAGMealPlanner
    db = SessionLocal()
    planner = RAGMealPlanner(db)
    
    targets = {
        "calorias": request.dailyGoals.get("calories", 2000),
        "proteinas": request.dailyGoals.get("protein", 150),
        "carbohidratos": request.dailyGoals.get("carbs", 200),
        "grasas": request.dailyGoals.get("fat", 60),
        "azucares": request.dailyGoals.get("sugar"),
        "fibra": request.dailyGoals.get("fiber"),
    }
    
    structure = [m.lower() for m in request.meals]
    num_days = max(1, min(14, request.num_days))

    try:
        result = planner.generate(
            meal_structure=structure,
            target_macros=targets,
            restrictions=request.restrictions,
            cycle_phase=request.cycle_phase,
            num_days=num_days,
            profile={"goal": request.goal, "is_pregnant": request.is_pregnant,
                     "avoid": request.avoid, "likes": request.likes},
        )
    except Exception as e:
        db.close()
        raise HTTPException(status_code=400, detail=str(e))
        
    db.close()
    return result


class MealPrepRequest(BaseModel):
    sessions: list

@app.post("/api/mealprep/generate")
def generate_mealprep(request: MealPrepRequest):
    from mealprep_planner import MealPrepPlanner
    planner = MealPrepPlanner()

    try:
        result = planner.generate(request.sessions)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result


# --- PANTRY & GROCERY LIST ENDPOINTS ---

class PantryItemCreate(BaseModel):
    name: str
    amount: str = None

@app.get("/api/pantry")
def get_pantry():
    from database import SessionLocal
    from models import PantryItem
    db = SessionLocal()
    items = db.query(PantryItem).all()
    result = [{"id": i.id, "name": i.name, "amount": i.amount} for i in items]
    db.close()
    return result

@app.post("/api/pantry")
def add_pantry_item(item: PantryItemCreate):
    """
    Si ya existe un item con el mismo nombre (ej. al tildar un item de la
    grocery list dos semanas seguidas), suma la cantidad en vez de crear una
    fila duplicada - pero solo cuando ambas cantidades tienen la misma
    unidad; si no, no adivinamos la suma y se guarda como fila aparte.
    """
    from database import SessionLocal
    from models import PantryItem
    from ingredient_normalizer import parse_amount_str, normalize_ingredient_name
    from shopping_list import to_canonical, parse_free_text

    name_clean = item.name.strip()
    amount = (item.amount or "").strip()
    if not amount:
        # Input manual en una sola línea: "1lb de arroz" -> ("arroz", "1 lb")
        name_clean, amount = parse_free_text(name_clean)
    item.amount = amount or None
    if not name_clean:
        raise HTTPException(status_code=400, detail="El nombre no puede estar vacío")

    db = SessionLocal()
    try:
        # "Huevos" y "huevo" son el mismo item; el pantry es chico, se recorre entero.
        norm = normalize_ingredient_name(name_clean) or name_clean.lower()
        existing = next((p for p in db.query(PantryItem).all()
                         if (normalize_ingredient_name(p.name) or p.name.lower()) == norm), None)

        if existing:
            new_qty, new_unit = to_canonical(*parse_amount_str(str(item.amount or "")))
            old_qty, old_unit = to_canonical(*parse_amount_str(str(existing.amount or "")))
            if new_qty and old_qty and new_unit == old_unit:
                total = old_qty + new_qty
                existing.amount = f"{total:g} {new_unit}".strip()
                db.commit()
                db.refresh(existing)
                return {"id": existing.id, "name": existing.name, "amount": existing.amount}

        new_item = PantryItem(name=name_clean, amount=item.amount)
        db.add(new_item)
        db.commit()
        db.refresh(new_item)
        return {"id": new_item.id, "name": new_item.name, "amount": new_item.amount}
    finally:
        db.close()

class PantryRemoveByName(BaseModel):
    name: str

@app.post("/api/pantry/remove")
def remove_pantry_ingredient(item: PantryRemoveByName):
    """
    Al desmarcar un item de la grocery list ("no lo tengo"): borra ese
    ingrediente del pantry, con el mismo matching de nombre que usa la lista
    ("Huevos" == "huevo"). Restar solo lo necesario dejaría el item cubierto
    si había stock de sobra, y el check volvería a marcarse solo.
    """
    from database import SessionLocal
    from models import PantryItem
    from ingredient_normalizer import normalize_ingredient_name

    name_clean = item.name.strip()
    if not name_clean:
        raise HTTPException(status_code=400, detail="El nombre no puede estar vacío")

    db = SessionLocal()
    try:
        norm = normalize_ingredient_name(name_clean) or name_clean.lower()
        for p in db.query(PantryItem).all():
            if (normalize_ingredient_name(p.name) or p.name.lower()) == norm:
                db.delete(p)
        db.commit()
        return {"status": "ok"}
    finally:
        db.close()

class ReceiptScanRequest(BaseModel):
    image: str  # data URL: "data:image/jpeg;base64,..."

class ReceiptItem(BaseModel):
    name: str
    amount: str = ""

class ReceiptItems(BaseModel):
    items: List[ReceiptItem]

RECEIPT_PROMPT = (
    "Eres un asistente que lee recibos de supermercado. Extrae SOLO alimentos e "
    "ingredientes (ignora bolsas, productos de limpieza, impuestos, descuentos y totales).\n"
    "- name: nombre genérico en español, en singular y minúsculas, SIN marca, sabor "
    "comercial ni tamaño (ej. 'ARROZ DIANA 1KG' -> 'arroz', 'LECHE ALQUERIA ENT' -> 'leche').\n"
    "- amount: cantidad TOTAL comprada con unidad (g, kg, ml, l, lb, oz o sin unidad para "
    "piezas). Multiplica unidades x tamaño del paquete (2 x arroz 1kg -> '2 kg'). Si el "
    "recibo no indica el tamaño, usa solo el número de unidades (ej. '1').\n"
    "- Si el mismo alimento aparece varias veces, únelo en una sola entrada.\n"
    "Si la imagen no es un recibo, devuelve items vacío."
)

@app.post("/api/pantry/receipt")
def scan_receipt(req: ReceiptScanRequest):
    """
    Lee una foto de un recibo con Gemini y devuelve los alimentos con nombre
    genérico (sin marca). NO guarda nada: el frontend muestra la lista para que
    el usuario la revise/edite y luego agrega cada item con POST /api/pantry.
    """
    from rag_chatbot import get_llm
    from langchain_core.messages import HumanMessage

    m = re.match(r"^data:(image/(?:jpeg|png|webp|heic|heif));base64,", req.image)
    if not m:
        raise HTTPException(status_code=400, detail="Sube una imagen JPG, PNG, WEBP o HEIC del recibo.")
    if len(req.image) > 14_000_000:  # ~10 MB de imagen en base64
        raise HTTPException(status_code=413, detail="La imagen es muy grande (máx. 10 MB).")

    llm = get_llm()
    if not llm:
        raise HTTPException(status_code=500, detail="El LLM no está configurado (falta GEMINI_API_KEY).")

    try:
        result = llm.with_structured_output(ReceiptItems).invoke([HumanMessage(content=[
            {"type": "text", "text": RECEIPT_PROMPT},
            {"type": "image_url", "image_url": req.image},
        ])])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"No se pudo leer el recibo: {e}")

    items = [{"name": i.name.strip(), "amount": i.amount.strip()}
             for i in (result.items if result else []) if i.name.strip()]
    return {"items": items}

@app.delete("/api/pantry/{item_id}")
def delete_pantry_item(item_id: int):
    from database import SessionLocal
    from models import PantryItem
    db = SessionLocal()
    item = db.query(PantryItem).filter(PantryItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
    db.close()
    return {"status": "ok"}

class GroceryPlanRequest(BaseModel):
    meals: List[Dict]

@app.post("/api/grocery/generate")
def generate_grocery_list(req: GroceryPlanRequest):
    """
    Genera la lista de compras de forma determinística (sin LLM):
    1. Suma los ingredientes de TODAS las recetas del plan (día o semana).
    2. Resta lo que ya hay en el Pantry.
    3. Devuelve solo lo que falta, con la cantidad faltante exacta.
    """
    from database import SessionLocal
    from models import PantryItem
    from shopping_list import generate_shopping_list

    db = SessionLocal()
    try:
        pantry_items = db.query(PantryItem).all()
        grocery_list = generate_shopping_list(req.meals, pantry_items)
        return {"grocery_list": grocery_list}
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# PROCESAMIENTO AUTOMÁTICO EN LOTE DE UNA CARPETA (flujo: conectar → carpeta →
# video por video → download_media → JSON → LLM completa nutrición → Cookbook)
# ─────────────────────────────────────────────────────────────────────────────

BATCH_JOBS: Dict[str, Dict] = {}


def run_collection_batch(batch_id: str, posts: list, gemini_api_key: str):
    from langchain_pipeline import run_recipe_pipeline

    job = BATCH_JOBS[batch_id]
    job["status"] = "processing"

    for post in posts:
        media_id = post["media_id"]
        entry = {"media_id": media_id, "nombre": None, "status": "processing", "error": None}
        job["items"][media_id] = entry
        try:
            final_recipe = run_recipe_pipeline(
                media_id=media_id,
                video_url=post.get("video_url") or post.get("url"),
                gemini_api_key=gemini_api_key,
                target_servings=0,
                save_to_db=True,  # guarda en recetas_db.json Y en SQLite (Cookbook)
                caption=post.get("caption", ""),
            )
            if final_recipe.get("is_recipe"):
                entry["status"] = "done"
                entry["nombre"] = final_recipe.get("nombre")
                job["completed"] += 1
            else:
                entry["status"] = "skipped"
                entry["error"] = "El contenido no parece ser una receta."
                job["skipped"] += 1
        except Exception as e:
            entry["status"] = "failed"
            entry["error"] = str(e)
            job["failed"] += 1

        job["processed"] += 1

    job["status"] = "completed"


@app.post("/api/collections/{collection_id}/process")
def process_collection(
    collection_id: str,
    gemini_api_key: str,
    background_tasks: BackgroundTasks,
    force_sync: bool = False,
    sync_amount: int = 50,
    x_ig_username: str = Header(None),
    x_ig_password: str = Header(None),
):
    """
    Sincroniza la carpeta (respetando el TTL, salvo force_sync=true) y arranca
    a procesar en segundo plano, video por video, todos los posts que todavía
    no estén en el Cookbook. Devuelve un batch_id para consultar el progreso
    en GET /api/collections/batch-status/{batch_id}.

    sync_amount: cuántos posts pedirle a Instagram en esta sincronización
    (default 50). Subilo si la carpeta tiene más posts nuevos que eso.
    """
    if not LANGCHAIN_AVAILABLE:
        raise HTTPException(status_code=503, detail="LangChain no está instalado.")

    import uuid
    from ig_collections import sync_collection_posts, get_posts_for_collection

    user_cl = get_client_for_user(x_ig_username, x_ig_password)
    try:
        sync_collection_posts(collection_id, user_cl, force=force_sync, amount=sync_amount)
    except Exception as e:
        print(f"[process_collection] Aviso: sync con Instagram falló ({e}). Se sigue con lo que haya en cache.")

    posts = get_posts_for_collection(collection_id)
    analyzed_ids = _get_analyzed_media_ids()
    pending = [p for p in posts if p["media_id"] not in analyzed_ids]

    batch_id = str(uuid.uuid4())
    BATCH_JOBS[batch_id] = {
        "collection_id": collection_id,
        "status": "pending",
        "total": len(pending),
        "processed": 0,
        "completed": 0,
        "failed": 0,
        "skipped": 0,
        "items": {},
    }

    if pending:
        background_tasks.add_task(run_collection_batch, batch_id, pending, gemini_api_key)
    else:
        BATCH_JOBS[batch_id]["status"] = "completed"

    return {"batch_id": batch_id, "total": len(pending)}


@app.get("/api/collections/batch-status/{batch_id}")
def get_batch_status(batch_id: str):
    job = BATCH_JOBS.get(batch_id)
    if not job:
        raise HTTPException(status_code=404, detail="Batch no encontrado")
    return job


# ─────────────────────────────────────────────────────────────────────────────
# IMPORTAR RECETAS DE TIKTOK
# TikTok no tiene (a diferencia de Instagram) una forma viable de sincronizar
# una carpeta/colección privada en vivo - ver discusión con el usuario. La vía
# práctica: el usuario pega la URL de un video puntual y se reusa el mismo
# pipeline de LangChain que ya procesa recetas de Instagram.
# ─────────────────────────────────────────────────────────────────────────────

class TikTokImportRequest(BaseModel):
    url: str
    gemini_api_key: str = None
    target_servings: int = 0


@app.post("/api/tiktok/import")
def import_tiktok_recipe(body: TikTokImportRequest):
    """
    Descarga un video de TikTok a partir de su URL y lo procesa con el mismo
    pipeline de LangChain que usa Instagram (extraer -> estructurar -> nutrición).
    Termina en el mismo Cookbook (SQLite + Chroma), sin distinción de origen.
    """
    if not LANGCHAIN_AVAILABLE:
        raise HTTPException(status_code=503, detail="LangChain no está instalado.")

    import yt_dlp

    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(body.url, download=False)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"No se pudo leer el video de TikTok: {str(e)}")

    video_id = info.get("id") if info else None
    if not video_id:
        raise HTTPException(status_code=400, detail="No se pudo identificar el video de TikTok (¿la URL es correcta?).")

    media_id = f"tiktok_{video_id}"
    caption = (info.get("description") or info.get("title") or "").strip()

    try:
        from langchain_pipeline import run_recipe_pipeline
        result = run_recipe_pipeline(
            media_id=media_id,
            video_url=body.url,
            gemini_api_key=body.gemini_api_key,
            target_servings=body.target_servings,
            save_to_db=True,
            caption=caption,
        )
        return {"status": "success", "media_id": media_id, "recipe": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en pipeline: {str(e)}")
