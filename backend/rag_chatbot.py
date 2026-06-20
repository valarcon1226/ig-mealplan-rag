import os
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage

from vector_db import get_chroma_client, get_or_create_collection, perform_similarity_search
from langchain_pipeline import get_env_var

def get_llm():
    api_key = get_env_var("GEMINI_API_KEY")
    if not api_key:
        print("ADVERTENCIA: No se encontró GEMINI_API_KEY en el entorno o .env")
        return None
        
    return ChatGoogleGenerativeAI(
        model="gemini-flash-lite-latest",
        google_api_key=api_key,
        temperature=0.7,
    )

def generate_rag_response(llm, query: str, context_results: list) -> str:
    """
    Generates a conversational response using the context from the vector database.
    """
    if not llm:
        return "El modelo Gemini no está configurado (falta API KEY)."
        
    # Formatear el contexto
    context_text = ""
    for i, res in enumerate(context_results, 1):
        context_text += f"\n--- Receta {i} ---\n"
        context_text += f"Nombre: {res['nombre']}\n"
        if res.get('calorias'):
            context_text += f"Calorias: {res['calorias']} kcal\n"
        if res.get('tags'):
            context_text += f"Etiquetas: {res['tags']}\n"
        if res.get('restricciones'):
            context_text += f"Apto para (Restricciones alimentarias): {res['restricciones']}\n"
        if res.get('ingredientes'):
            context_text += f"Ingredientes: {res['ingredientes']}\n"
        if res.get('instrucciones'):
            context_text += f"Instrucciones paso a paso: {res['instrucciones']}\n"
        if res.get('video_url'):
            context_text += f"Video URL: {res['video_url']}\n"
            
    system_prompt = """Eres un asistente culinario experto. 
Tu tarea es recomendar recetas basadas UNICAMENTE en el contexto proporcionado.
Si el usuario pregunta algo que no esta en las recetas proporcionadas, indicale amablemente que no tienes esa receta pero ofrecele alternativas del contexto.
Presta especial atencion a las "Restricciones alimentarias" de las recetas y asegurate de ofrecer opciones que cumplan con la dieta del usuario si la menciona.
Se amigable, entusiasma al usuario con la comida e incluye los enlaces a los videos si estan disponibles."""

    human_prompt = f"""Consulta del usuario: {query}
    
Contexto de recetas encontradas en la base de datos:
{context_text}

Por favor, responde a la consulta recomendando la mejor opcion y dando un resumen de por que es ideal."""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]
    
    try:
        response = llm.invoke(messages)
        return response.content
    except Exception as e:
        return f"Error al generar respuesta con Gemini: {str(e)}"

def main():
    print("Chatbot RAG de Recetas (Gemini + ChromaDB)")
    print("Escribe 'salir' para terminar.")
    
    client = get_chroma_client()
    collection = get_or_create_collection(client)
    llm = get_llm()
    
    while True:
        query = input("\nTu: ")
        if query.lower() in ["salir", "exit", "quit"]:
            break
            
        if not query.strip():
            continue
            
        print("\nPensando... (buscando recetas y generando respuesta)")
        
        # 1. Recuperación (Retrieval)
        results = perform_similarity_search(collection, query, n_results=3)
        
        if not results:
            print("\nChatbot: No encontré recetas relevantes en mi base de datos para esa consulta.")
            continue
            
        # 2. Generación (Generation)
        response = generate_rag_response(llm, query, results)
        
        print(f"\nChatbot:\n{response}")

if __name__ == "__main__":
    main()
