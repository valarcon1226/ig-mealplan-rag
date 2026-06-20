import re

# Fix store.tsx
with open('frontend/src/lib/store.tsx', 'r', encoding='utf-8') as f:
    store_content = f.read()

# Add setAllRecipes to type
store_content = store_content.replace('  recipes: Recipe[];', '  recipes: Recipe[];\n  setAllRecipes: (recipes: Recipe[]) => void;')

# Add setAllRecipes implementation
set_all_impl = """
  const setAllRecipes = (newRecipes: Recipe[]) => {
    setRecipes(newRecipes);
    set('app_recipes', newRecipes);
    triggerSync(profile, newRecipes);
  };

  const addRecipe = (recipe: Recipe) => {"""
store_content = store_content.replace('  const addRecipe = (recipe: Recipe) => {', set_all_impl)

# Add setAllRecipes to provider
store_content = store_content.replace('value={{ recipes, addRecipe,', 'value={{ recipes, setAllRecipes, addRecipe,')

with open('frontend/src/lib/store.tsx', 'w', encoding='utf-8') as f:
    f.write(store_content)

# Fix Cookbook.tsx
with open('frontend/src/pages/Cookbook.tsx', 'r', encoding='utf-8') as f:
    cookbook_content = f.read()

# Add setAllRecipes to useStore destructuring
cookbook_content = cookbook_content.replace('const { recipes, updateDailyConsumption, dailyConsumption, addRecipe, updateRecipe } = useStore();', 'const { recipes, updateDailyConsumption, dailyConsumption, addRecipe, updateRecipe, setAllRecipes } = useStore();')

# Replace the loop with setAllRecipes
loop_code = """          // Add or update recipes
          const currentIds = new Set(recipes.map(r => r.id));
          for (const newRecipe of backendRecipes) {
            if (newRecipe.macros) {
              if (!currentIds.has(newRecipe.id)) {
                addRecipe({ ...newRecipe, id: newRecipe.id || crypto.randomUUID() });
              } else {
                updateRecipe(newRecipe.id, newRecipe);
              }
            }
          }"""

new_code = """          // Instead of looping (which causes closure stale state bugs), 
          // we merge local and backend, and set them all at once.
          const localRecipes = [...recipes];
          const currentIds = new Set(localRecipes.map(r => String(r.id)));
          
          for (const newRecipe of backendRecipes) {
            newRecipe.id = String(newRecipe.id); // Ensure string ID
            if (newRecipe.macros) {
              if (!currentIds.has(newRecipe.id)) {
                localRecipes.push({ ...newRecipe, id: newRecipe.id || crypto.randomUUID() });
              } else {
                const index = localRecipes.findIndex(r => String(r.id) === newRecipe.id);
                localRecipes[index] = { ...localRecipes[index], ...newRecipe };
              }
            }
          }
          setAllRecipes(localRecipes);"""

cookbook_content = cookbook_content.replace(loop_code, new_code)

with open('frontend/src/pages/Cookbook.tsx', 'w', encoding='utf-8') as f:
    f.write(cookbook_content)
