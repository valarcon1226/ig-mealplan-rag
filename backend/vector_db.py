import os
import json
import chromadb
from chromadb.utils import embedding_functions
from typing import List, Dict, Any

DB_PATH = os.path.join(os.path.dirname(__file__), "chroma_db")
RECIPES_FILE = os.path.join(os.path.dirname(__file__), "recetas_saludables_backup.json")

def get_chroma_client():
    """Returns a PersistentClient for ChromaDB."""
    return chromadb.PersistentClient(path=DB_PATH)

def infer_dietary_restrictions(recipe: Dict[str, Any]) -> List[str]:
    """Restricciones de dieta que la receta cumple (ver diet.py)."""
    from diet import diet_labels
    ingredientes = recipe.get("ingredientes_ajustados") or recipe.get("ingredientes", [])
    nutricion = recipe.get("nutricion_por_porcion") or {}
    return diet_labels(
        recipe.get("tags", []),
        [ing.get("nombre", "") for ing in ingredientes if isinstance(ing, dict)],
        nutricion.get("azucares_g"),
    )

def load_recipes_data(media_ids: List[str] = None) -> List[Dict[str, Any]]:
    """
    Carga las recetas desde SQLite - la fuente real desde que run_recipe_pipeline
    persiste ahí (ver recipe_store.py). Antes esto leía recetas_saludables_backup.json
    -> post["ai_analysis"], un campo que el pipeline en vivo nunca escribe, así que
    ninguna receta procesada por la app terminaba indexada en Chroma.
    """
    from database import SessionLocal
    from models import Recipe

    db = SessionLocal()
    try:
        query = db.query(Recipe).filter(Recipe.nombre.isnot(None))
        if media_ids:
            query = query.filter(Recipe.media_id.in_(media_ids))
        recipes = query.all()
        recipes_list = []
        for r in recipes:
            try:
                ingredientes = json.loads(r.ingredients_raw) if r.ingredients_raw else []
            except Exception:
                ingredientes = []
            try:
                instrucciones = json.loads(r.instructions) if r.instructions else []
            except Exception:
                instrucciones = []

            recipes_list.append({
                "id": r.media_id,
                "nombre": r.nombre,
                "tags": [t.strip() for t in (r.tags or "").split(",") if t.strip()],
                "cuisine_type": r.cuisine_type,
                "dificultad": r.dificultad,
                "category": r.category,
                "ingredientes": ingredientes,
                "instrucciones": instrucciones,
                "tiempo_preparacion_min": r.tiempo_preparacion_min,
                "video_url": r.video_url,
                "thumbnail_url": r.thumbnail_url,
                "nutricion_por_porcion": {
                    "calorias": r.nutrition.calories if r.nutrition else 0,
                    "proteina_g": r.nutrition.proteins if r.nutrition else 0,
                    "carbohidratos_g": r.nutrition.carbohydrates if r.nutrition else 0,
                    "grasa_g": r.nutrition.fats if r.nutrition else 0,
                    "azucares_g": r.nutrition.sugars if r.nutrition else None,
                    "fibra_g": r.nutrition.fiber if r.nutrition else None,
                } if r.nutrition else {},
            })
        print(f"Loaded {len(recipes_list)} recipes from SQLite.")
        return recipes_list
    finally:
        db.close()

def get_or_create_collection(client, collection_name: str = "recipes_collection"):
    """Gets or creates the ChromaDB collection with the sentence transformer embedding function."""
    sentence_transformer_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )
    
    return client.get_or_create_collection(
        name=collection_name,
        embedding_function=sentence_transformer_ef,
        metadata={"hnsw:space": "cosine"}
    )

def populate_collection(collection, recipes: List[Dict[str, Any]]):
    """Formats recipes into text documents and inserts them into the collection."""
    documents = []
    metadatas = []
    ids = []
    
    for recipe in recipes:
        recipe_id = recipe.get("id")
        if not recipe_id:
            continue
            
        nombre = recipe.get("nombre", "Sin nombre")
        restricciones = infer_dietary_restrictions(recipe)
        
        # Build a comprehensive text document for the embedding
        text_parts = [f"Receta: {nombre}"]
        
        if restricciones:
            text_parts.append(f"Restricciones alimentarias: {', '.join(restricciones)}")
            
        tags = recipe.get("tags", [])
        if tags:
            text_parts.append(f"Etiquetas: {', '.join(tags)}")

        category = recipe.get("category")
        if category:
            text_parts.append(f"Categoría: {category.replace('_', ' ')}")

        cuisine_type = recipe.get("cuisine_type")
        if cuisine_type:
            text_parts.append(f"Tipo de cocina: {cuisine_type}")

        dificultad = recipe.get("dificultad")
        if dificultad:
            text_parts.append(f"Dificultad: {dificultad}")

        # Add ingredients
        ingredientes = recipe.get("ingredientes_ajustados") or recipe.get("ingredientes", [])
        ing_texts = []
        for ing in ingredientes:
            cant = ing.get("cantidad")
            unidad = ing.get("unidad")
            nombre_ing = ing.get("nombre")
            if cant and unidad:
                ing_texts.append(f"{cant} {unidad} de {nombre_ing}")
            elif nombre_ing:
                ing_texts.append(nombre_ing)
        
        if ing_texts:
            text_parts.append(f"Ingredientes: {', '.join(ing_texts)}")
        
        # Add nutrition
        nutricion = recipe.get("nutricion_por_porcion", {})
        if nutricion:
            calorias = nutricion.get("calorias", 0)
            proteina = nutricion.get("proteina_g", 0)
            azucar = nutricion.get("azucares_g")
            fibra = nutricion.get("fibra_g")
            nut_text = f"Nutrición: {calorias} kcal, {proteina}g proteína"
            if azucar is not None:
                nut_text += f", {azucar}g azúcar"
            if fibra is not None:
                nut_text += f", {fibra}g fibra"
            text_parts.append(nut_text + " por porción.")
            
        tiempo = recipe.get("tiempo_preparacion_min")
        if tiempo:
            text_parts.append(f"Tiempo de preparacion: {tiempo} minutos.")
            
        # Add instructions
        instrucciones = recipe.get("instrucciones", [])
        if instrucciones:
            text_parts.append(f"Instrucciones: {', '.join(instrucciones)}")
            
        text = ". ".join(text_parts)
        
        # Prepare metadata
        meta = {
            "nombre": nombre,
            "calorias": float(nutricion.get("calorias", 0)) if isinstance(nutricion, dict) else 0.0,
            "proteina": float(nutricion.get("proteina_g", 0)) if isinstance(nutricion, dict) else 0.0,
            "azucar": float(nutricion.get("azucares_g")) if isinstance(nutricion, dict) and nutricion.get("azucares_g") is not None else -1.0,
            "fibra": float(nutricion.get("fibra_g")) if isinstance(nutricion, dict) and nutricion.get("fibra_g") is not None else -1.0,
            "tiempo": int(tiempo) if tiempo else 0,
            "tags": ", ".join(tags),
            "cuisine_type": cuisine_type or "",
            "category": category or "",
            "dificultad": dificultad or "",
            "restricciones": ", ".join(restricciones),
            "ingredientes": ", ".join(ing_texts),
            "instrucciones": " | ".join(instrucciones),
            "video_url": recipe.get("video_url", ""),
            "thumbnail_url": recipe.get("thumbnail_url", "")
        }
        
        documents.append(text)
        metadatas.append(meta)
        ids.append(recipe_id)
        
    print(f"Upserting {len(documents)} documents into ChromaDB...")
    collection.upsert(
        documents=documents,
        metadatas=metadatas,
        ids=ids
    )
    print("Done!")

def index_recipes(media_ids: List[str]):
    """Vectoriza (upsert) solo estas recetas: se llama al guardar cada receta."""
    recipes = load_recipes_data(media_ids)
    if recipes:
        populate_collection(get_or_create_collection(get_chroma_client()), recipes)


def perform_similarity_search(collection, query: str, n_results: int = 5) -> List[Dict[str, Any]]:
    results = collection.query(
        query_texts=[query],
        n_results=n_results
    )
    
    formatted_results = []
    if not results['ids'] or len(results['ids'][0]) == 0:
        return formatted_results
        
    for i in range(len(results['ids'][0])):
        similarity_score = 1 - results['distances'][0][i]
        
        res = {
            "id": results['ids'][0][i],
            "nombre": results['metadatas'][0][i].get("nombre"),
            "calorias": results['metadatas'][0][i].get("calorias"),
            "proteina": results['metadatas'][0][i].get("proteina"),
            "tags": results['metadatas'][0][i].get("tags"),
            "cuisine_type": results['metadatas'][0][i].get("cuisine_type"),
            "dificultad": results['metadatas'][0][i].get("dificultad"),
            "restricciones": results['metadatas'][0][i].get("restricciones"),
            "ingredientes": results['metadatas'][0][i].get("ingredientes"),
            "instrucciones": results['metadatas'][0][i].get("instrucciones"),
            "video_url": results['metadatas'][0][i].get("video_url"),
            "similarity_score": similarity_score
        }
        formatted_results.append(res)

    return formatted_results

def perform_filtered_search(collection, query: str, min_calories: float = None, max_calories: float = None, min_protein: float = None, max_time: int = None, max_sugar: float = None, min_fiber: float = None, cuisine_type: str = None, dificultad: str = None, n_results: int = 5) -> List[Dict[str, Any]]:
    filters = []

    if min_calories is not None:
        filters.append({"calorias": {"$gte": min_calories}})
    if max_calories is not None:
        filters.append({"calorias": {"$lte": max_calories}})

    if min_protein is not None:
        filters.append({"proteina": {"$gte": min_protein}})
    if max_time is not None:
        filters.append({"tiempo": {"$lte": max_time}})

    # azucar/fibra usan -1.0 como sentinel de "no calculado" (ver populate_collection).
    # Se exige >=0 explícitamente para no dejar pasar recetas sin dato en un filtro de máximo.
    if max_sugar is not None:
        filters.append({"azucar": {"$gte": 0}})
        filters.append({"azucar": {"$lte": max_sugar}})
    if min_fiber is not None:
        filters.append({"fibra": {"$gte": max(min_fiber, 0)}})
    if cuisine_type is not None:
        from recipe_search import canon_cuisine
        filters.append({"cuisine_type": canon_cuisine(cuisine_type)})
    if dificultad is not None:
        filters.append({"dificultad": dificultad.lower().strip()})

    where_clause = None
    if len(filters) == 1:
        where_clause = filters[0]
    elif len(filters) > 1:
        where_clause = {"$and": filters}
        
    results = collection.query(
        query_texts=[query],
        n_results=n_results,
        where=where_clause
    )
    
    formatted_results = []
    if not results['ids'] or len(results['ids'][0]) == 0:
        return formatted_results
        
    for i in range(len(results['ids'][0])):
        similarity_score = 1 - results['distances'][0][i]
        
        res = {
            "id": results['ids'][0][i],
            "nombre": results['metadatas'][0][i].get("nombre"),
            "calorias": results['metadatas'][0][i].get("calorias"),
            "proteina": results['metadatas'][0][i].get("proteina"),
            "azucar": (lambda v: None if v is None or v < 0 else v)(results['metadatas'][0][i].get("azucar")),
            "fibra": (lambda v: None if v is None or v < 0 else v)(results['metadatas'][0][i].get("fibra")),
            "tiempo": results['metadatas'][0][i].get("tiempo"),
            "tags": results['metadatas'][0][i].get("tags"),
            "cuisine_type": results['metadatas'][0][i].get("cuisine_type"),
            "dificultad": results['metadatas'][0][i].get("dificultad"),
            "restricciones": results['metadatas'][0][i].get("restricciones"),
            "ingredientes": results['metadatas'][0][i].get("ingredientes"),
            "instrucciones": results['metadatas'][0][i].get("instrucciones"),
            "similarity_score": similarity_score
        }
        formatted_results.append(res)

    return formatted_results
