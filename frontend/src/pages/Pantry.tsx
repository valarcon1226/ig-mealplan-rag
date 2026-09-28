import { useState, useEffect } from 'react';
import { useStore } from '../lib/store';
import { Trash2, ShoppingCart, Archive, ListChecks, Plus, Loader2 } from 'lucide-react';
import toast from 'react-hot-toast';

export default function Pantry() {
  const { currentMealPlan } = useStore();
  const [subTab, setSubTab] = useState<'inventory' | 'grocery'>('inventory');
  
  return (
    <div className="p-4 max-w-lg mx-auto space-y-6 pt-8 pb-24">
      <header className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight text-white mb-4">Pantry & Groceries</h1>
        <p className="text-neutral-400 text-sm">Manage your inventory and generate smart grocery lists.</p>
      </header>

      <div className="flex bg-neutral-900 rounded-xl p-1 mb-6 border border-neutral-800">
        <button 
          onClick={() => setSubTab('inventory')}
          className={`flex-1 py-2 text-sm font-bold rounded-lg flex items-center justify-center gap-2 transition-colors ${subTab === 'inventory' ? 'bg-neutral-800 text-white' : 'text-neutral-500 hover:text-neutral-300'}`}
        >
          <Archive className="w-4 h-4" />
          Inventory
        </button>
        <button 
          onClick={() => setSubTab('grocery')}
          className={`flex-1 py-2 text-sm font-bold rounded-lg flex items-center justify-center gap-2 transition-colors ${subTab === 'grocery' ? 'bg-neutral-800 text-white' : 'text-neutral-500 hover:text-neutral-300'}`}
        >
          <ShoppingCart className="w-4 h-4" />
          Grocery List
        </button>
      </div>

      {subTab === 'inventory' && <PantryInventory />}
      {subTab === 'grocery' && <GroceryList currentMealPlan={currentMealPlan} />}
    </div>
  );
}

function PantryInventory() {
  const [items, setItems] = useState<any[]>([]);
  const [name, setName] = useState('');
  const [amount, setAmount] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/pantry').then(res => res.json()).then(data => {
      setItems(data);
      setLoading(false);
    });
  }, []);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    const res = await fetch('/api/pantry', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, amount })
    });
    const newItem = await res.json();
    setItems([...items, newItem]);
    setName('');
    setAmount('');
  };

  const handleDelete = async (id: number) => {
    await fetch(`/api/pantry/${id}`, { method: 'DELETE' });
    setItems(items.filter(i => i.id !== id));
  };

  if (loading) return <div className="text-center py-10 text-neutral-500"><Loader2 className="w-8 h-8 animate-spin mx-auto opacity-50" /></div>;

  return (
    <div className="space-y-6">
      <form onSubmit={handleAdd} className="flex gap-2">
        <input 
          type="text" 
          value={name} onChange={e => setName(e.target.value)}
          placeholder="Item (e.g. Rice)" 
          className="flex-1 bg-neutral-900 border border-neutral-800 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-orange-500"
        />
        <input 
          type="text" 
          value={amount} onChange={e => setAmount(e.target.value)}
          placeholder="Qty (e.g. 1 kg)" 
          className="w-1/3 bg-neutral-900 border border-neutral-800 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-orange-500"
        />
        <button type="submit" className="bg-neutral-800 text-white px-4 rounded-lg font-bold hover:bg-neutral-700 transition-colors">
          <Plus className="w-4 h-4" />
        </button>
      </form>

      {items.length === 0 ? (
        <div className="text-center py-10 text-neutral-600">Your pantry is empty.</div>
      ) : (
        <ul className="space-y-2">
          {items.map(item => (
            <li key={item.id} className="flex items-center justify-between bg-neutral-900 border border-neutral-800 p-3 rounded-xl">
              <div>
                <div className="font-bold text-sm text-white">{item.name}</div>
                {item.amount && <div className="text-xs text-neutral-500">{item.amount}</div>}
              </div>
              <button onClick={() => handleDelete(item.id)} className="p-2 text-neutral-600 hover:text-red-500 transition-colors">
                <Trash2 className="w-4 h-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function GroceryList({ currentMealPlan }: { currentMealPlan: any }) {
  const [list, setList] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasGenerated, setHasGenerated] = useState(false);

  const generateList = async () => {
    if (!currentMealPlan) {
      toast.error("No meal plan found. Generate one in the Plan tab first!");
      return;
    }
    
    // Flatten meals. Daily returns { meals: [] }, Weekly returns [ { meals: [] }, ... ]
    let allMeals: any[] = [];
    if (Array.isArray(currentMealPlan)) {
      currentMealPlan.forEach((day: any) => allMeals.push(...day.meals));
    } else if (currentMealPlan.meals) {
      allMeals = currentMealPlan.meals;
    }
    
    if (allMeals.length === 0) {
      toast.error("Your meal plan has no meals.");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch('/api/grocery/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ meals: allMeals })
      });
      const data = await res.json();
      if (data.grocery_list) {
        setList(data.grocery_list);
        setHasGenerated(true);
      } else {
        toast.error("Could not generate list.");
      }
    } catch (e) {
      toast.error("Error connecting to server.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="bg-neutral-900 border border-neutral-800 p-4 rounded-xl text-center">
        <ListChecks className="w-8 h-8 mx-auto text-orange-500 mb-2" />
        <h3 className="font-bold text-white mb-1">Smart Grocery List</h3>
        <p className="text-xs text-neutral-400 mb-4">
          Compares your current active Meal Plan against your Pantry inventory.
        </p>
        <button 
          onClick={generateList}
          disabled={loading || !currentMealPlan}
          className="w-full bg-orange-500 text-black font-bold py-3 rounded-lg flex items-center justify-center gap-2 disabled:opacity-50"
        >
          {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : "Generate List"}
        </button>
      </div>

      {hasGenerated && (
        <div className="space-y-4">
          <h4 className="font-bold text-sm text-neutral-400 uppercase tracking-widest">To Buy</h4>
          {list.length === 0 ? (
            <div className="text-center py-10 text-neutral-500">You have everything you need!</div>
          ) : (
            <ul className="space-y-2">
              {list.map((item, i) => (
                <li key={i} className="flex items-center justify-between bg-neutral-900 border border-neutral-800 p-3 rounded-xl">
                  <div className="flex items-center gap-3">
                    <input 
                      type="checkbox" 
                      className="w-4 h-4 rounded border-neutral-700 text-orange-500 focus:ring-orange-500 bg-neutral-950 accent-orange-500 cursor-pointer"
                      onChange={async (e) => {
                        if (e.target.checked) {
                          try {
                            const res = await fetch('/api/pantry', {
                              method: 'POST',
                              headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({ name: item.item, amount: item.amount })
                            });
                            if (res.ok) {
                              toast.success(`${item.item} added to Pantry!`);
                              e.target.disabled = true; // Disable after adding
                            } else {
                              toast.error("Failed to add to Pantry");
                              e.target.checked = false;
                            }
                          } catch (err) {
                            toast.error("Network error");
                            e.target.checked = false;
                          }
                        }
                      }}
                    />
                    <span className="font-bold text-sm text-white">{item.item}</span>
                  </div>
                  <span className="text-xs font-mono text-orange-500 bg-orange-500/10 px-2 py-1 rounded-md">{item.amount}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
