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
    """Infers dietary restrictions based on tags and ingredients."""
    restrictions = set()
    tags = [t.lower() for t in recipe.get("tags", [])]
    
    # 1. Tags check
    if "vegetariano" in tags: restrictions.add("Vegetariano")
    if "vegano" in tags: restrictions.add("Vegano")
    if "sin gluten" in tags: restrictions.add("Sin Gluten")
    if "sin lacteos" in tags or "sin lácteos" in tags: restrictions.add("Sin Lácteos")
        
    # 2. Ingredients check
    ingredientes = recipe.get("ingredientes_ajustados") or recipe.get("ingredientes", [])
    ing_nombres = [ing.get("nombre", "").lower() for ing in ingredientes]
    
    meat_keywords = ["pollo", "carne", "res", "cerdo", "tocino", "bacon", "pescado", "atun", "atún", "salmon", "salmón", "camaron", "camarón", "marisco", "pavo", "jamon", "jamón", "salchicha"]
    animal_keywords = meat_keywords + ["queso", "leche", "huevo", "huevos", "mantequilla", "miel", "yogurt", "crema", "suero", "ghee"]
    lactose_keywords = ["queso", "leche", "mantequilla", "yogurt", "crema", "suero"]
    
    has_meat = any(any(mk in ing for mk in meat_keywords) for ing in ing_nombres)
    has_animal = any(any(ak in ing for ak in animal_keywords) for ing in ing_nombres)
    has_lactose = any(any(lk in ing for lk in lactose_keywords) for ing in ing_nombres)
    
    if not has_meat:
        restrictions.add("Vegetariano")
    if not has_animal:
        restrictions.add("Vegano")
        restrictions.add("Vegetariano")
    if not has_lactose:
        restrictions.add("Sin Lácteos")
        
    return sorted(list(restrictions))

def load_recipes_data() -> List[Dict[str, Any]]:
    """Loads recipes from the local backup JSON DB."""
    if not os.path.exists(RECIPES_FILE):
        print(f"File not found: {RECIPES_FILE}")
        return []
    
    with open(RECIPES_FILE, 'r', encoding='utf-8-sig') as f:
        data = json.load(f)
    
    recipes_list = []
    # recetas_saludables_backup.json has a "posts" array
    posts = data.get("posts", [])
    for post in posts:
        ai_analysis = post.get("ai_analysis", {})
        if ai_analysis and ai_analysis.get("is_recipe"):
            # Ensure it has an ID, fallback to media_id if not present
            if not ai_analysis.get("id"):
                ai_analysis["id"] = ai_analysis.get("media_id", post.get("media_id"))
            recipes_list.append(ai_analysis)
    
    print(f"Loaded {len(recipes_list)} recipes from database.")
    return recipes_list

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
            text_parts.append(f"Nutrición: {calorias} kcal, {proteina}g proteína por porción.")
            
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
            "tiempo": int(tiempo) if tiempo else 0,
            "tags": ", ".join(tags),
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
            "restricciones": results['metadatas'][0][i].get("restricciones"),
            "ingredientes": results['metadatas'][0][i].get("ingredientes"),
            "instrucciones": results['metadatas'][0][i].get("instrucciones"),
            "video_url": results['metadatas'][0][i].get("video_url"),
            "similarity_score": similarity_score
        }
        formatted_results.append(res)
        
    return formatted_results

def perform_filtered_search(collection, query: str, max_calories: float = None, min_protein: float = None, max_time: int = None, restriccion: str = None, n_results: int = 5) -> List[Dict[str, Any]]:
    filters = []
    if max_calories is not None:
        filters.append({"calorias": {"$lte": max_calories}})
    if min_protein is not None:
        filters.append({"proteina": {"$gte": min_protein}})
    if max_time is not None:
        filters.append({"tiempo": {"$lte": max_time}})
    if restriccion:
        filters.append({"restricciones": {"$contains": restriccion}})
        
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
            "tiempo": results['metadatas'][0][i].get("tiempo"),
            "tags": results['metadatas'][0][i].get("tags"),
            "restricciones": results['metadatas'][0][i].get("restricciones"),
            "ingredientes": results['metadatas'][0][i].get("ingredientes"),
            "instrucciones": results['metadatas'][0][i].get("instrucciones"),
            "similarity_score": similarity_score
        }
        formatted_results.append(res)
        
    return formatted_results
