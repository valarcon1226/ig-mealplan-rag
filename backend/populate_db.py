from vector_db import get_chroma_client, load_recipes_data, get_or_create_collection, populate_collection

def main():
    print("Inicializando motor de base de datos vectorial...")
    client = get_chroma_client()
    
    print("Creando/Obteniendo coleccion de recetas...")
    collection = get_or_create_collection(client)
    
    print("Cargando recetas desde el backup...")
    recipes = load_recipes_data()
    
    if not recipes:
        print("No se encontraron recetas. Finalizando.")
        return
        
    print(f"Se cargaran {len(recipes)} recetas validas.")
    
    print("Iniciando el proceso de embedding y carga en ChromaDB...")
    populate_collection(collection, recipes)
    
    print("Proceso finalizado. La base de datos vectorial esta lista.")

if __name__ == "__main__":
    main()
