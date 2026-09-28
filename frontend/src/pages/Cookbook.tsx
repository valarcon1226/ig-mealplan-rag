import { useState, useMemo, useEffect } from 'react';
import { useStore } from '../lib/store';
import { Search, Plus } from 'lucide-react';
import { Recipe } from '../lib/types';
import RecipeImport from './RecipeImport';

export default function Cookbook() {
  const { recipes, updateDailyConsumption, dailyConsumption, setAllRecipes } = useStore();
  const [activeTab, setActiveTab] = useState<'recipes' | 'add'>('recipes');
  
  return (
    <div className="p-4 max-w-lg mx-auto space-y-6 pt-8 pb-24">
      <header className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight text-white mb-4">Cookbook</h1>
        <div className="flex bg-neutral-900 rounded-xl p-1 mb-6 border border-neutral-800">
          <button 
            onClick={() => setActiveTab('recipes')}
            className={`flex-1 py-2 text-sm font-bold rounded-lg transition-colors ${activeTab === 'recipes' ? 'bg-neutral-800 text-white' : 'text-neutral-500 hover:text-neutral-300'}`}
          >
            Recipes
          </button>
          <button 
            onClick={() => setActiveTab('add')}
            className={`flex-1 py-2 text-sm font-bold rounded-lg transition-colors ${activeTab === 'add' ? 'bg-neutral-800 text-white' : 'text-neutral-500 hover:text-neutral-300'}`}
          >
            Add Recipe
          </button>
        </div>
      </header>

      {activeTab === 'recipes' && <RecipesTab recipes={recipes} setAllRecipes={setAllRecipes} dailyConsumption={dailyConsumption} updateDailyConsumption={updateDailyConsumption} />}
      {activeTab === 'add' && <RecipeImport />}
    </div>
  );
}

function RecipesTab({ recipes, setAllRecipes, dailyConsumption, updateDailyConsumption }: any) {
  const [search, setSearch] = useState('');
  const [selectedRecipe, setSelectedRecipe] = useState<Recipe | null>(null);
  const [loadingBackend, setLoadingBackend] = useState(false);

  useEffect(() => {
    const fetchRecipes = async () => {
      setLoadingBackend(true);
      try {
        const res = await fetch("/api/recipes", { method: "GET" });
        if (res.ok) {
          const data = await res.json();
          const backendRecipes = Array.isArray(data) ? data : data.recipes || [];
          const localRecipes = [...recipes];
          const currentIds = new Set(localRecipes.map(r => String(r.id)));
          
          for (const newRecipe of backendRecipes) {
            newRecipe.id = String(newRecipe.id);
            if (newRecipe.macros) {
              if (!currentIds.has(newRecipe.id)) {
                localRecipes.push({ ...newRecipe, id: newRecipe.id || crypto.randomUUID() });
              } else {
                const index = localRecipes.findIndex(r => String(r.id) === newRecipe.id);
                localRecipes[index] = { ...localRecipes[index], ...newRecipe };
              }
            }
          }
          setAllRecipes(localRecipes);
        }
      } catch (err) {
        console.error("Error fetching recipes:", err);
      } finally {
        setLoadingBackend(false);
      }
    };
    fetchRecipes();
  }, []);

  const filteredRecipes = useMemo(() => {
    return recipes.filter((r: Recipe) => {
      const matchSearch = r.title.toLowerCase().includes(search.toLowerCase()) || r.categories.some((c: string) => c.toLowerCase().includes(search.toLowerCase()));
      return matchSearch;
    }).sort((a: Recipe, b: Recipe) => (b.createdAt || 0) - (a.createdAt || 0));
  }, [recipes, search]);

  const eatRecipe = (recipe: Recipe) => {
    updateDailyConsumption({
      macros: {
        calories: dailyConsumption.macros.calories + Math.round(recipe.macros.calories / recipe.servings),
        protein: dailyConsumption.macros.protein + Math.round(recipe.macros.protein / recipe.servings),
        carbs: dailyConsumption.macros.carbs + Math.round(recipe.macros.carbs / recipe.servings),
        fat: dailyConsumption.macros.fat + Math.round(recipe.macros.fat / recipe.servings),
        fiber: dailyConsumption.macros.fiber + Math.round(recipe.macros.fiber / recipe.servings),
        sugar: dailyConsumption.macros.sugar + Math.round(recipe.macros.sugar / recipe.servings),
      }
    });
    setSelectedRecipe(null);
  };

  return (
    <>
      <div className="relative mb-6">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-500" />
        <input 
          type="text" 
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search recipes, cravings..." 
          className="w-full bg-neutral-900 border border-neutral-800 text-white rounded-xl py-3 pl-10 pr-4 text-sm focus:outline-none focus:border-orange-500 transition-colors"
        />
      </div>

      {filteredRecipes.length === 0 ? (
        <div className="text-center py-20 text-neutral-500">
          <BookOpenIcon className="w-12 h-12 mx-auto mb-4 opacity-20" />
          <p>No recipes found.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {filteredRecipes.map((recipe: Recipe) => (
            <div 
              key={recipe.id} 
              onClick={() => setSelectedRecipe(recipe)}
              className="bg-neutral-900 border border-neutral-800 rounded-2xl p-4 cursor-pointer hover:border-orange-500/50 transition-colors flex flex-col overflow-hidden relative"
            >
              {(recipe.imageUrl || recipe.thumbnail_url) && (
                <div className="w-full h-32 bg-neutral-800 rounded-xl mb-3 overflow-hidden relative">
                  <img 
                    src={recipe.imageUrl || recipe.thumbnail_url} 
                    alt={recipe.title} 
                    className="w-full h-full object-cover opacity-80"
                    referrerPolicy="no-referrer"
                    onError={(e) => {
                      (e.target as HTMLImageElement).src = 'https://placehold.co/600x400/1a1a1a/4a4a4a?text=No+Image';
                    }}
                  />
                </div>
              )}
              <h3 className="font-bold text-sm leading-tight mb-2">{recipe.title}</h3>

              <div className="flex justify-between items-end mt-auto pt-2 border-t border-neutral-800">
                <div className="text-xs font-mono text-neutral-500">
                  <span className="text-orange-400 font-bold">{recipe.macros.calories}</span> kcal
                </div>
                <div className="text-xs text-neutral-600 bg-neutral-950 px-2 py-1 rounded-md">
                  {recipe.servings} svg
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {selectedRecipe && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-[100] flex items-end sm:items-center justify-center p-4">
          <div className="bg-neutral-950 border border-neutral-800 w-full max-w-md rounded-3xl overflow-hidden shadow-2xl max-h-[90vh] flex flex-col">
            <div className="p-6 overflow-y-auto">
              <div className="flex justify-between items-start mb-6">
                <h2 className="text-2xl font-bold">{selectedRecipe.title}</h2>
                <button onClick={() => setSelectedRecipe(null)} className="text-neutral-500 hover:text-white p-2">✕</button>
              </div>

              {(selectedRecipe.imageUrl || selectedRecipe.thumbnail_url) && (
                <div className="w-full h-48 bg-neutral-900 rounded-xl mb-6 overflow-hidden relative">
                  <img 
                    src={selectedRecipe.imageUrl || selectedRecipe.thumbnail_url} 
                    alt={selectedRecipe.title} 
                    className="w-full h-full object-cover"
                    referrerPolicy="no-referrer"
                    onError={(e) => {
                      (e.target as HTMLImageElement).src = 'https://placehold.co/600x400/1a1a1a/4a4a4a?text=No+Image';
                    }}
                  />
                </div>
              )}

              <div className="grid grid-cols-4 gap-2 mb-8 bg-neutral-900 p-3 rounded-xl border border-neutral-800 text-center text-sm font-mono">
                <div><div className="text-orange-500 font-bold">{selectedRecipe.macros.calories}</div><div className="text-[10px] text-neutral-500">kCal</div></div>
                <div><div className="text-white font-bold">{selectedRecipe.macros.protein}g</div><div className="text-[10px] text-neutral-500">Pro</div></div>
                <div><div className="text-white font-bold">{selectedRecipe.macros.carbs}g</div><div className="text-[10px] text-neutral-500">Carb</div></div>
                <div><div className="text-white font-bold">{selectedRecipe.macros.fat}g</div><div className="text-[10px] text-neutral-500">Fat</div></div>
              </div>

              <h3 className="font-bold text-sm text-neutral-400 uppercase tracking-widest mb-3">Ingredients</h3>
              <ul className="mb-8 space-y-2">
                {selectedRecipe.ingredients.map((ing: any, i: number) => (
                  <li key={i} className="text-sm flex justify-between border-b border-neutral-800/50 pb-2">
                    <span className="text-white">{ing.name}</span>
                    <span className="text-neutral-500">{ing.amount}</span>
                  </li>
                ))}
              </ul>

              <h3 className="font-bold text-sm text-neutral-400 uppercase tracking-widest mb-3">Instructions</h3>
              <ol className="space-y-4 mb-4">
                {selectedRecipe.instructions.map((step: string, i: number) => (
                  <li key={i} className="text-sm text-neutral-300 flex gap-3">
                    <span className="text-orange-500 font-mono font-bold">{i + 1}.</span>
                    <span className="leading-relaxed">{step}</span>
                  </li>
                ))}
              </ol>
            </div>
            
            <div className="p-4 bg-neutral-900 border-t border-neutral-800 shrink-0">
               <button 
                onClick={() => eatRecipe(selectedRecipe)}
                className="w-full bg-orange-500 text-black font-bold py-4 rounded-xl flex items-center justify-center gap-2 shadow-lg shadow-orange-500/20"
              >
                <Plus className="w-5 h-5" />
                Add 1 Serving to Today
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function BookOpenIcon(props: any) {
  return (
    <svg {...props} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
    </svg>
  );
}
