from crewai import Agent, Task, Crew, Process
from pydantic import BaseModel, Field
from typing import List

# ==========================================
# 1. PYDANTIC MODELS FOR STRUCTURED OUTPUTS
# ==========================================

class GroceryItem(BaseModel):
    name: str = Field(description="Name of the grocery item")
    quantity: str = Field(description="Quantity needed (for example, '2 lbs', '1 gallon')")
    category: str = Field(description="Store section (for example, 'Produce', 'Dairy')")

class ShoppingCategory(BaseModel):
    section_name: str = Field(description="Store section (for example, 'Produce', 'Dairy')")
    items: List[GroceryItem] = Field(description="Items in this section")

class GroceryShoppingPlan(BaseModel):
    shopping_sections: List[ShoppingCategory] = Field(description="Organized by store sections")
    shopping_tips: List[str] = Field(description="Money-saving and efficiency tips")

class DailyMealPlan(BaseModel):
    day: int = Field(description="Day number")
    breakfast: str = Field(description="Recipe ID for breakfast")
    lunch: str = Field(description="Recipe ID for lunch")
    dinner: str = Field(description="Recipe ID for dinner")
    snack: str = Field(description="Recipe ID for snack")

class WeeklyMealPlan(BaseModel):
    days: List[DailyMealPlan] = Field(description="7 days of meals")

# ==========================================
# 2. AGENTS
# ==========================================

def create_extractor_agent(llm):
    return Agent(
        role="Extractor & Scraper",
        goal="Extract clean recipe steps, ingredients, and quantities from raw Instagram media text.",
        backstory="An expert culinary reader who can deduce exact measurements and steps from casual cooking videos.",
        tools=[], # In the future we can attach vision tools here
        llm=llm,
        verbose=False
    )

def create_profiling_agent(llm):
    return Agent(
        role="Profiling & Nutritionist",
        goal="Establish strict dietary rules based on the user's static data.",
        backstory="A clinical nutritionist that ensures all meal plans strictly adhere to the user's physical goals, weight targets, and medical allergies.",
        tools=[],
        llm=llm,
        verbose=False
    )

def create_meal_planner_agent(llm):
    return Agent(
        role="Meal Planner",
        goal="Create a perfectly balanced weekly meal plan using available recipes from the Cookbook.",
        backstory="A creative chef that builds diverse weekly menus. Knows how to perfectly divide daily macros into breakfast, lunch, and dinner.",
        tools=[], # ChromaDB integration can be passed here as a tool or via context
        llm=llm,
        verbose=False
    )

def create_shopping_organizer_agent(llm):
    return Agent(
        role="Pantry & Shopping Organizer",
        goal="Organize grocery lists by store sections and subtract items already in the pantry.",
        backstory="A highly organized logistics expert who hates wasting money and knows the grocery store layout perfectly.",
        tools=[],
        llm=llm,
        verbose=False
    )

def create_budget_agent(llm):
    return Agent(
        role="Budget & Pricing Advisor",
        goal="Provide cost estimates for the final grocery list.",
        backstory="A frugal shopper who knows all the supermarket prices and always finds the best deals.",
        tools=[], # Selenium/Scraping tools to be added
        llm=llm,
        verbose=False
    )

# ==========================================
# 3. TASKS
# ==========================================

# We will define the tasks that bind these agents together in a workflow module later.
