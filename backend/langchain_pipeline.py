"""
langchain_pipeline.py
=====================
Pipeline de LangChain para procesamiento de recetas desde videos/imágenes de Instagram.

Flujo:
  Input (video_url / imagen_url)
      │
      ▼
  [Paso 1] GeminiMediaExtractor  → texto crudo de la receta
      │
      ▼
  [Paso 2] RecipeStructureChain  → JSON estructurado (ingredientes, instrucciones, porciones)
      │
      ▼
  [Paso 3] NutritionCalculatorChain → nutrición por porción + ajuste de cantidades
      │
      ▼
  Diccionario final de receta (guardado en recetas_db.json)
"""

import os
import re
import json
import time
import base64
import tempfile
import requests as req_lib

def get_env_var(key: str) -> str:
    val = os.environ.get(key)
    if val: return val
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith(key + "="):
                    return line.strip().split("=", 1)[1]
    return ""

from typing import Optional, Any
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
from langchain_google_genai import ChatGoogleGenerativeAI

# ──────────────────────────────────────────────
# DB local de recetas (JSON)
# ──────────────────────────────────────────────
RECIPES_DB_FILE = "recetas_db.json"

def load_recipes_db() -> dict:
    """Carga el diccionario de recetas desde el archivo JSON local."""
    if os.path.exists(RECIPES_DB_FILE):
        try:
            with open(RECIPES_DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_recipes_db(db: dict):
    """Guarda el diccionario de recetas en el archivo JSON local."""
    with open(RECIPES_DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def get_recipe(media_id: str) -> Optional[dict]:
    """Obtiene una receta del diccionario por su media_id."""
    db = load_recipes_db()
    return db.get(media_id)

def save_recipe(media_id: str, recipe: dict):
    """Guarda o actualiza una receta en el diccionario por su media_id."""
    db = load_recipes_db()
    db[media_id] = recipe
    save_recipes_db(db)


# ──────────────────────────────────────────────
# PASO 1: Gemini Media Extractor
# Descarga el video/imagen y lo envía a Gemini para extraer texto crudo
# ──────────────────────────────────────────────

def _gemini_post_raw(url: str, payload: dict, timeout: int = 60, max_retries: int = 4) -> dict:
    """POST a Gemini API con retry automático en 429."""
    wait = 15
    for attempt in range(max_retries):
        resp = req_lib.post(url, json=payload, timeout=timeout)
        if resp.status_code == 429:
            time.sleep(wait)
            wait *= 2
            continue
        resp.raise_for_status()
        time.sleep(3)  # cortesía para RPM
        return resp.json()
    resp.raise_for_status()
    return resp.json()


def extract_text_from_media(inputs: dict) -> dict:
    """
    Paso 1: Extrae texto crudo de un video o imagen usando Gemini Files API / inline_data.
    
    Inputs esperados:
        - video_url (str): URL del video o imagen de Instagram
        - media_id (str): ID único del post
        - gemini_api_key (str): API key de Gemini
    
    Output:
        - raw_text (str): Texto crudo extraído por Gemini
        - media_id (str): Mismo media_id de entrada
        - video_url (str): Misma URL de entrada
    """
    video_url: str = inputs["video_url"]
    media_id: str = inputs["media_id"]
    gemini_api_key: str = inputs.get("gemini_api_key") or get_env_var("GEMINI_API_KEY")
    if not gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not set in environment or inputs.")

    is_image = any(ext in video_url.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"])

    EXTRACTION_PROMPT = (
        "Eres un asistente experto en cocina. Observa este contenido (imagen o video) "
        "y transcribe TODA la información relevante de la receta que puedas ver o escuchar: "
        "nombre de la receta, todos los ingredientes con sus cantidades, "
        "todos los pasos del proceso de preparación, tiempo de cocción, "
        "y porciones si se mencionan. "
        "Si hay valores nutricionales visibles, inclúyelos también. "
        "Sé lo más detallado y completo posible. Si el contenido NO es una receta, "
        "responde únicamente: 'NO_ES_RECETA'."
    )

    if is_image:
        # Imagen: usar inline_data con base64
        try:
            from ig_downloader import get_ig_image_bytes
            img_bytes = get_ig_image_bytes(media_id)
            img_b64 = base64.b64encode(img_bytes).decode()
            payload = {
                "contents": [{
                    "parts": [
                        {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}},
                        {"text": EXTRACTION_PROMPT}
                    ]
                }]
            }
            resp = _gemini_post_raw(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={gemini_api_key}",
                payload
            )
            raw_text = resp["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            caption = inputs.get("caption", "")
            if caption:
                # Fallback to using just the caption since the image URL expired
                return {
                    "raw_text": caption,
                    "media_id": media_id,
                    "video_url": video_url,
                    "gemini_api_key": gemini_api_key,
                }
            raise RuntimeError(f"Error extrayendo texto de imagen: {str(e)}")

    else:
        # Video: descargar y subir a Gemini Files API
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                tmp_path = tmp.name
                
            # Descarga con reintentos + backoff; si la URL directa falló del
            # todo (ej. venció), cae internamente a yt-dlp con el media_id.
            from ig_media import download_media, MediaDownloadError
            try:
                download_media(video_url, tmp_path, media_id=media_id)
            except MediaDownloadError as e:
                raise RuntimeError(f"Fallo al descargar video: {str(e)}")

            # Subir a Gemini Files API
            print("Uploading to Gemini Files API...")
            upload_url = (
                f"https://generativelanguage.googleapis.com/upload/v1beta/files"
                f"?uploadType=multipart&key={gemini_api_key}"
            )
            with open(tmp_path, "rb") as f:
                video_bytes = f.read()

            boundary = "bound_recipe_pipeline"
            metadata = json.dumps({"file": {"display_name": media_id}}).encode()
            body = (
                f"--{boundary}\r\nContent-Type: application/json\r\n\r\n"
            ).encode() + metadata + (
                f"\r\n--{boundary}\r\nContent-Type: video/mp4\r\n\r\n"
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
            print(f"Uploaded! file_name: {file_name}")

            # Esperar a que Gemini procese el video (estado ACTIVE)
            print("Waiting for video processing...")
            for _ in range(12):
                time.sleep(5)
                try:
                    status_resp = req_lib.get(
                        f"https://generativelanguage.googleapis.com/v1beta/{file_name}?key={gemini_api_key}",
                        timeout=30
                    )
                    state = status_resp.json().get("state")
                    print(f"Video state: {state}")
                    if status_resp.ok and state == "ACTIVE":
                        break
                except Exception as e:
                    print(f"Error checking status: {e}")

            # Llamar a generateContent con el video subido
            print("Calling generateContent...")
            payload = {
                "contents": [{
                    "parts": [
                        {"file_data": {"mime_type": "video/mp4", "file_uri": file_uri}},
                        {"text": EXTRACTION_PROMPT + " También, identifica en qué segundo exacto (timestamp en formato decimal, ej 3.5) se ve el plato terminado en su mejor presentación. Inclúyelo al final de tu respuesta en este formato exacto: [TIMESTAMP: 3.5]"}
                    ]
                }]
            }
            resp = _gemini_post_raw(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={gemini_api_key}",
                payload,
                timeout=60
            )
            print("generateContent successful!")
            raw_text = resp["candidates"][0]["content"]["parts"][0]["text"]
            
            # Extraer frame usando cv2 antes de borrar el video
            print("Extracting frame...")
            try:
                import re
                match = re.search(r'\[TIMESTAMP:\s*([\d\.]+)\]', raw_text)
                if match:
                    timestamp = float(match.group(1))
                    print(f"Found timestamp: {timestamp}")
                    from video_utils import extract_end_frame
                    extract_end_frame(None, media_id, local_video_path=tmp_path, target_timestamp=timestamp)
                else:
                    print("No timestamp found in response")
            except Exception as cv_err:
                print("Error extracting frame from Gemini timestamp:", cv_err)

        except Exception as e:
            print("Exception in extract_text_from_media:", str(e))
            caption = inputs.get("caption", "")
            if caption:
                # Fallback to using just the caption since the video URL expired
                return {
                    "raw_text": caption,
                    "media_id": media_id,
                    "video_url": video_url,
                    "gemini_api_key": gemini_api_key,
                }
            raise RuntimeError(f"Error extrayendo texto de video y sin caption: {str(e)}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    return {
        "raw_text": raw_text,
        "media_id": media_id,
        "video_url": video_url,
        "gemini_api_key": gemini_api_key,
    }


# ──────────────────────────────────────────────
# PASO 2: Recipe Structure Chain
# Toma el texto crudo y lo estructura en JSON de receta
# ──────────────────────────────────────────────

STRUCTURE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """Eres un asistente experto en estructurar recetas de cocina.
Tu tarea es tomar un texto crudo que describe una receta y convertirlo en un JSON perfectamente estructurado.

REGLAS ESTRICTAS:
1. Responde ÚNICAMENTE con JSON válido, sin markdown, sin bloques de código, sin texto adicional.
2. Si el texto dice 'NO_ES_RECETA', devuelve exactamente: {{"nombre": null}}
3. Si el tiempo no se menciona, usa null. Si las porciones no se mencionan explícitamente, infiérelas lógicamente basándote en las cantidades de los ingredientes (ej: 250g de pasta suele ser 2 porciones). Si no hay cantidades, usa 1.
4. Normaliza las cantidades: convierte tazas, cucharadas, etc. a gramos/ml cuando sea posible.
5. Separa cada paso de las instrucciones como un elemento independiente de la lista.
6. Genera una lista de 'tags' indicando el tipo de comida (ej: desayuno, almuerzo, cena, postre, snack) según los ingredientes y el estilo.
7. Identifica el 'tipo_cocina' (ej: italiana, mexicana, asiática, mediterránea, americana, latina, fusión, etc.) según los ingredientes y técnicas usadas. Si no es claramente de ninguna tradición específica, usa "internacional".
8. Clasifica 'dificultad' como "facil", "media" o "dificil", según la cantidad de pasos, técnicas involucradas y tiempo de preparación.

Estructura JSON requerida:
{{
  "nombre": "Nombre de la receta",
  "tiempo_preparacion_min": 30,
  "porciones": 4,
  "tags": ["almuerzo", "cena"],
  "tipo_cocina": "italiana",
  "dificultad": "facil",
  "ingredientes": [
    {{"nombre": "nombre del ingrediente", "cantidad": 200, "unidad": "g"}}
  ],
  "instrucciones": [
    "Paso 1: ...",
    "Paso 2: ..."
  ]
}}"""),
    ("human", "Texto de la receta:\n\n{raw_text}")
])


def structure_recipe(inputs: dict) -> dict:
    """
    Paso 2: Estructura el texto crudo en un JSON de receta usando LangChain + Gemini.
    Si el texto es 'NO_ES_RECETA', retorna un dict con nombre=null.
    """
    raw_text: str = inputs["raw_text"]
    gemini_api_key: str = inputs.get("gemini_api_key") or get_env_var("GEMINI_API_KEY")

    if "NO_ES_RECETA" in raw_text.upper():
        return {
            **inputs,
            "structured_recipe": {"nombre": None}
        }

    llm = ChatGoogleGenerativeAI(
        model="gemini-flash-lite-latest",
        google_api_key=gemini_api_key,
        temperature=0.0,
    )
    chain = STRUCTURE_PROMPT | llm | JsonOutputParser()

    try:
        structured = chain.invoke({"raw_text": raw_text})
    except Exception:
        # Fallback: intentar parsear el JSON de la respuesta de texto directamente
        try:
            response = (STRUCTURE_PROMPT | llm).invoke({"raw_text": raw_text})
            text = response.content if hasattr(response, "content") else str(response)
            if isinstance(text, list):
                # Gemini a veces devuelve el contenido como lista de partes en vez de string plano
                text = " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in text)
            match = re.search(r'\{[\s\S]*\}', text)
            structured = json.loads(match.group(0)) if match else {"nombre": None}
        except Exception as e:
            raise RuntimeError(f"Error estructurando receta: {str(e)}")

    return {
        **inputs,
        "structured_recipe": structured,
    }


# ──────────────────────────────────────────────
# PASO 3: Nutrition Calculator Chain
# Calcula valores nutricionales y ajusta cantidades por número de personas
# ──────────────────────────────────────────────

NUTRITION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """Eres un nutricionista experto y calculador de macronutrientes.
Tu tarea es calcular los valores nutricionales de una receta y ajustar las cantidades según el número de personas objetivo.

CONSTANTES CALÓRICAS:
- 1g de Grasa = 9 kcal
- 1g de Proteína = 4 kcal  
- 1g de Carbohidratos = 4 kcal
- 1g de Azúcar = 4 kcal (subcategoría de carbohidratos)
- 1g de Fibra = 2 kcal

REGLAS:
1. Responde ÚNICAMENTE con JSON válido, sin markdown, sin bloques de código.
2. Los valores nutricionales deben ser POR PORCIÓN (del target_servings).
3. Si la receta tiene valores nutricionales explícitos en el texto, úsalos. Si no, calcúlalos basándote en los ingredientes.
4. Para ajustar ingredientes: multiplica cada cantidad por (target_servings / porciones_originales).
5. Redondea cantidades a 1 decimal.

Estructura JSON requerida:
{{
  "nutricion_por_porcion": {{
    "calorias": 350,
    "proteina_g": 25.0,
    "carbohidratos_g": 40.0,
    "grasa_g": 8.0,
    "azucares_g": 5.0,
    "fibra_g": 3.0
  }},
  "origen_nutricional": "Calculado por IA",
  "porciones_originales": 4,
  "porciones_ajustadas": 2,
  "ingredientes_ajustados": [
    {{"nombre": "nombre del ingrediente", "cantidad": 100.0, "unidad": "g"}}
  ]
}}"""),
    ("human", """Receta estructurada:
{structured_recipe_json}

Porciones originales: {porciones_originales}
Porciones objetivo (target): {target_servings}""")
])


def calculate_nutrition(inputs: dict) -> dict:
    """
    Paso 3: Calcula nutrición por porción y ajusta cantidades según target_servings.
    """
    structured_recipe: dict = inputs["structured_recipe"]
    gemini_api_key: str = inputs.get("gemini_api_key") or get_env_var("GEMINI_API_KEY")
    target_servings: int = inputs.get("target_servings", 0)

    # Si no es receta, retornar tal cual
    if not structured_recipe.get("nombre"):
        return {
            **inputs,
            "final_recipe": {
                "media_id": inputs["media_id"],
                "nombre": None,
                "is_recipe": False,
            }
        }

    porciones_originales = structured_recipe.get("porciones", 1) or 1
    # Si no se especifica target_servings, usar las porciones originales
    if not target_servings or target_servings <= 0:
        target_servings = porciones_originales

    llm = ChatGoogleGenerativeAI(
        model="gemini-flash-lite-latest",
        google_api_key=gemini_api_key,
        temperature=0.0,
    )
    chain = NUTRITION_PROMPT | llm | JsonOutputParser()

    try:
        nutrition_data = chain.invoke({
            "structured_recipe_json": json.dumps(structured_recipe, ensure_ascii=False),
            "porciones_originales": porciones_originales,
            "target_servings": target_servings,
        })
    except Exception:
        # Fallback: parsear de texto
        try:
            response = (NUTRITION_PROMPT | llm).invoke({
                "structured_recipe_json": json.dumps(structured_recipe, ensure_ascii=False),
                "porciones_originales": porciones_originales,
                "target_servings": target_servings,
            })
            text = response.content if hasattr(response, "content") else str(response)
            match = re.search(r'\{[\s\S]*\}', text)
            nutrition_data = json.loads(match.group(0)) if match else {}
        except Exception as e:
            raise RuntimeError(f"Error calculando nutrición: {str(e)}")

    from video_utils import extract_end_frame
    thumb_url = extract_end_frame(inputs.get("video_url", ""), inputs["media_id"])

    # Construir receta final completa
    final_recipe = {
        "media_id": inputs["media_id"],
        "video_url": inputs.get("video_url", ""),
        "thumbnail_url": thumb_url or inputs.get("video_url", ""),
        "is_recipe": True,
        "nombre": structured_recipe.get("nombre"),
        "tiempo_preparacion_min": structured_recipe.get("tiempo_preparacion_min"),
        "porciones_originales": nutrition_data.get("porciones_originales", porciones_originales),
        "porciones_ajustadas": nutrition_data.get("porciones_ajustadas", target_servings),
        "tags": structured_recipe.get("tags", []),
        "tipo_cocina": structured_recipe.get("tipo_cocina"),
        "dificultad": structured_recipe.get("dificultad"),
        "ingredientes": structured_recipe.get("ingredientes", []),
        "ingredientes_ajustados": nutrition_data.get("ingredientes_ajustados", []),
        "instrucciones": structured_recipe.get("instrucciones", []),
        "nutricion_por_porcion": nutrition_data.get("nutricion_por_porcion", {}),
        "origen_nutricional": nutrition_data.get("origen_nutricional", "Calculado por IA"),
    }

    return {
        **inputs,
        "final_recipe": final_recipe,
    }


# ──────────────────────────────────────────────
# PIPELINE COMPLETO
# Orquesta los 3 pasos en secuencia con LCEL
# ──────────────────────────────────────────────

def build_recipe_pipeline():
    """
    Construye y retorna el pipeline completo de LangChain como una cadena LCEL.
    
    Uso:
        pipeline = build_recipe_pipeline()
        result = pipeline.invoke({
            "media_id": "123456",
            "video_url": "https://...",
            "gemini_api_key": "AIza...",
            "target_servings": 2  # opcional
        })
        print(result["final_recipe"])
    """
    pipeline = (
        RunnableLambda(extract_text_from_media)   # Paso 1: Gemini → texto crudo
        | RunnableLambda(structure_recipe)         # Paso 2: texto → JSON estructurado
        | RunnableLambda(calculate_nutrition)      # Paso 3: JSON → nutrición + ajuste
    )
    return pipeline


def run_recipe_pipeline(
    media_id: str,
    video_url: str,
    gemini_api_key: str,
    target_servings: int = 0,
    save_to_db: bool = True,
    caption: str = "",
) -> dict:
    """
    Función de alto nivel que ejecuta el pipeline completo y guarda la receta en la DB local.
    
    Args:
        media_id: ID único del post de Instagram (clave del diccionario)
        video_url: URL directa del video o imagen
        gemini_api_key: API Key de Gemini
        target_servings: Para cuántas personas ajustar (0 = usar porciones originales)
        save_to_db: Si True, guarda la receta en recetas_db.json
    
    Returns:
        dict: La receta final con ingredientes, instrucciones, nutrición y ajuste de porciones
    """
    pipeline = build_recipe_pipeline()
    result = pipeline.invoke({
        "media_id": media_id,
        "video_url": video_url,
        "gemini_api_key": gemini_api_key,
        "target_servings": target_servings,
        "caption": caption,
    })

    final_recipe = result.get("final_recipe", {})

    if save_to_db and final_recipe.get("is_recipe"):
        save_recipe(media_id, final_recipe)
        # Persistir también en SQLite: es lo que /api/recipes y el Cookbook
        # realmente leen. Antes esto requería correr un script aparte a mano.
        try:
            from recipe_store import persist_recipe_to_sqlite
            persist_recipe_to_sqlite(media_id, final_recipe)
        except Exception as e:
            print(f"[langchain_pipeline] Aviso: no se pudo persistir '{media_id}' en SQLite: {e}")

    return final_recipe
