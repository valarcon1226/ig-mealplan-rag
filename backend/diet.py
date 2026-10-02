"""
diet.py
=======
Qué restricciones de dieta CUMPLE una receta, inferido de tags, ingredientes y
azúcar por porción. Es la fuente única para el planner (metadata
"restricciones" en Chroma) y el Cookbook (/api/recipes -> "diet").

Se equivoca hacia el lado seguro: ante la duda (ej. "harina" sin decir de qué)
la receta NO se marca como apta. Las palabras se buscan como palabras
completas: antes "res" (carne) coincidía con "fresas".
"""
import re
from typing import Iterable, List, Optional

DIET_LABELS = ["Vegetariano", "Vegano", "Sin Gluten", "Sin Lácteos", "Sin Frutos Secos", "Sin Mariscos", "Apto Diabético"]

# Máximo de azúcar por porción para "Apto Diabético".
# ponytail: umbral fijo; si hace falta, pasar a carga glucémica o carbohidratos netos.
DIABETIC_MAX_SUGAR_G = 10

_PLANT_MILK = r"(?! de (?:almendras?|coco|avena|soya|soja|arroz|anacardos?|marañón|cacahuate|man[ií]))"
# Español + inglés: muchas recetas vienen de videos en inglés ("beef chuck", "cotija cheese").
_PATTERNS = {
    "carne": r"pollo|carne|res|ternera|cerdo|tocino|bacon|beicon|jam[oó]n|salchichas?|chorizos?|salami|pepperoni|malvaviscos?|marshmallows?|"
             r"pavo|cordero|pato|chistorra|lomo|costillas?|pechugas?|muslos?|alitas?|carnitas|gelatina|caldo de (?:pollo|res|carne)|"
             r"beef|chicken|pork|turkey|ham|sausages?|steak|meat|prosciutto|lamb|duck|brisket|ribs|gelatin|"
             r"chicken (?:breasts?|thighs|wings)|ground beef|soup dumplings|xiao ?long ?bao",
    "pescado": r"pescado|at[uú]n|salm[oó]n|tilapia|bacalao|merluza|sardinas?|anchoas?|trucha|"
               r"fish|tuna|salmon|cod|anchov(?:y|ies)|sardines?",
    "marisco": r"camar[oó]n(?:es)?|langostinos?|mariscos?|pulpo|calamar(?:es)?|mejill[oó]n(?:es)?|almejas?|cangrejo|surimi|langosta|ostras?|"
               r"shrimps?|prawns?|crab|lobster|clams?|mussels?|squid|oysters?|scallops?",
    "lacteo": rf"queso|leche{_PLANT_MILK}|mantequilla(?! de (?:man[ií]|cacahuate|almendras?))|yog[uo]rt?h?|crema(?! de (?:man[ií]|cacahuate|almendras?|coco))|"
              r"suero|ghee|nata|reques[oó]n|k[eé]fir|labneh|burrata|mozzarella|parmesano|ricotta|cottage|whey|"
              r"cheese|cheddar|parmesan|feta|brie|gouda|provolone|buttermilk|"
              r"(?<!coconut )(?<!almond )(?<!oat )(?<!soy )(?<!rice )milk|(?<!peanut )(?<!almond )(?<!cashew )butter|(?<!coconut )cream",
    "huevo_miel": r"huevos?|claras?|yemas?|miel|mayonesa|eggs?|egg whites?|honey|mayo|mayonnaise",
    "gluten": r"harina(?! de (?:almendras?|coco|arroz|ma[ií]z|avena sin gluten|garbanzo))|trigo|pan|panko|pasta|espaguetis?|"
              r"fideos|macarrones|tortillas? de harina|galletas?|cebada|centeno|cusc[uú]s|seit[aá]n|cerveza|sémola|semola|"
              r"gnocchi|ñoquis|lasa[ñn]a|rigatoni|penne|ravioli|brioche|bizcocho|croissant|salsa de soya|salsa de soja|"
              r"(?<!almond )(?<!coconut )(?<!rice )(?<!oat )(?<!corn )flour|bread|breadcrumbs|wheat|noodles|spaghetti|"
              r"crackers|(?<!corn )tortillas?|buns?|dough|pita|naan|graham|oreos?|cookies?|biscuits?|beer|barley|rye|"
              r"croutons|soy sauce|dumplings?|wontons?|wrappers?|envoltorios|envolturas|gyozas?|empanadas?|tempura",
    "frutos_secos": r"almendras?|nuez|nueces|man[ií]|cacahuates?|avellanas?|pistachos?|anacardos?|marañ[oó]n|pecanas?|macadamias?|pi[ñn]ones|"
                    r"almonds?|walnuts?|peanuts?|cashews?|pecans?|pistachios?|hazelnuts?|pine nuts|nuts?",
}
_COMPILED = {k: re.compile(rf"\b(?:{v})\b", re.I) for k, v in _PATTERNS.items()}


def _has(kind: str, texts: Iterable[str]) -> bool:
    return any(_COMPILED[kind].search(t or "") for t in texts)


def diet_labels(tags: Iterable[str], ingredient_names: Iterable[str], sugar_g: Optional[float]) -> List[str]:
    """Etiquetas de DIET_LABELS que la receta cumple."""
    tags = {t.strip().lower() for t in tags or []}
    names = [n for n in ingredient_names or [] if n]
    meat, fish, seafood = _has("carne", names), _has("pescado", names), _has("marisco", names)
    dairy, egg_honey = _has("lacteo", names), _has("huevo_miel", names)

    labels = set()
    if "vegano" in tags or not (meat or fish or seafood or dairy or egg_honey):
        labels |= {"Vegano", "Vegetariano"}
    if "vegetariano" in tags or not (meat or fish or seafood):
        labels.add("Vegetariano")
    if "sin gluten" in tags or not _has("gluten", names):
        labels.add("Sin Gluten")
    if {"sin lacteos", "sin lácteos"} & tags or not dairy:
        labels.add("Sin Lácteos")
    if not _has("frutos_secos", names):
        labels.add("Sin Frutos Secos")
    if not seafood:
        labels.add("Sin Mariscos")
    if sugar_g is not None and sugar_g <= DIABETIC_MAX_SUGAR_G:
        labels.add("Apto Diabético")
    return [l for l in DIET_LABELS if l in labels]


def avoids(texts: Iterable[str], disliked: Iterable[str]) -> bool:
    """True si ningún ingrediente/nombre contiene algo de la lista 'no me gusta / alergias'."""
    blob = " ".join(t for t in texts if t).lower()
    return not any(d.strip().lower() and re.search(rf"\b{re.escape(d.strip().lower())}", blob) for d in disliked or [])


if __name__ == "__main__":
    assert "Vegetariano" in diet_labels([], ["Fresas", "Azúcar"], 20)  # "res" ya no coincide con "fresas"
    assert "Vegetariano" not in diet_labels([], ["Pechuga de pollo"], 0)
    assert "Vegetariano" not in diet_labels([], ["chorizos", "miel"], 0)
    v = diet_labels([], ["Leche de almendras", "Avena", "Plátano"], 8)
    assert {"Vegano", "Sin Lácteos", "Apto Diabético"} <= set(v) and "Sin Frutos Secos" not in v, v
    assert "Vegano" not in diet_labels([], ["Yogur griego"], 5)
    assert "Sin Lácteos" not in diet_labels([], ["Queso cottage"], 5)
    assert "Sin Gluten" not in diet_labels([], ["Harina"], 5)
    assert "Sin Gluten" in diet_labels([], ["Harina de almendra"], 5)
    assert "Sin Lácteos" in diet_labels([], ["Mantequilla de maní"], 5)
    assert "Apto Diabético" not in diet_labels([], ["Arroz"], None)  # azúcar desconocida: no se asume
    assert "Sin Mariscos" not in diet_labels([], ["Camarones"], 1)
    tostadas = diet_labels([], ["beef chuck", "cotija cheese", "honey", "tostadas"], 8)
    assert "Vegetariano" not in tostadas and "Sin Lácteos" not in tostadas, tostadas
    assert "Sin Lácteos" in diet_labels([], ["peanut butter", "almond milk"], 5)
    assert "Sin Gluten" in diet_labels([], ["corn tortillas", "almond flour"], 5)
    assert "Sin Gluten" not in diet_labels([], ["all-purpose flour"], 5)
    sd = diet_labels([], ["soup dumplings congelados", "salsa de maní picante"], 3)
    assert not {"Vegano", "Sin Gluten", "Sin Frutos Secos"} & set(sd), sd
    assert avoids(["Pollo", "Arroz"], ["cilantro"]) and not avoids(["Cilantro fresco"], ["cilantro"])
    assert avoids(["Pollo"], ["", " "])
    print("ok")
