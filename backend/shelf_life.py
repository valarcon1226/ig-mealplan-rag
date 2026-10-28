"""
shelf_life.py
=============
Cuántos días dura un alimento de la despensa desde que se compró, para que el
plan use primero lo que se va a dañar y no se desperdicie comida.

Valores típicos en nevera (crudo/fresco); lo seco o enlatado dura meses.
ponytail: tabla por palabras clave, primera coincidencia gana; si algo dura
distinto (ej. carne congelada), ajustar la tabla o agregar fecha manual por item.
"""
import re
from datetime import date
from typing import Optional

# (palabras, días). Orden: lo más específico primero ("carne molida" antes que "carne").
SHELF_DAYS = [
    (("molida", "picada"), 2),
    (("pescado", "salmón", "salmon", "atún fresco", "tilapia", "camarón", "camaron", "marisco", "mejillón", "calamar"), 2),
    (("pollo", "pechuga", "muslo", "pavo", "pato"), 2),
    (("jamón", "jamon", "salchicha", "chorizo", "tocino", "bacon", "embutido", "salami"), 7),
    (("carne", "res", "cerdo", "lomo", "cordero", "costilla", "steak", "bistec"), 4),
    (("fresa", "frambuesa", "arándano", "arandano", "mora", "cereza", "uva"), 4),
    (("lechuga", "espinaca", "cilantro", "perejil", "albahaca", "rúcula", "rucula", "kale", "hierba"), 5),
    (("aguacate", "palta", "banano", "banana", "plátano", "platano", "durazno", "mango"), 5),
    (("leche", "crema", "nata", "queso fresco", "requesón", "requeson", "cottage", "ricotta", "burrata", "mozzarella"), 7),
    (("yogur", "yogurt", "kéfir", "kefir"), 14),
    (("pan", "tortilla", "bagel"), 6),
    (("tomate", "pepino", "pimentón", "pimenton", "calabacín", "calabacin", "brócoli", "brocoli", "champiñón", "champinon", "hongo"), 7),
    (("zanahoria", "repollo", "col", "apio", "limón", "limon", "naranja", "manzana", "pera"), 21),
    (("queso",), 30),
    (("huevo",), 30),
    (("papa", "cebolla", "ajo", "batata"), 30),
]
DRY_GOODS_DAYS = 180  # arroz, pasta, avena, harina, azúcar, legumbres secas, enlatados, aceites...


def shelf_days(name: str) -> int:
    n = (name or "").lower()
    # Palabra completa (con plural): "col" no calza en "chocolate" ni "pan" en "panela"; "huevo" sí en "huevos".
    return next((days for words, days in SHELF_DAYS if any(re.search(rf"\b{re.escape(w)}(s|es)?\b", n) for w in words)),
                DRY_GOODS_DAYS)


def days_left(name: str, added_at: Optional[str], today: Optional[date] = None) -> int:
    """Días que le quedan (negativo = ya se pasó). Sin fecha, se cuenta desde hoy."""
    today = today or date.today()
    added = date.fromisoformat(added_at) if added_at else today
    return shelf_days(name) - (today - added).days


if __name__ == "__main__":
    # python shelf_life.py
    assert shelf_days("Carne molida") == 2 and shelf_days("carne de res") == 4
    assert shelf_days("pechuga de pollo") == 2 and shelf_days("arroz") == DRY_GOODS_DAYS
    assert shelf_days("queso parmesano") == 30 and shelf_days("queso cottage") == 7
    assert shelf_days("chocolate") == DRY_GOODS_DAYS and shelf_days("panela") == DRY_GOODS_DAYS
    assert shelf_days("fresas") == 4 and shelf_days("huevos") == 30
    assert days_left("pollo", "2026-10-01", date(2026, 10, 2)) == 1
    assert days_left("pollo", "2026-10-01", date(2026, 10, 5)) == -2
    print("ok")
