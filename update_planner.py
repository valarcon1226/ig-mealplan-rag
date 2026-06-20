import os

planner_content = """import { useState } from 'react';
import { useStore } from '../lib/store';
import { Calendar as CalIcon, ShoppingBag, Send, FileDown, Loader2 } from 'lucide-react';

export default function Planner() {
  const { profile, recipes } = useStore();
  const [plan, setPlan] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  
  // Default meals
  const [selectedMeals, setSelectedMeals] = useState<string[]>(['desayuno', 'almuerzo', 'cena']);
  
  const toggleMeal = (meal: string) => {
    if (selectedMeals.includes(meal)) {
      setSelectedMeals(selectedMeals.filter(m => m !== meal));
    } else {
      setSelectedMeals([...selectedMeals, meal]);
    }
  };

  const generatePlan = async () => {
    if (selectedMeals.length === 0) {
      alert("Please select at least one meal.");
      return;
    }
    setLoading(true);
    setShowModal(false);
    try {
      const res = await fetch('/api/mealplan/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dailyGoals: profile.dailyGoals,
          meals: selectedMeals
        })
      });
      const data = await res.json();
      
      if (!res.ok) {
        alert(data.error || "Failed to generate plan");
        setPlan(null);
      } else {
        setPlan(data);
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

  return (
    <div className="p-4 max-w-lg mx-auto space-y-6 pt-8 print:pt-0 pb-20 print:pb-0 relative">
      <header className="mb-8 print:hidden">
        <h1 className="text-3xl font-bold tracking-tight text-white mb-2">Meal Planner</h1>
        <p className="text-neutral-400 text-sm">AI generates your daily plan based on your cookbook and macros.</p>
      </header>

      {showModal && (
        <div className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4">
          <div className="bg-neutral-900 border border-neutral-800 p-6 rounded-2xl w-full max-w-sm space-y-6">
            <h2 className="text-xl font-bold">Select Meals</h2>
            <p className="text-sm text-neutral-400">Which meals do you want to include in today's plan?</p>
            <div className="space-y-2">
              {['desayuno', 'almuerzo', 'snack', 'cena'].map(meal => (
                <label key={meal} className="flex items-center gap-3 p-3 bg-black rounded-lg border border-neutral-800 cursor-pointer">
                  <input 
                    type="checkbox" 
                    checked={selectedMeals.includes(meal)}
                    onChange={() => toggleMeal(meal)}
                    className="w-5 h-5 accent-orange-500"
                  />
                  <span className="capitalize text-white font-medium">{meal}</span>
                </label>
              ))}
            </div>
            <div className="flex gap-3">
              <button onClick={() => setShowModal(false)} className="flex-1 py-3 text-sm font-bold text-neutral-400">Cancel</button>
              <button onClick={generatePlan} className="flex-1 py-3 bg-orange-500 text-black rounded-xl font-bold text-sm">Confirm</button>
            </div>
          </div>
        </div>
      )}

      {!plan ? (
        <div className="bg-neutral-900 border border-neutral-800 rounded-2xl p-8 text-center print:hidden">
          <CalIcon className="w-12 h-12 mx-auto text-orange-500 mb-4" />
          <h2 className="font-bold text-xl mb-2">Ready for the day?</h2>
          <p className="text-sm text-neutral-400 mb-6 pb-6 border-b border-neutral-800">Use your saved recipes to build a balanced, goal-oriented daily meal plan.</p>
          <button
            onClick={() => setShowModal(true)}
            disabled={loading}
            className="w-full bg-orange-500 text-black font-bold py-3 rounded-xl flex items-center justify-center gap-2"
          >
            {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : "Generate Daily Plan"}
          </button>
        </div>
      ) : (
        <div className="space-y-6">
          <div className="flex justify-between items-center print:hidden">
            <h2 className="font-bold text-xl">Today's Perfect Plan</h2>
            <div className="flex gap-2">
              <button onClick={printPdf} className="p-2 border border-neutral-800 rounded-lg hover:bg-neutral-900"><FileDown className="w-4 h-4 text-white" /></button>
            </div>
          </div>
          
          <div className="bg-neutral-900/50 p-4 rounded-xl border border-neutral-800/50">
             <div className="flex justify-between items-center mb-2">
                <span className="text-neutral-400 text-sm">Fitness Score</span>
                <span className="text-orange-500 font-bold">{Math.round(plan.score)}</span>
             </div>
             <div className="grid grid-cols-4 gap-2 text-center text-xs">
                <div className="bg-black p-2 rounded border border-neutral-800"><div className="text-neutral-500 mb-1">Cals</div><div className="font-bold text-orange-400">{Math.round(plan.totals.calorias)}</div></div>
                <div className="bg-black p-2 rounded border border-neutral-800"><div className="text-neutral-500 mb-1">Pro</div><div className="font-bold text-white">{Math.round(plan.totals.proteinas)}g</div></div>
                <div className="bg-black p-2 rounded border border-neutral-800"><div className="text-neutral-500 mb-1">Carb</div><div className="font-bold text-white">{Math.round(plan.totals.carbohidratos)}g</div></div>
                <div className="bg-black p-2 rounded border border-neutral-800"><div className="text-neutral-500 mb-1">Fat</div><div className="font-bold text-white">{Math.round(plan.totals.grasas)}g</div></div>
             </div>
          </div>

          <div className="space-y-4 print:text-black print:bg-white pb-4">
            <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 print:border-gray-300 print:bg-white print:-mx-4">
              <div className="space-y-4">
                {plan.meals.map((meal: any, i: number) => (
                  <div key={i} className="flex gap-3 text-sm">
                    <div className="w-20 shrink-0 text-orange-500 font-bold uppercase text-xs mt-1">{meal.meal_type}</div>
                    <div>
                        <div className="text-white print:text-black font-medium">{meal.nombre}</div>
                        <div className="text-neutral-500 text-xs mt-1">{meal.calorias} kcal · {meal.proteinas}g pro</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
          
          <button
            onClick={() => setShowModal(true)}
            disabled={loading}
            className="w-full bg-neutral-900 border border-neutral-800 py-3 rounded-xl print:hidden flex items-center justify-center gap-2 mt-4 text-xs font-bold text-neutral-400 uppercase tracking-widest"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Regenerate Plan"}
          </button>
        </div>
      )}
    </div>
  );
}
"""

with open('frontend/src/pages/Planner.tsx', 'w', encoding='utf-8') as f:
    f.write(planner_content)
