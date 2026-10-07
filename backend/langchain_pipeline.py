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

def _gemini_generate(payload: dict, api_key: str, timeout: int = 60) -> dict:
    """
    generateContent rotando modelos (cada uno tiene su cupo gratis diario): si uno
    responde 429 se pasa al siguiente en vez de esperar. Ver llm_chain.py.
    """
    from llm_chain import gemini_models, mark_exhausted, AllProvidersExhausted
    for model in gemini_models(lite=True):
        # La key va en header: en la URL terminaba impresa en los logs de error.
        resp = req_lib.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": api_key}, json=payload, timeout=timeout)
        if resp.status_code == 429:
            mark_exhausted(model)
            continue
        if resp.status_code >= 500:
            # 503 "high demand": el modelo está saturado ahora, no sin cupo -> probar otro sin pausarlo
            print(f"   [llm_chain] {model} respondió {resp.status_code}, probando el siguiente")
            continue
        resp.raise_for_status()
        time.sleep(3)  # cortesía para RPM
        return resp.json()
    raise AllProvidersExhausted("RESOURCE_EXHAUSTED: ningún modelo Gemini con cupo para leer el video/imagen")


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
        "Para CADA paso incluye: qué ingredientes y cuánto se usa, técnica, temperatura "
        "del horno o nivel de fuego, tiempos (cocción, reposo, refrigeración, congelado) "
        "y la señal de que está listo (ej. 'hasta que dore', 'hasta que espese'). "
        "No resumas ni juntes pasos. Si un tiempo o temperatura no se dice pero la técnica "
        "lo requiere (ej. refrigerar la avena nocturna, precalentar el horno), indica el valor "
        "típico marcado como 'aprox.'. "
        "Si hay valores nutricionales visibles, inclúyelos también. "
        "Sé lo más detallado y completo posible. Si el contenido NO es una receta, "
        "responde únicamente: 'NO_ES_RECETA'."
    )
    # El caption suele traer la receta escrita (cantidades, tiempos): se usa junto al video, no solo como fallback.
    caption = inputs.get("caption", "")
    if caption:
        EXTRACTION_PROMPT += f"\n\nTexto del post (caption), úsalo para completar lo que no se vea:\n{caption}"

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
            resp = _gemini_generate(payload, gemini_api_key)
            raw_text = resp["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            from llm_chain import AllProvidersExhausted
            if isinstance(e, AllProvidersExhausted):
                raise  # sin cupo: mejor parar y reintentar que guardar una receta hecha solo con el caption
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
                f"?uploadType=multipart"
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
                headers={"Content-Type": f"multipart/related; boundary={boundary}", "x-goog-api-key": gemini_api_key},
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
                        f"https://generativelanguage.googleapis.com/v1beta/{file_name}",
                        headers={"x-goog-api-key": gemini_api_key}, timeout=30
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
            resp = _gemini_generate(payload, gemini_api_key, timeout=60)
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
            from llm_chain import AllProvidersExhausted
            if isinstance(e, AllProvidersExhausted):
                raise  # sin cupo: mejor parar y reintentar que guardar una receta hecha solo con el caption
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

# Categorías por contenido. Los slugs deben coincidir con las imágenes de
# frontend/public/placeholders (ver DISH_IMAGES en Cookbook.tsx).
CATEGORIAS = {
    "ensaladas": "vegetales u otros ingredientes fríos mezclados y aliñados, bowls tipo poke",
    "sopas": "todo lo líquido que se come con cuchara: sopas, cremas, caldos, ramen",
    "guisos": "cocciones lentas en salsa espesa: curry, estofado, chili, cazuelas",
    "pastas": "pastas y fideos de cualquier tipo",
    "arroces": "el grano es el protagonista: risotto, paella, quinoa, cuscús",
    "aves": "pollo, pavo o pato como plato principal",
    "carnes": "vacuno, cerdo o cordero como plato principal",
    "comida_de_mar": "pescados y mariscos",
    "snacks": "snacks salados para picar: papas fritas, nachos, palomitas, dips",
    "verduras": "verduras cocidas o legumbres como plato principal, tofu",
    "comida_rapida": "hamburguesas, pizzas, sándwiches, tacos, burritos, wraps, empanadas, dumplings",
    "panes": "panes y horneados salados: pan, focaccia, bagels, quiches, crackers",
    "desayunos": "avena, chía, granola, yogur, cottage, panqueques, waffles, huevos",
    "postres": "todo lo dulce: tortas, galletas, helados, mousse, bolitas energéticas",
    "bebidas": "todo lo que se toma: batidos, jugos, cafés, tés, mocktails",
    "untables": "quesos, mantequillas, mermeladas, salsas, aderezos, condimentos y preparaciones caseras en frasco",
}

STRUCTURE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """Eres un asistente experto en estructurar recetas de cocina.
Tu tarea es tomar un texto crudo que describe una receta y convertirlo en un JSON perfectamente estructurado.

REGLAS ESTRICTAS:
1. Responde ÚNICAMENTE con JSON válido, sin markdown, sin bloques de código, sin texto adicional.
2. Si el texto dice 'NO_ES_RECETA', devuelve exactamente: {{"nombre": null}}
3. Si el tiempo no se menciona, usa null. 'porciones' SOLO si el texto dice explícitamente cuántas porciones/personas rinde; si no lo dice, usa null (no adivines: se calculan después a partir de los ingredientes).
4. Normaliza las cantidades: convierte tazas, cucharadas, etc. a gramos/ml cuando sea posible. Si el texto NO dice cuánto de un ingrediente, estima la cantidad típica para esa receta (ej. un bark de yogur: ~300 g de yogur griego) en vez de dejar null: sin cantidades no se puede calcular la nutrición. Solo sal, pimienta y especias "al gusto" pueden quedar sin cantidad.
5. Separa cada paso de las instrucciones como un elemento independiente de la lista. NO resumas: conserva en cada paso las cantidades, temperaturas, nivel de fuego, tiempos (incluido reposo/refrigeración) y señales de punto que traiga el texto, incluidos los valores marcados 'aprox.'. No antepongas "Paso N:".
6. Genera una lista de 'tags' indicando el tipo de comida (ej: desayuno, almuerzo, cena, postre, snack) según los ingredientes y el estilo. IMPORTANTE: si la receta es una salsa, aderezo, dip, mermelada, crema untable, topping o cualquier acompañamiento que NO se coma solo como una comida o snack completo, NO le asignes tags de tipo de comida (desayuno/almuerzo/cena/snack) — en su lugar usa únicamente el tag "condimento" (junto con "salsa", "aderezo", "dip", etc. si aplica). Estos tags de tipo de comida son solo para platos que alguien serviría como esa comida completa por sí sola. Lo mismo para bebidas (chocolate caliente, té, café, jugos, electrolitos, mocktails): usa solo "bebida" y "otros", sin tags de tipo de comida. Y para suplementos o remedios caseros (magnesio en polvo, proteína en polvo, termogénicos): usa solo "suplemento" y "otros".
7. Identifica el 'tipo_cocina' (ej: italiana, mexicana, asiática, mediterránea, americana, latina, fusión, etc.) según los ingredientes y técnicas usadas. Si no es claramente de ninguna tradición específica, usa "internacional".
8. Clasifica 'dificultad' como "facil", "media" o "dificil", según la cantidad de pasos, técnicas involucradas y tiempo de preparación.
9. 'categoria' es QUÉ ES el plato por su contenido (no su origen ni el momento del día). Elige exactamente una de:
""" + "\n".join(f"   - {slug}: {desc}" for slug, desc in CATEGORIAS.items()) + """
10. 'tiempos': minutos de preparación activa, cocción y reposo/refrigeración/congelado (null si no aplica). 'tiempo_preparacion_min' es el total de los tres.

Estructura JSON requerida:
{{
  "nombre": "Nombre de la receta",
  "tiempo_preparacion_min": 30,
  "tiempos": {{"preparacion_min": 10, "coccion_min": 20, "reposo_min": null}},
  "porciones": 4,
  "categoria": "pastas",
  "tags": ["almuerzo", "cena"],
  "tipo_cocina": "italiana",
  "dificultad": "facil",
  "ingredientes": [
    {{"nombre": "nombre del ingrediente", "cantidad": 200, "unidad": "g"}}
  ],
  "instrucciones": [
    "Precalentar el horno a 180°C.",
    "Batir 2 huevos con 50 g de azúcar durante 3 minutos, hasta que blanqueen."
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

    # Rota modelos con cupo (llm_chain.py); si uno devuelve JSON inválido, prueba el siguiente.
    from llm_chain import invoke_json
    try:
        structured = invoke_json(STRUCTURE_PROMPT, {"raw_text": raw_text}, lite=True)
    except Exception as e:
        raise RuntimeError(f"Error estructurando receta: {str(e)}")

    return {
        **inputs,
        "structured_recipe": structured,
    }


# ──────────────────────────────────────────────
# PASO 3: Nutrición y porciones
# El LLM estima gramos/macros POR INGREDIENTE y Python suma, elige las
# porciones y divide (ver nutrition_calc.py). Antes un solo prompt adivinaba
# porciones y macros por porción por separado y no cuadraban entre sí.
# ──────────────────────────────────────────────

def _scale_ingredients(ingredientes: list, factor: float) -> list:
    """Multiplica las cantidades numéricas; "al gusto" y similares quedan igual."""
    if factor == 1:
        return ingredientes
    scaled = []
    for ing in ingredientes:
        ing = dict(ing)
        try:
            ing["cantidad"] = round(float(ing["cantidad"]) * factor, 1)
        except (KeyError, TypeError, ValueError):
            pass
        scaled.append(ing)
    return scaled


def calculate_nutrition(inputs: dict) -> dict:
    """
    Paso 3: Calcula nutrición por porción (coherente con los ingredientes) y
    ajusta cantidades según target_servings.
    """
    from nutrition_calc import calculate

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

    ingredientes = structured_recipe.get("ingredientes", []) or []
    try:
        explicitas = int(structured_recipe.get("porciones") or 0) or None
    except (TypeError, ValueError):
        explicitas = None

    try:
        calc = calculate(
            structured_recipe.get("nombre"), structured_recipe.get("tags", []), ingredientes,
            texto=inputs.get("raw_text", ""), porciones_explicitas=explicitas, api_key=gemini_api_key,
        )
    except Exception as e:
        raise RuntimeError(f"Error calculando nutrición: {str(e)}")

    if calc["status"] == "ok":
        porciones_originales = calc["porciones"]
        n = calc["nutricion_por_porcion"]
        nutricion = {
            "calorias": n["kcal"], "proteina_g": n["proteina_g"], "carbohidratos_g": n["carbohidratos_g"],
            "grasa_g": n["grasa_g"], "azucares_g": n["azucares_g"], "fibra_g": n["fibra_g"],
        }
        origen = "Calculado por IA (por ingrediente)"
    else:
        # Sin cantidades no hay con qué calcular: no se inventan números.
        porciones_originales = explicitas or 1
        nutricion = {}
        origen = "Sin cantidades: nutrición no calculada"

    # Si no se especifica target_servings, usar las porciones originales
    if not target_servings or target_servings <= 0:
        target_servings = porciones_originales

    from video_utils import extract_end_frame, save_remote_image
    # Frame del video; si no es video (post de foto), se guarda la imagen misma.
    thumb_url = (extract_end_frame(inputs.get("video_url", ""), inputs["media_id"])
                 or save_remote_image(inputs.get("video_url", ""), inputs["media_id"]))

    # Construir receta final completa
    final_recipe = {
        "media_id": inputs["media_id"],
        "video_url": inputs.get("video_url", ""),
        "thumbnail_url": thumb_url,  # nunca la URL del CDN: caduca y puede ser un .mp4
        "is_recipe": True,
        "nombre": structured_recipe.get("nombre"),
        "tiempo_preparacion_min": structured_recipe.get("tiempo_preparacion_min"),
        "porciones_originales": porciones_originales,
        "porciones_ajustadas": target_servings,
        "tags": structured_recipe.get("tags", []),
        "tipo_cocina": structured_recipe.get("tipo_cocina"),
        "dificultad": structured_recipe.get("dificultad"),
        "ingredientes": ingredientes,
        "ingredientes_ajustados": _scale_ingredients(ingredientes, target_servings / porciones_originales),
        "instrucciones": structured_recipe.get("instrucciones", []),
        "nutricion_por_porcion": nutricion,
        "origen_nutricional": origen,
        # Si el modelo inventa una categoría fuera de la lista, se deja vacía (el frontend tiene su respaldo).
        "categoria": structured_recipe.get("categoria") if structured_recipe.get("categoria") in CATEGORIAS else None,
        "tiempos": structured_recipe.get("tiempos"),
        # Se guardan para poder re-procesar sin volver a Instagram (reprocess_recipes.py).
        "texto_extraido": inputs.get("raw_text", ""),
        "estructura": structured_recipe,
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
            persist_recipe_to_sqlite(media_id, final_recipe, {"caption": caption})
        except Exception as e:
            print(f"[langchain_pipeline] Aviso: no se pudo persistir '{media_id}' en SQLite: {e}")

    return final_recipe
