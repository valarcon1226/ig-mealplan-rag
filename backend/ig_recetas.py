import os
import re
import json
import hmac
import hashlib
import secrets
import zipfile
import time
import tempfile
import threading
import requests as req_lib
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Dict, Literal

from ig_media import download_media, download_bytes, MediaDownloadError  # descargas por URL, sin sesión de Instagram

# LangChain pipeline (import opcional — solo falla si no está instalado)
try:
    from langchain_pipeline import run_recipe_pipeline, get_recipe, load_recipes_db
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False

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

@app.on_event("startup")
def startup():
    load_jobs()


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

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    return salt.hex() + "$" + hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1).hex()

def verify_password(password: str, stored: str) -> bool:
    salt_hex, hash_hex = stored.split("$", 1)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1).hex()
    return hmac.compare_digest(digest, hash_hex)

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class UserDataRequest(BaseModel):
    profile: dict
    recipes: list
    eatLog: list = []

def _new_session(db, user) -> dict:
    from models import AuthSession
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token=token, user_id=user.id))
    db.commit()
    return {"token": token, "user": {"name": user.name, "email": user.email}}

def current_user(authorization: str = Header(default="")):
    """Devuelve (db, user) del token `Authorization: Bearer ...`, o 401."""
    from database import SessionLocal
    from models import AuthSession, User
    token = authorization.removeprefix("Bearer ").strip()
    db = SessionLocal()
    try:
        session = db.get(AuthSession, token) if token else None
        user = db.get(User, session.user_id) if session else None
        if not user:
            raise HTTPException(status_code=401, detail="Sesión inválida o expirada")
        yield db, user, session
    finally:
        db.close()

@app.post("/auth/register")
def register(body: RegisterRequest):
    from database import SessionLocal
    from models import User
    name, email = body.name.strip(), body.email.strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="Escribe tu nombre")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(status_code=400, detail="Correo inválido")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 8 caracteres")
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == email).first():
            raise HTTPException(status_code=409, detail="Ya existe una cuenta con ese correo")
        user = User(name=name, email=email, password_hash=hash_password(body.password))
        db.add(user)
        db.commit()
        return _new_session(db, user)
    finally:
        db.close()

@app.post("/auth/login")
def login(body: LoginRequest):
    from database import SessionLocal
    from models import User
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == body.email.strip().lower()).first()
        if not user or not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos")
        return _new_session(db, user)
    finally:
        db.close()

@app.post("/auth/logout")
def logout(ctx=Depends(current_user)):
    db, _, session = ctx
    db.delete(session)
    db.commit()
    return {"status": "success"}

@app.get("/me/data")
def get_my_data(ctx=Depends(current_user)):
    _, user, _ = ctx
    return {"user": {"name": user.name, "email": user.email}, "data": json.loads(user.data) if user.data else None}

@app.put("/me/data")
def put_my_data(body: UserDataRequest, ctx=Depends(current_user)):
    db, user, _ = ctx
    user.data = json.dumps(body.model_dump(), ensure_ascii=False)
    db.commit()
    return {"status": "success"}



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
    use_pantry: bool = True  # priorizar recetas con lo que hay en la despensa (lo que vence primero)

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
            "category": r.category,
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
    from diet import fold

    q = req.q.strip()
    if not q:
        raise HTTPException(status_code=400, detail="La búsqueda está vacía.")
    if len(q) > 200:
        raise HTTPException(status_code=400, detail="La búsqueda es muy larga (máx. 200 caracteres).")
    try:
        result = search(fold(q))  # sin tildes: "asiático" y "asiatico" son la misma búsqueda (y el mismo caché)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"No se pudo buscar: {e}")

    db = SessionLocal()
    try:
        id_by_media = dict(db.query(Recipe.media_id, Recipe.id).all())
    finally:
        db.close()
    ids = [str(id_by_media[m]) for m in result["media_ids"] if m in id_by_media]
    return {"ids": list(dict.fromkeys(ids)), "filters": result["filters"]}

def _pantry_by_urgency(db, limit: int = 12) -> List[str]:
    """Nombres de la despensa con stock, lo que vence primero adelante (shelf_life.py)."""
    from models import PantryItem
    from shelf_life import days_left
    items = [i for i in db.query(PantryItem).all() if (i.amount or "").strip() not in ("0", "0 g", "0 ml")]
    items.sort(key=lambda i: days_left(i.name, i.added_at))
    return [i.name for i in items[:limit]]


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
                     "avoid": request.avoid, "likes": request.likes,
                     "pantry": _pantry_by_urgency(db) if request.use_pantry else []},
        )
    except Exception as e:
        db.close()
        raise HTTPException(status_code=400, detail=str(e))
        
    db.close()
    return result


@app.post("/api/mealplan/from-pantry")
def generate_mealplan_from_pantry(request: MealPlanRequest, ctx=Depends(current_user)):
    """Plan día por día solo con lo que hay en la despensa (ver pantry_planner.py)."""
    db, user, _ = ctx
    from pantry_planner import plan_from_pantry
    g = request.dailyGoals
    targets = {"calorias": g.get("calories", 2000), "proteinas": g.get("protein", 150),
               "carbohidratos": g.get("carbs", 200), "grasas": g.get("fat", 60),
               "azucares": g.get("sugar"), "fibra": g.get("fiber")}
    try:
        return plan_from_pantry(
            db, [m.lower() for m in request.meals], targets, request.restrictions,
            {"goal": request.goal, "is_pregnant": request.is_pregnant, "avoid": request.avoid, "likes": request.likes},
            max_days=max(1, min(14, request.num_days)),
            user_id=user.id,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class InstagramExportUpload(BaseModel):
    filename: str
    data_base64: str  # el ZIP (o JSON) de "Descargar tu información", como en el escaneo de boletas


def _saved_summary(db, user_id: int = None) -> dict:
    """Cuántos guardados hay por colección y estado (para la pantalla de importación)."""
    from collections import Counter
    from models import SavedImport
    q = db.query(SavedImport.collection, SavedImport.status)
    if user_id is not None:
        q = q.filter(SavedImport.user_id == user_id)
    rows = q.all()
    by_col: dict = {}
    for col, status in rows:
        by_col.setdefault(col or "Sin colección", Counter())[status] += 1
    return {
        "total": len(rows),
        "por_estado": dict(Counter(s for _, s in rows)),
        "colecciones": sorted(({"nombre": k, "total": sum(v.values()), **v} for k, v in by_col.items()),
                              key=lambda c: -c["total"]),
    }


@app.post("/api/import/instagram-export")
def import_instagram_export(body: InstagramExportUpload, ctx=Depends(current_user)):
    """
    Importa en bloque los guardados desde la exportación oficial de Instagram, sin
    entrar a la cuenta. Quedan en la cola `saved_imports`; los que ya están en el
    recetario se marcan "en_recetario".
    """
    import base64
    import zipfile
    from ig_export import parse_export, shortcode_to_pk
    from models import Recipe, SavedImport

    try:
        posts = parse_export(base64.b64decode(body.data_base64), body.filename)
    except (ValueError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as e:
        raise HTTPException(status_code=400, detail=f"No pude leer la exportación: {e}")

    db, user, _ = ctx
    # media_id de las recetas es "<pk>_<user>": con el pk se reconoce lo que ya está.
    have_pks = {(m or "").split("_")[0] for (m,) in db.query(Recipe.media_id).all()}
    existing = {s.shortcode: s for s in db.query(SavedImport).filter(SavedImport.user_id == user.id).all()}
    nuevos = 0
    for p in posts:
        row = existing.get(p["shortcode"])
        if not row:
            row = SavedImport(user_id=user.id, shortcode=p["shortcode"], url=p["url"], status="pendiente")
            db.add(row)
            nuevos += 1
        row.username = p["username"] or row.username
        row.collection = p["collection"] or row.collection
        row.saved_at = p["saved_at"] or row.saved_at
        if row.status == "pendiente" and shortcode_to_pk(p["shortcode"]) in have_pks:
            row.status = "en_recetario"
    db.commit()
    return {"leidos": len(posts), "nuevos": nuevos, **_saved_summary(db, user_id=user.id)}


@app.get("/api/import/saved")
def get_saved_imports(ctx=Depends(current_user)):
    db, user, _ = ctx
    return _saved_summary(db, user_id=user.id)


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
def get_pantry(ctx=Depends(current_user)):
    db, user, _ = ctx
    from models import PantryItem
    from datetime import date
    from shelf_life import days_left
    items = db.query(PantryItem).filter(PantryItem.user_id == user.id).all()
    for i in items:
        if not i.added_at:  # items de antes de guardar la fecha: se cuentan desde hoy
            i.added_at = date.today().isoformat()
    db.commit()
    result = [{"id": i.id, "name": i.name, "amount": i.amount, "added_at": i.added_at,
               "days_left": days_left(i.name, i.added_at)} for i in items]
    # Lo que vence primero, arriba.
    return sorted(result, key=lambda r: r["days_left"])

@app.post("/api/pantry")
def add_pantry_item(item: PantryItemCreate, ctx=Depends(current_user)):
    """
    Si ya existe un item con el mismo nombre (ej. al tildar un item de la
    grocery list dos semanas seguidas), suma la cantidad en vez de crear una
    fila duplicada - pero solo cuando ambas cantidades tienen la misma
    unidad; si no, no adivinamos la suma y se guarda como fila aparte.
    """
    db, user, _ = ctx
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

    # "Huevos" y "huevo" son el mismo item; el pantry es chico, se recorre entero.
    norm = normalize_ingredient_name(name_clean) or name_clean.lower()
    existing = next((p for p in db.query(PantryItem).filter(PantryItem.user_id == user.id).all()
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

    from datetime import date
    # Si se suma a un item existente se conserva su fecha (lo más viejo se daña primero).
    new_item = PantryItem(user_id=user.id, name=name_clean, amount=item.amount, added_at=date.today().isoformat())
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    return {"id": new_item.id, "name": new_item.name, "amount": new_item.amount}

class PantryRemoveByName(BaseModel):
    name: str

@app.post("/api/pantry/remove")
def remove_pantry_ingredient(item: PantryRemoveByName, ctx=Depends(current_user)):
    """
    Al desmarcar un item de la grocery list ("no lo tengo"): borra ese
    ingrediente del pantry, con el mismo matching de nombre que usa la lista
    ("Huevos" == "huevo"). Restar solo lo necesario dejaría el item cubierto
    si había stock de sobra, y el check volvería a marcarse solo.
    """
    db, user, _ = ctx
    from models import PantryItem
    from ingredient_normalizer import normalize_ingredient_name

    name_clean = item.name.strip()
    if not name_clean:
        raise HTTPException(status_code=400, detail="El nombre no puede estar vacío")

    norm = normalize_ingredient_name(name_clean) or name_clean.lower()
    for p in db.query(PantryItem).filter(PantryItem.user_id == user.id).all():
        if (normalize_ingredient_name(p.name) or p.name.lower()) == norm:
            db.delete(p)
    db.commit()
    return {"status": "ok"}

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
def scan_receipt(req: ReceiptScanRequest, ctx=Depends(current_user)):
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
def delete_pantry_item(item_id: int, ctx=Depends(current_user)):
    db, user, _ = ctx
    from models import PantryItem
    item = db.query(PantryItem).filter(PantryItem.id == item_id).first()
    if not item or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Item no encontrado")
    db.delete(item)
    db.commit()
    return {"status": "ok"}

class GroceryPlanRequest(BaseModel):
    meals: List[Dict]

@app.post("/api/grocery/generate")
def generate_grocery_list(req: GroceryPlanRequest, ctx=Depends(current_user)):
    """
    Genera la lista de compras de forma determinística (sin LLM):
    1. Suma los ingredientes de TODAS las recetas del plan (día o semana).
    2. Resta lo que ya hay en el Pantry.
    3. Devuelve solo lo que falta, con la cantidad faltante exacta.
    """
    db, user, _ = ctx
    from models import PantryItem
    from shopping_list import generate_shopping_list

    pantry_items = db.query(PantryItem).filter(PantryItem.user_id == user.id).all()
    grocery_list = generate_shopping_list(req.meals, pantry_items)
    return {"grocery_list": grocery_list}


# ─────────────────────────────────────────────────────────────────────────────
# PROCESAMIENTO AUTOMÁTICO EN LOTE DE UNA CARPETA (flujo: conectar → carpeta →
# video por video → download_media → JSON → LLM completa nutrición → Cookbook)
# ─────────────────────────────────────────────────────────────────────────────

BATCH_JOBS: Dict[str, Dict] = {}


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
