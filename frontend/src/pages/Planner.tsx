import { useState } from 'react';
import { useStore } from '../lib/store';
import { Calendar as CalIcon, ShoppingBag, Send, FileDown, Loader2 } from 'lucide-react';

export default function Planner() {
  const { profile, recipes } = useStore();
  const [plan, setPlan] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [n8nStatus, setN8nStatus] = useState<string>('');

  const getCyclePhase = (dateStr?: string) => {
    if (!dateStr) return 'none';
    const start = new Date(dateStr);
    const now = new Date();
    const diffTime = now.getTime() - start.getTime();
    const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
    if (diffDays < 0) return 'none';
    const cycleDay = (diffDays % 28) + 1;
    if (cycleDay >= 1 && cycleDay <= 5) return 'menstrual';
    if (cycleDay >= 6 && cycleDay <= 13) return 'follicular';
    if (cycleDay >= 14 && cycleDay <= 17) return 'ovulation';
    return 'luteal';
  }

  const generatePlan = async () => {
    if (recipes.length === 0) {
      alert("Add some recipes to your cookbook first!");
      return;
    }
    setLoading(true);
    try {
      const res = await fetch('/api/generate-plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          preferences: {
            goals: profile.dailyGoals,
            cyclePhase: getCyclePhase(profile.lastPeriodStart)
          },
          recipes: recipes.map(r => ({ id: r.id, title: r.title, macros: r.macros }))
        })
      });
      const data = await res.json();
      setPlan(data);
    } catch (err) {
      console.error(err);
      alert("Failed to generate plan");
    } finally {
      setLoading(false);
    }
  };

  const sendToN8n = async () => {
    if (!profile.n8nWebhookUrl) {
      alert("Please configure your n8n webhook URL in the Profile tab.");
      return;
    }
    setN8nStatus('Sending...');
    try {
      const res = await fetch('/api/send-webhook', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ webhookUrl: profile.n8nWebhookUrl, data: plan })
      });
      if (res.ok) setN8nStatus('Sent to WhatsApp via n8n!');
      else setN8nStatus('Failed to send.');
    } catch (e) {
      setN8nStatus('Error sending data.');
    }
    setTimeout(() => setN8nStatus(''), 3000);
  };

  const printPdf = () => {
    window.print();
  };

  return (
    <div className="p-4 max-w-lg mx-auto space-y-6 pt-8 print:pt-0 pb-20 print:pb-0">
      <header className="mb-8 print:hidden">
        <h1 className="text-3xl font-bold tracking-tight text-white mb-2">Meal Planner</h1>
        <p className="text-neutral-400 text-sm">AI generates your weekly plan based on your cookbook and macros.</p>
      </header>

      {!plan ? (
        <div className="bg-neutral-900 border border-neutral-800 rounded-2xl p-8 text-center print:hidden">
          <CalIcon className="w-12 h-12 mx-auto text-orange-500 mb-4" />
          <h2 className="font-bold text-xl mb-2">Ready for the week?</h2>
          <p className="text-sm text-neutral-400 mb-6 pb-6 border-b border-neutral-800">Use your saved recipes to build a balanced, goal-oriented meal plan.</p>
          <button
            onClick={generatePlan}
            disabled={loading}
            className="w-full bg-orange-500 text-black font-bold py-3 rounded-xl flex items-center justify-center gap-2"
          >
            {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : "Generate Weekly Plan"}
          </button>
        </div>
      ) : (
        <div className="space-y-6">
          <div className="flex justify-between items-center print:hidden">
            <h2 className="font-bold text-xl">Your Week</h2>
            <div className="flex gap-2">
              <button onClick={printPdf} className="p-2 border border-neutral-800 rounded-lg hover:bg-neutral-900"><FileDown className="w-4 h-4 text-white" /></button>
              <button onClick={sendToN8n} className="p-2 border border-neutral-800 rounded-lg bg-green-500/10 hover:bg-green-500/20"><Send className="w-4 h-4 text-green-500" /></button>
            </div>
          </div>
          {n8nStatus && <p className="text-xs text-green-400">{n8nStatus}</p>}

          <div className="space-y-4 print:text-black print:bg-white pb-4">
            {plan.mealPlan.map((day: any) => (
              <div key={day.day} className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 print:border-gray-300 print:bg-white print:-mx-4">
                <h3 className="font-bold text-orange-500 mb-3">{day.day}</h3>
                <div className="space-y-3">
                  {day.meals.map((meal: any, i: number) => (
                    <div key={i} className="flex gap-3 text-sm">
                      <div className="w-20 shrink-0 text-neutral-500 font-medium">{meal.type}</div>
                      <div className="text-white print:text-black">{meal.suggestion}</div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-5 print:border-gray-300 print:bg-white print:-mx-4">
            <h3 className="font-bold text-white flex items-center gap-2 mb-4 print:text-black"><ShoppingBag className="w-5 h-5" /> Grocery List</h3>
            <ul className="grid grid-cols-2 gap-2 text-sm text-neutral-300 print:text-black">
              {plan.groceryList.map((item: string, i: number) => (
                <li key={i} className="flex gap-2 items-start"><span className="text-orange-500 mt-1">•</span> {item}</li>
              ))}
            </ul>
          </div>
          
          <button
            onClick={generatePlan}
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
