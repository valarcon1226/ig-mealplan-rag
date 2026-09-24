import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useStore } from '../lib/store';
import { Calendar as CalIcon, ShoppingBag, Send, FileDown, Loader2, Plus, ChevronLeft, ChevronRight, ChefHat } from 'lucide-react';
import { Recipe } from '../lib/types';

export default function Planner() {
  const { profile, recipes, updateDailyConsumption, dailyConsumption, setCurrentMealPlan, currentMealPlan } = useStore();
  const [plan, setPlan] = useState<any>(currentMealPlan); // puede ser array o objeto
  const [loading, setLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  
  const [planType, setPlanType] = useState<'daily' | 'weekly'>('daily');
  const [currentDayIndex, setCurrentDayIndex] = useState(0);

  // Selecciones disponibles (con soporte para múltiples snacks)
  const mealOptions = [
    { id: 'desayuno', label: 'Desayuno', query: 'desayuno' },
    { id: 'almuerzo', label: 'Almuerzo', query: 'almuerzo' },
    { id: 'cena', label: 'Cena', query: 'cena' },
    { id: 'snack1', label: 'Snack 1', query: 'snack' },
    { id: 'snack2', label: 'Snack 2', query: 'snack' },
    { id: 'postre', label: 'Postre', query: 'postre' }
  ];

  const [selectedMealIds, setSelectedMealIds] = useState<string[]>(['desayuno', 'almuerzo', 'cena']);
  const [selectedRecipe, setSelectedRecipe] = useState<Recipe | null>(null);

  const toggleMeal = (id: string) => {
    if (selectedMealIds.includes(id)) {
      setSelectedMealIds(selectedMealIds.filter(m => m !== id));
    } else {
      setSelectedMealIds([...selectedMealIds, id]);
    }
  };

  const generatePlan = async () => {
    if (selectedMealIds.length === 0) {
      alert("Please select at least one meal.");
      return;
    }
    
    // Mapear los IDs seleccionados al query que entiende el backend
    const mealsToSend = selectedMealIds.map(id => mealOptions.find(o => o.id === id)?.query || 'snack');

    setLoading(true);
    setShowModal(false);
    try {
      const res = await fetch('/api/mealplan/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dailyGoals: profile.dailyGoals,
          meals: mealsToSend,
          plan_type: planType
        })
      });
      const data = await res.json();
      
      if (!res.ok) {
        alert(data.error || "Failed to generate plan");
        setPlan(null);
        setCurrentMealPlan(null);
      } else {
        setPlan(data);
        setCurrentMealPlan(data);
        setCurrentDayIndex(0);
      }
    } catch (err) {
      console.error(err);
      alert("Failed to generate plan");
    } finally {
      setLoading(false);
    }
  };

  const printPdf = () => {
    window.print();
  };

  const openRecipeDetails = (meal: any) => {
    const recipeToOpen = {
      id: meal.recipe_id,
      title: meal.nombre,
      thumbnail_url: meal.thumbnail_url,
      video_url: meal.video_url,
      ingredients: meal.ingredients || [],
      instructions: meal.instructions || [],
      macros: {
        calories: meal.calorias || 0,
        protein: meal.proteinas || 0,
        carbs: meal.carbohidratos || 0,
        fat: meal.grasas || 0
      },
      servings: 1
    };
    setSelectedRecipe(recipeToOpen as Recipe);
  };

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

  const isWeekly = Array.isArray(plan);
  const currentPlan = isWeekly ? plan[currentDayIndex] : plan;

  return (
    <div className="p-4 max-w-lg mx-auto space-y-6 pt-8 print:pt-0 pb-20 print:pb-0 relative">
      <header className="mb-8 print:hidden">
        <h1 className="text-3xl font-bold tracking-tight text-white mb-2">Meal Planner</h1>
        <p className="text-neutral-400 text-sm">AI generates your plan based on your cookbook and macros.</p>
      </header>

      {showModal && (
        <div className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4">
          <div className="bg-neutral-900 border border-neutral-800 p-6 rounded-2xl w-full max-w-sm space-y-6">
            <h2 className="text-xl font-bold">Generate Plan</h2>
            
            <div className="flex bg-black rounded-lg p-1 border border-neutral-800">
              <button 
                onClick={() => setPlanType('daily')}
                className={`flex-1 py-2 rounded-md text-sm font-bold transition-colors ${planType === 'daily' ? 'bg-orange-500 text-black' : 'text-neutral-400 hover:text-white'}`}
              >
                Daily
              </button>
              <button 
                onClick={() => setPlanType('weekly')}
                className={`flex-1 py-2 rounded-md text-sm font-bold transition-colors ${planType === 'weekly' ? 'bg-orange-500 text-black' : 'text-neutral-400 hover:text-white'}`}
              >
                Weekly (7 Days)
              </button>
            </div>

            <p className="text-sm text-neutral-400">Which meals do you want to include each day?</p>
            <div className="space-y-2 max-h-[40vh] overflow-y-auto">
              {mealOptions.map(option => (
                <label key={option.id} className="flex items-center gap-3 p-3 bg-black rounded-lg border border-neutral-800 cursor-pointer">
                  <input 
                    type="checkbox" 
                    checked={selectedMealIds.includes(option.id)}
                    onChange={() => toggleMeal(option.id)}
                    className="w-5 h-5 accent-orange-500"
                  />
                  <span className="capitalize text-white font-medium">{option.label}</span>
                </label>
              ))}
            </div>
            
            <div className="flex gap-3 pt-2">
              <button onClick={() => setShowModal(false)} className="flex-1 py-3 text-sm font-bold text-neutral-400">Cancel</button>
              <button onClick={generatePlan} className="flex-1 py-3 bg-orange-500 text-black rounded-xl font-bold text-sm">Generate</button>
            </div>
          </div>
        </div>
      )}

      {!plan ? (
        <div className="bg-neutral-900 border border-neutral-800 rounded-2xl p-8 text-center print:hidden">
          <CalIcon className="w-12 h-12 mx-auto text-orange-500 mb-4" />
          <h2 className="font-bold text-xl mb-2">Ready for the day?</h2>
          <p className="text-sm text-neutral-400 mb-6 pb-6 border-b border-neutral-800">Use your saved recipes to build a balanced, goal-oriented meal plan.</p>
          <button
            onClick={() => setShowModal(true)}
            disabled={loading}
            className="w-full bg-orange-500 text-black font-bold py-3 rounded-xl flex items-center justify-center gap-2"
          >
            {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : "Generate New Plan"}
          </button>
        </div>
      ) : (
        <div className="space-y-6">
          <div className="flex justify-between items-center print:hidden">
            <h2 className="font-bold text-xl">
              {isWeekly ? `Weekly Plan` : `Today's Plan`}
            </h2>
            <div className="flex gap-2">
              <button onClick={printPdf} className="p-2 border border-neutral-800 rounded-lg hover:bg-neutral-900 text-neutral-400 hover:text-white"><FileDown className="w-4 h-4" /></button>
            </div>
          </div>
          
          {isWeekly && (
            <div className="flex items-center justify-between bg-black rounded-xl border border-neutral-800 p-2 print:hidden">
              <button 
                onClick={() => setCurrentDayIndex(prev => Math.max(0, prev - 1))}
                disabled={currentDayIndex === 0}
                className="p-2 rounded-lg text-neutral-400 hover:text-white hover:bg-neutral-900 disabled:opacity-30"
              >
                <ChevronLeft className="w-5 h-5" />
              </button>
              <span className="font-bold text-white uppercase tracking-wider text-sm">
                {["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"][currentDayIndex] || `Day ${currentDayIndex + 1}`}
              </span>
              <button 
                onClick={() => setCurrentDayIndex(prev => Math.min(plan.length - 1, prev + 1))}
                disabled={currentDayIndex === plan.length - 1}
                className="p-2 rounded-lg text-neutral-400 hover:text-white hover:bg-neutral-900 disabled:opacity-30"
              >
                <ChevronRight className="w-5 h-5" />
              </button>
            </div>
          )}

          {currentPlan && (
            <>
              <div className="bg-neutral-900/50 p-4 rounded-xl border border-neutral-800/50">
                <div className="flex justify-between items-center mb-2">
                    <span className="text-neutral-400 text-sm">Fitness Score (Day {currentPlan.day || 1})</span>
                    <span className="text-orange-500 font-bold">{Math.round(currentPlan.score)}</span>
                </div>
                <div className="grid grid-cols-4 gap-2 text-center text-xs">
                    <div className="bg-black p-2 rounded border border-neutral-800"><div className="text-neutral-500 mb-1">Cals</div><div className="font-bold text-orange-400">{Math.round(currentPlan.totals.calorias)}</div></div>
                    <div className="bg-black p-2 rounded border border-neutral-800"><div className="text-neutral-500 mb-1">Pro</div><div className="font-bold text-white">{Math.round(currentPlan.totals.proteinas)}g</div></div>
                    <div className="bg-black p-2 rounded border border-neutral-800"><div className="text-neutral-500 mb-1">Carb</div><div className="font-bold text-white">{Math.round(currentPlan.totals.carbohidratos)}g</div></div>
                    <div className="bg-black p-2 rounded border border-neutral-800"><div className="text-neutral-500 mb-1">Fat</div><div className="font-bold text-white">{Math.round(currentPlan.totals.grasas)}g</div></div>
                </div>
              </div>

              <div className="space-y-4 print:text-black print:bg-white pb-4">
                <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 print:border-gray-300 print:bg-white print:-mx-4">
                  <div className="space-y-4">
                    {currentPlan.meals.map((meal: any, i: number) => (
                      <div 
                        key={i} 
                        onClick={() => openRecipeDetails(meal)}
                        className="flex gap-3 text-sm p-2 rounded-lg hover:bg-neutral-800 transition-colors cursor-pointer group"
                      >
                        <div className="w-20 shrink-0 text-orange-500 font-bold uppercase text-xs mt-1">{meal.meal_type}</div>
                        <div>
                            <div className="text-white group-hover:text-orange-400 transition-colors print:text-black font-medium">{meal.nombre}</div>
                            <div className="text-neutral-500 text-xs mt-1">{meal.calorias} kcal · {meal.proteinas}g pro</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </>
          )}

          <Link
            to="/mealprep"
            className="w-full bg-neutral-900 border border-orange-500/40 py-3 rounded-xl flex items-center justify-center gap-2 mt-4 text-xs font-bold text-orange-400 uppercase tracking-widest"
          >
            <ChefHat className="w-4 h-4" /> Mealprep
          </Link>

          <button
            onClick={() => setShowModal(true)}
            disabled={loading}
            className="w-full bg-neutral-900 border border-neutral-800 py-3 rounded-xl print:hidden flex items-center justify-center gap-2 mt-4 text-xs font-bold text-neutral-400 uppercase tracking-widest"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Regenerate Plan"}
          </button>
        </div>
      )}

      {/* MODAL DE RECETA SELECCIONADA */}
      {selectedRecipe && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-[100] flex items-end sm:items-center justify-center p-4">
          <div className="bg-neutral-950 border border-neutral-800 w-full max-w-md rounded-3xl overflow-hidden shadow-2xl max-h-[90vh] flex flex-col">
            <div className="p-6 overflow-y-auto">
              <div className="flex justify-between items-start mb-6">
                <h2 className="text-2xl font-bold text-white">{selectedRecipe.title}</h2>
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
                <div><div className="text-orange-500 font-bold">{selectedRecipe.macros?.calories || 0}</div><div className="text-[10px] text-neutral-500">kCal</div></div>
                <div><div className="text-white font-bold">{selectedRecipe.macros?.protein || 0}g</div><div className="text-[10px] text-neutral-500">Pro</div></div>
                <div><div className="text-white font-bold">{selectedRecipe.macros?.carbs || 0}g</div><div className="text-[10px] text-neutral-500">Carb</div></div>
                <div><div className="text-white font-bold">{selectedRecipe.macros?.fat || 0}g</div><div className="text-[10px] text-neutral-500">Fat</div></div>
              </div>

              <h3 className="font-bold text-sm text-neutral-400 uppercase tracking-widest mb-3">Ingredients</h3>
              <ul className="mb-8 space-y-2">
                {selectedRecipe.ingredients?.map((ing, i) => (
                  <li key={i} className="text-sm flex justify-between border-b border-neutral-800/50 pb-2">
                    <span className="text-white">{ing.name}</span>
                    <span className="text-neutral-500">{ing.amount}</span>
                  </li>
                ))}
              </ul>

              <h3 className="font-bold text-sm text-neutral-400 uppercase tracking-widest mb-3">Instructions</h3>
              <ol className="space-y-4 mb-4">
                {selectedRecipe.instructions?.map((step, i) => (
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

    </div>
  );
}
