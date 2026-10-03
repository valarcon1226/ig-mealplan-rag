"""
generate_placeholders.py
========================
Genera con Nano Banana (Gemini image) una imagen por categoría de plato. El
Cookbook las usa cuando una receta no tiene foto propia. Se guardan en
frontend/public/placeholders/<slug>.jpg, que Vite sirve tal cual.

Uso (desde backend/):  .\\venv\\Scripts\\python.exe generate_placeholders.py
Salta las que ya existen; borra un .jpg para regenerarlo.

Los slugs deben coincidir con DISH_IMAGES en frontend/src/pages/Cookbook.tsx.
"""
import os

import cv2
import numpy as np
from google import genai

from langchain_pipeline import get_env_var

MODEL = "gemini-3.1-flash-image"
OUT_DIR = os.path.join("..", "frontend", "public", "placeholders")

STYLE = ("Abundant overhead flat lay food photography, square format, all arranged together on a dark "
         "charcoal stone surface, warm soft natural light, appetizing, varied colors and textures. "
         "Only food in dark ceramic dishes, bowls and glasses; the stone surface between them is empty. "
         "No cutlery or utensils of any kind: no spoons, forks, knives or chopsticks, no wooden boards, "
         "no wooden utensils, no napkins. No text, no logos, no people, no hands.")

# Cada imagen muestra varios platos representativos de la categoría.
DISHES = {
    "ensaladas": "Several different salads, each in its own bowl: a leafy green salad with avocado and cherry tomatoes, a Greek salad with feta and olives, a quinoa salad with roasted vegetables, a poke bowl with tuna and edamame, and a caprese with mozzarella and basil",
    "sopas": "Several different soups, each in its own bowl: a creamy orange pumpkin soup, a clear vegetable broth with noodles, a red tomato soup with basil, a ramen bowl with a soft egg and scallions, and a green pea soup",
    "guisos": "Several hearty stews and curries, each in its own bowl: a yellow chicken curry, a beef stew with carrots and potatoes, a red bean chili, and a lentil stew, with a small bowl of white rice",
    "pastas": "Several pasta dishes, each on its own plate: spaghetti with tomato sauce and basil, a slice of lasagna, creamy fettuccine alfredo, penne with green pesto, and gnocchi with butter and sage",
    "arroces": "Several rice and grain dishes, each in its own bowl: a seafood paella, a creamy mushroom risotto, vegetable fried rice, a quinoa bowl, and couscous with herbs",
    "aves": "Several poultry dishes, each on its own plate: golden roast chicken, glazed chicken wings, sliced grilled chicken breast, roast turkey slices, and crispy chicken tenders, garnished with herbs and lemon",
    "carnes": "Several meat dishes, each on its own plate: sliced medium-rare steak, glazed pork ribs, lamb chops, pulled pork, and slices of ham, garnished with rosemary and coarse salt",
    "comida_de_mar": "Several seafood dishes, each on its own plate: a seared salmon fillet, grilled shrimp, steamed mussels, fried calamari rings, a few pieces of sushi, and a small bowl of ceviche, with lemon wedges",
    "snacks": "Several savory snacks, each in its own bowl: crispy golden fries, tortilla chips, popcorn, nachos with melted cheese, and small bowls of guacamole and salsa",
    "verduras": "Several vegetable and legume dishes, each on its own plate: colorful roasted vegetables, hummus with chickpeas, falafel, grilled corn on the cob, a lentil dish, and sauteed broccoli with tofu",
    "comida_rapida": "Several handheld and filled foods, each on its own plate: a cheeseburger, a slice of pizza, a burrito cut in half, a toasted sandwich, soft tacos, and golden empanadas",
    "panes": "Several breads and savory bakes: a rustic sourdough loaf with a few slices, sesame and everything bagels, a rosemary focaccia, a baguette, a slice of quiche, and crackers",
    "desayunos": "Several breakfast dishes, each in its own bowl or plate: overnight oats with sliced banana, yogurt with granola and berries, a stack of pancakes, chia pudding, and fried eggs with avocado toast",
    "postres": "Several desserts, each on its own plate: a slice of chocolate cake, a slice of cheesecake, cookies, brownies, a scoop of ice cream, chocolate mousse in a glass, and energy balls",
    "bebidas": "Several drinks in glasses and cups: a green smoothie, a pink berry smoothie, iced coffee, an iced citrus drink with mint, orange juice, and a cup of hot tea",
    "untables": "Several small bowls and jars of spreads, cheeses and sauces: butter, fruit jam, honey, a selection of cheeses (brie, cream cheese, burrata), green pesto, and dips like aioli and ranch, with a few crackers",
}


def main():
    api_key = get_env_var("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("Falta GEMINI_API_KEY en backend/.env")
    client = genai.Client(api_key=api_key)
    os.makedirs(OUT_DIR, exist_ok=True)

    for slug, dish in DISHES.items():
        path = os.path.join(OUT_DIR, f"{slug}.jpg")
        if os.path.exists(path):
            print(f"ya existe: {slug}")
            continue
        try:
            resp = client.models.generate_content(model=MODEL, contents=f"{dish}. {STYLE}")
            data = next((p.inline_data.data for p in resp.candidates[0].content.parts if p.inline_data), None)
        except Exception as e:
            if "RESOURCE_EXHAUSTED" in str(e):
                # El plan gratuito de Gemini no incluye modelos de imagen: reintentar no sirve.
                raise SystemExit("Sin cuota para el modelo de imagen: activa facturación en la key de Gemini "
                                 "(https://aistudio.google.com/apikey) y vuelve a correrlo.")
            print(f"error {slug}: {e}")
            continue
        if not data:
            print(f"sin imagen: {slug}")
            continue
        # Achica y recomprime: las PNG del modelo pesan ~1-2 MB y esto va al repo.
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        img = cv2.resize(img, (640, 640), interpolation=cv2.INTER_AREA)
        cv2.imwrite(path, img, [cv2.IMWRITE_JPEG_QUALITY, 82])
        print(f"ok: {slug}")


if __name__ == "__main__":
    main()
