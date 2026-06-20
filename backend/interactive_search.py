from vector_db import get_chroma_client, get_or_create_collection, perform_similarity_search

def print_result(result):
    print(f"\nReceta: {result['nombre']}")
    if result.get('calorias'):
        print(f"Nutricion: {result['calorias']} kcal | Proteina: {result.get('proteina', 0)}g")
    if result.get('tags'):
        print(f"Etiquetas: {result['tags']}")
    if result.get('restricciones'):
        print(f"Apto para: {result['restricciones']}")
    print(f"Similitud: {result['similarity_score']:.2f}")
    if result.get('video_url'):
        print(f"Video: {result['video_url']}")
    print("-" * 40)

def main():
    print("🔍 Búsqueda Interactiva de Recetas (Similitud Semántica)")
    print("Escribe 'salir' para terminar.")
    
    client = get_chroma_client()
    collection = get_or_create_collection(client)
    
    while True:
        query = input("\n¿Qué tipo de comida o ingredientes buscas?: ")
        if query.lower() in ["salir", "exit", "quit"]:
            break
            
        if not query.strip():
            continue
            
        print("Buscando las mejores coincidencias...")
        results = perform_similarity_search(collection, query, n_results=5)
        
        if not results:
            print("No se encontraron resultados.")
        else:
            for i, res in enumerate(results, 1):
                print(f"\n--- Resultado #{i} ---")
                print_result(res)

if __name__ == "__main__":
    main()
