from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Date
from sqlalchemy.orm import relationship
import datetime
from database import Base

class Food(Base):
    """
    Concepto abstracto de un alimento (ej. Leche, Pollo)
    """
    __tablename__ = "foods"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    plural_name = Column(String, nullable=True)

    # Relaciones
    ingredients = relationship("Ingredient", back_populates="food")
    inventory_entries = relationship("InventoryEntry", back_populates="food")

class Unit(Base):
    """
    Unidad de medida (ej. Taza, Gramo, Mililitro)
    """
    __tablename__ = "units"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    plural_name = Column(String, nullable=True)

    # Relaciones
    ingredients = relationship("Ingredient", back_populates="unit")

class UnitConversion(Base):
    """
    Conversión entre unidades (ej. 1 Taza = 240 ml)
    """
    __tablename__ = "unit_conversions"

    id = Column(Integer, primary_key=True, index=True)
    base_amount = Column(Float, nullable=False)
    base_unit_id = Column(Integer, ForeignKey("units.id"), nullable=False)
    converted_amount = Column(Float, nullable=False)
    converted_unit_id = Column(Integer, ForeignKey("units.id"), nullable=False)
    food_id = Column(Integer, ForeignKey("foods.id"), nullable=True) # Específico a un alimento (ej. 1 taza de harina != 1 taza de agua)

class NutritionInformation(Base):
    """
    Información nutricional de SparkyFitness
    """
    __tablename__ = "nutrition_information"

    id = Column(Integer, primary_key=True, index=True)
    fats = Column(Float, default=0.0)
    carbohydrates = Column(Float, default=0.0)
    proteins = Column(Float, default=0.0)
    calories = Column(Float, default=0.0)
    sugars = Column(Float, default=0.0, nullable=True)
    fiber = Column(Float, default=0.0, nullable=True)

    # Relación uno-a-uno con Recipe
    recipe = relationship("Recipe", back_populates="nutrition", uselist=False)

class Recipe(Base):
    """
    Receta descargada de Instagram o creada manual
    """
    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True, index=True)
    media_id = Column(String, unique=True, index=True) # ID de Instagram
    nombre = Column(String, index=True)
    caption = Column(String, nullable=True)
    video_url = Column(String, nullable=True)
    thumbnail_url = Column(String, nullable=True)
    tiempo_preparacion_min = Column(Integer, nullable=True)
    servings = Column(Integer, default=1)
    tags = Column(String, nullable=True) # Comma-separated tags
    instructions = Column(String, nullable=True) # JSON list of strings
    ingredients_raw = Column(String, nullable=True) # JSON string of ingredients
    cuisine_type = Column(String, nullable=True) # ej. "italiana", "mexicana", "asiática"
    dificultad = Column(String, nullable=True) # "facil" | "media" | "dificil"
    
    nutrition_id = Column(Integer, ForeignKey("nutrition_information.id"), nullable=True)
    nutrition = relationship("NutritionInformation", back_populates="recipe")

    ingredients = relationship("Ingredient", back_populates="recipe", cascade="all, delete-orphan")
    meal_plans = relationship("MealPlan", back_populates="recipe")

class Ingredient(Base):
    """
    Ingrediente en una receta (Cantidad + Unidad + Alimento)
    """
    __tablename__ = "ingredients"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    food_id = Column(Integer, ForeignKey("foods.id"), nullable=True)
    unit_id = Column(Integer, ForeignKey("units.id"), nullable=True)
    
    amount = Column(Float, default=0.0)
    note = Column(String, nullable=True)
    original_text = Column(String, nullable=True) # Texto original ("2 tazas de leche deslactosada")

    recipe = relationship("Recipe", back_populates="ingredients")
    food = relationship("Food", back_populates="ingredients")
    unit = relationship("Unit", back_populates="ingredients")

class MealPlan(Base):
    """
    Plan de Comidas (Asigna Receta a Fecha y Porciones)
    """
    __tablename__ = "meal_plans"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    servings = Column(Float, default=1.0)
    target_date = Column(Date, default=datetime.date.today)
    meal_type = Column(String) # Desayuno, Almuerzo, Cena, Snack
    note = Column(String, nullable=True)

    recipe = relationship("Recipe", back_populates="meal_plans")

class ShoppingList(Base):
    """
    Lista de Compras
    """
    __tablename__ = "shopping_lists"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    entries = relationship("ShoppingListEntry", back_populates="shopping_list", cascade="all, delete-orphan")

class ShoppingListEntry(Base):
    """
    Elemento en la Lista de Compras
    """
    __tablename__ = "shopping_list_entries"

    id = Column(Integer, primary_key=True, index=True)
    shopping_list_id = Column(Integer, ForeignKey("shopping_lists.id"), nullable=False)
    food_id = Column(Integer, ForeignKey("foods.id"), nullable=False)
    unit_id = Column(Integer, ForeignKey("units.id"), nullable=True)
    
    amount = Column(Float, default=0.0)
    checked = Column(Boolean, default=False)
    
    shopping_list = relationship("ShoppingList", back_populates="entries")
    food = relationship("Food")
    unit = relationship("Unit")

class InventoryEntry(Base):
    """
    Pantry/Despensa (Lo que hay en casa)
    """
    __tablename__ = "inventory_entries"

    id = Column(Integer, primary_key=True, index=True)
    food_id = Column(Integer, ForeignKey("foods.id"), nullable=False)
    unit_id = Column(Integer, ForeignKey("units.id"), nullable=True)
    
    amount = Column(Float, default=0.0)
    expires_at = Column(Date, nullable=True)
    
    food = relationship("Food", back_populates="inventory_entries")
    unit = relationship("Unit")

class CollectionSyncState(Base):
    """
    Cuándo se sincronizó por última vez cada carpeta (colección) guardada
    de Instagram. Se usa para no volver a pedirle datos a Instagram si ya
    se sincronizó hace poco (TTL), y así reducir consumo/riesgo de rate
    limit o challenges de seguridad.
    """
    __tablename__ = "collection_sync_state"

    id = Column(Integer, primary_key=True, index=True)
    collection_id = Column(String, unique=True, index=True, nullable=False)
    collection_name = Column(String, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    posts_synced = Column(Integer, default=0)


class PantryItem(Base):
    """
    Elemento en la Despensa (Pantry), texto libre
    """
    __tablename__ = "pantry_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    amount = Column(String, nullable=True)
