from vector_db import get_chroma_client, get_or_create_collection, perform_filtered_search
from interactive_search import print_result

def get_float_input(prompt: str) -> float:
    while True:
        val = input(prompt).strip()
        if not val:
            return None
        try:
            return float(val)
        except ValueError:
            print("Por favor, ingresa un número válido o deja vacío para omitir.")

def get_int_input(prompt: str) -> int:
    while True:
        val = input(prompt).strip()
        if not val:
            return None
        try:
            return int(val)
        except ValueError:
            print("Por favor, ingresa un número entero válido o deja vacío para omitir.")

def main():
    print("⚙️ Búsqueda Avanzada de Recetas (Filtros + Semántica)")
    print("Escribe 'salir' en la consulta para terminar.")
    
    client = get_chroma_client()
    collection = get_or_create_collection(client)
    
    while True:
        query = input("\n¿Qué buscas? (ej. Cena rápida con pollo): ")
        if query.lower() in ["salir", "exit", "quit"]:
            break
            
        if not query.strip():
            print("La consulta no puede estar vacía.")
            continue
            
        print("\nFiltros opcionales (presiona Enter para saltar):")
        max_calories = get_float_input("- Maximo de calorias por porcion: ")
        min_protein = get_float_input("- Minimo de proteina (g): ")
        max_time = get_int_input("- Tiempo maximo de preparacion (min): ")
        restriccion = input("- Restriccion alimentaria (ej. Vegetariano, Vegano, Sin Gluten) o enter para saltar: ").strip().title()
        if not restriccion:
            restriccion = None
        
        print("\nBuscando aplicando filtros...")
        results = perform_filtered_search(
            collection, 
            query, 
            max_calories=max_calories, 
            min_protein=min_protein, 
            max_time=max_time,
            restriccion=restriccion,
            n_results=5
        )
        
        if not results:
            print("No se encontraron resultados con esos filtros.")
        else:
            for i, res in enumerate(results, 1):
                print(f"\n--- Resultado #{i} ---")
                print_result(res)

if __name__ == "__main__":
    main()
