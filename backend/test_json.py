import json
with open('recetas_db.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
    print(list(data.values())[0].keys())
    
    # Encontrar una receta con info nutricional
    for k, v in data.items():
        if "nutricion_por_porcion" in v:
            print("FOUND:", v["nutricion_por_porcion"])
            break
