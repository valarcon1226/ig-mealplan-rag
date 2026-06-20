import json

BACKUP_FILE = "recetas_saludables_backup.json"
DB_FILE = "recetas_db.json"
OUTPUT_FILE = "recetas_saludables_consolidadas.json"

def main():
    print(f"Cargando datos de {BACKUP_FILE}...")
    with open(BACKUP_FILE, "r", encoding="utf-8-sig") as f:
        backup_data = json.load(f)
    
    posts = backup_data.get("posts", [])
    print(f"Encontrados {len(posts)} posts originales.")

    print(f"Cargando cálculos de IA de {DB_FILE}...")
    try:
        with open(DB_FILE, "r", encoding="utf-8-sig") as f:
            db_data = json.load(f)
        print(f"Encontrados {len(db_data)} análisis de Gemini.")
    except Exception as e:
        print(f"Error cargando la DB: {e}")
        return

    # Fusionar datos
    merged_count = 0
    for post in posts:
        media_id = post.get("media_id", post.get("id"))
        if media_id in db_data:
            # Agregar los resultados de IA dentro del post original
            post["ai_analysis"] = db_data[media_id]
            merged_count += 1
            
    # Guardar en un nuevo archivo (o podríamos sobreescribir el mismo)
    backup_data["posts"] = posts
    
    # El usuario pidió guardarlo en el mismo lugar, así que sobreescribimos
    # Pero por seguridad creamos una copia o usamos un nombre claro:
    print(f"Fusionados {merged_count} análisis dentro de los posts originales.")
    
    # Sobreescribiendo el original como pidió el usuario: "que se guarden en ese mismo archivo"
    with open(BACKUP_FILE, "w", encoding="utf-8-sig") as f:
        json.dump(backup_data, f, ensure_ascii=False, indent=4)
        
    print(f"¡Listo! Archivo {BACKUP_FILE} actualizado exitosamente con todos los macros e ingredientes de la IA.")

if __name__ == "__main__":
    main()
