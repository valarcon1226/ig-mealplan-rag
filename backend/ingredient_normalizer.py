import re

def normalize_ingredient_name(name):
    if not name:
        return None
    
    # Convertir a minúsculas
    name = name.lower().strip()
    
    # Exclusiones absolutas
    exclude_list = ["agua", "sal", "pimienta", "hielo", "agua de cocción de pasta", "agua fría", "sal y pimienta"]
    if name in exclude_list:
        return None
        
    # Reemplazos y limpieza de descripciones
    replacements = {
        "arándanos frescos": "arándanos",
        "arandanos frescos": "arándanos",
        "arandanos": "arándanos",
        "avena en hojuelas": "avena",
        "avena molida": "avena",
        "pechuga de pollo en tiras": "pechuga de pollo",
        "pechugas de pollo": "pechuga de pollo",
        "bananas": "banana",
        "huevos": "huevo",
        "tomates": "tomate",
        "limones": "limón",
        "ajos": "ajo",
        "dientes de ajo": "ajo",
        "cebollas": "cebolla",
        "frescos": "",
        "fresca": "",
        "picado": "",
        "picada": "",
        "machacado": "",
        "machacada": "",
        "rallado": "",
        "en polvo": "",
        "entero": "",
        "entera": "",
        "descremada": "",
        "descremado": "",
        "semidescremada": "",
        "semidescremado": "",
        "deslactosada": "",
        "deslactosado": "",
        "light": "",
    }
    
    for old, new in replacements.items():
        if old in name:
            if new == "":
                name = name.replace(old, "").strip()
            else:
                name = name.replace(old, new).strip()
                
    # Limpiar espacios dobles que puedan haber quedado
    name = re.sub(r'\s+', ' ', name)
    
    if not name or name in exclude_list:
        return None
        
    return name

def parse_amount_str(amount_str):
    """
    Parsea un string como '100 g', '15 ml', '1 pizca'
    Devuelve (float, unit) o (None, original_str)
    """
    if not amount_str:
        return 0.0, ""
        
    amount_str = amount_str.lower().strip()
    match = re.match(r"^([\d\.]+)\s*(.*)$", amount_str)
    if match:
        val_str = match.group(1)
        unit = match.group(2).strip()
        try:
            val = float(val_str)
            return val, unit
        except ValueError:
            return 0.0, amount_str
    
    # Si no tiene números, lo devolvemos como unidad 'al gusto', 'pizca', etc.
    return 0.0, amount_str
