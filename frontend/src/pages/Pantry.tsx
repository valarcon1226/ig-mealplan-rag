import { useState, useEffect } from 'react';
import { useStore } from '../lib/store';
import { Trash2, ShoppingCart, Archive, ListChecks, Plus, Loader2, Receipt, X, Copy, Share2, Printer } from 'lucide-react';
import toast from 'react-hot-toast';
import { copyText, shareText, printText } from '../lib/shareText';

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
      {subTab === 'grocery' && <GroceryList meals={planMeals(currentMealPlan)} />}
    </div>
  );
}

type ScannedItem = { name: string; amount: string };

function PantryInventory() {
  const [items, setItems] = useState<any[]>([]);
  const [text, setText] = useState('');
  const [scanning, setScanning] = useState(false);
  const [scanned, setScanned] = useState<ScannedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const load = async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const res = await fetch('/api/pantry');
      const data = await res.json();
      if (!res.ok || !Array.isArray(data)) throw new Error();
      setItems(data);
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  // amount '' lets the backend parse free text like "1lb de arroz".
  const addItem = async (itemName: string, itemAmount = '') => {
    const res = await fetch('/api/pantry', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: itemName.trim(), amount: itemAmount.trim() })
    });
    const saved = await res.json();
    if (!res.ok) throw new Error(saved.detail || saved.error || 'Could not add item');
    // The backend may merge into an existing row (same id) instead of creating one.
    setItems(prev => prev.some(i => i.id === saved.id)
      ? prev.map(i => i.id === saved.id ? saved : i)
      : [...prev, saved]);
  };

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    try {
      await addItem(text);
      setText('');
    } catch (err: any) {
      toast.error(err.message);
    }
  };

  const handleReceipt = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ''; // allow picking the same file again
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) {
      toast.error('Image is too large (max 10 MB).');
      return;
    }
    setScanning(true);
    try {
      const image = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result as string);
        reader.onerror = () => reject(new Error('Could not read the file'));
        reader.readAsDataURL(file);
      });
      const res = await fetch('/api/pantry/receipt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || data.error || 'Could not read the receipt');
      if (!data.items.length) toast.error('No food items found on that receipt.');
      setScanned(data.items);
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setScanning(false);
    }
  };

  const confirmScanned = async () => {
    const failed: ScannedItem[] = [];
    for (const it of scanned) {
      if (!it.name.trim()) continue;
      try { await addItem(it.name, it.amount); } catch { failed.push(it); }
    }
    setScanned(failed);
    if (failed.length) toast.error(`${failed.length} item(s) could not be added.`);
    else toast.success('Receipt added to your pantry!');
  };

  const updateScanned = (idx: number, field: keyof ScannedItem, value: string) =>
    setScanned(prev => prev.map((it, i) => i === idx ? { ...it, [field]: value } : it));

  const handleDelete = async (id: number) => {
    try {
      const res = await fetch(`/api/pantry/${id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error();
      setItems(prev => prev.filter(i => i.id !== id));
    } catch {
      toast.error("Could not delete item");
    }
  };

  if (loading) return <div className="text-center py-10 text-neutral-500"><Loader2 className="w-8 h-8 animate-spin mx-auto opacity-50" /></div>;

  if (loadError) return (
    <div className="text-center py-10 text-neutral-500 space-y-3">
      <p>Couldn't load your pantry. Is the backend running?</p>
      <button onClick={load} className="bg-neutral-800 text-white px-4 py-2 rounded-lg text-sm font-bold hover:bg-neutral-700">Retry</button>
    </div>
  );

  return (
    <div className="space-y-6">
      <form onSubmit={handleAdd} className="flex gap-2">
        <input
          type="text"
          value={text} onChange={e => setText(e.target.value)}
          placeholder="e.g. 1 lb de arroz, 12 huevos"
          aria-label="Add item with quantity"
          className="flex-1 bg-neutral-900 border border-neutral-800 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-orange-500"
        />
        <button type="submit" aria-label="Add item" className="bg-neutral-800 text-white px-4 rounded-lg font-bold hover:bg-neutral-700 transition-colors">
          <Plus className="w-4 h-4" />
        </button>
      </form>

      <label className={`w-full border border-dashed border-neutral-700 rounded-xl py-3 text-sm font-bold flex items-center justify-center gap-2 transition-colors focus-within:border-orange-500 ${scanning ? 'text-neutral-500' : 'text-neutral-300 hover:border-orange-500 cursor-pointer'}`}>
        {scanning ? <Loader2 className="w-4 h-4 animate-spin" /> : <Receipt className="w-4 h-4" />}
        {scanning ? 'Reading receipt…' : 'Upload receipt'}
        <input type="file" accept="image/*" onChange={handleReceipt} disabled={scanning} className="sr-only" />
      </label>

      {scanned.length > 0 && (
        <div className="bg-neutral-900 border border-orange-500/40 rounded-xl p-3 space-y-2">
          <p className="text-xs text-neutral-400">Review the items from your receipt before adding them:</p>
          {scanned.map((it, i) => (
            <div key={i} className="flex gap-2">
              <input value={it.name} onChange={e => updateScanned(i, 'name', e.target.value)} aria-label="Item name"
                className="flex-1 bg-neutral-950 border border-neutral-800 rounded-lg px-2 py-1 text-sm focus:outline-none focus:border-orange-500" />
              <input value={it.amount} onChange={e => updateScanned(i, 'amount', e.target.value)} aria-label={`Quantity for ${it.name}`}
                className="w-24 bg-neutral-950 border border-neutral-800 rounded-lg px-2 py-1 text-sm focus:outline-none focus:border-orange-500" />
              <button onClick={() => setScanned(prev => prev.filter((_, j) => j !== i))} aria-label={`Remove ${it.name}`} className="p-1 text-neutral-600 hover:text-red-500">
                <X className="w-4 h-4" />
              </button>
            </div>
          ))}
          <div className="flex gap-2 pt-1">
            <button onClick={() => setScanned([])} className="flex-1 bg-neutral-800 text-white py-2 rounded-lg text-sm font-bold hover:bg-neutral-700">Cancel</button>
            <button onClick={confirmScanned} className="flex-1 bg-orange-500 text-black py-2 rounded-lg text-sm font-bold">Add {scanned.length} items</button>
          </div>
        </div>
      )}

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
              <button onClick={() => handleDelete(item.id)} aria-label={`Delete ${item.name}`} className="p-2 text-neutral-600 hover:text-red-500 transition-colors">
                <Trash2 className="w-4 h-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

type GroceryItem = { item: string; amount: string; missing: string; covered: boolean };

// Flatten a plan. Daily returns { meals: [] }, Weekly returns [ { meals: [] }, ... ]
const planMeals = (plan: any): any[] => !plan ? []
  : Array.isArray(plan) ? plan.flatMap((day: any) => day.meals || [])
  : plan.meals || [];

// Checklist of what `meals` need vs. the pantry. Also used per recipe in the Cookbook.
export function GroceryList({ meals: allMeals, title = 'Lista de mercado' }: { meals: any[]; title?: string }) {
  const [list, setList] = useState<GroceryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const mealsKey = JSON.stringify(allMeals); // refetch when the content changes, not the array identity

  // Full list of what the meals need; `covered` comes from the pantry.
  const fetchList = async () => {
    if (allMeals.length === 0) return;
    try {
      const res = await fetch('/api/grocery/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ meals: allMeals })
      });
      const data = await res.json();
      if (!res.ok || !Array.isArray(data.grocery_list)) throw new Error();
      setList(data.grocery_list);
    } catch {
      toast.error("Could not load the grocery list.");
    }
  };

  useEffect(() => {
    setLoading(true);
    fetchList().finally(() => setLoading(false));
  }, [mealsKey]);

  // Check = "I have it / bought it" -> add what's missing to the pantry.
  // Uncheck = "I don't have it" -> remove that ingredient from the pantry.
  const toggle = async (item: GroceryItem) => {
    setBusy(item.item);
    setList(prev => prev.map(i => i.item === item.item ? { ...i, covered: !i.covered } : i));
    try {
      const res = item.covered
        ? await fetch('/api/pantry/remove', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: item.item })
          })
        : await fetch('/api/pantry', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: item.item, amount: item.missing || item.amount })
          });
      if (!res.ok) throw new Error();
    } catch {
      toast.error("Could not update your pantry.");
    } finally {
      await fetchList(); // source of truth is the pantry
      setBusy(null);
    }
  };

  if (allMeals.length === 0) return (
    <div className="bg-neutral-900 border border-neutral-800 p-6 rounded-xl text-center">
      <ListChecks className="w-8 h-8 mx-auto text-orange-500 mb-2" />
      <p className="text-sm text-neutral-400">Generate a meal plan in the Plan tab first and your grocery list will show up here.</p>
    </div>
  );

  if (loading && !list.length) return <div className="text-center py-10 text-neutral-500"><Loader2 className="w-8 h-8 animate-spin mx-auto opacity-50" /></div>;

  const done = list.filter(i => i.covered).length;

  // Plain text that pastes cleanly into WhatsApp/notes and prints fine.
  const exportText = () => {
    const toBuy = list.filter(i => !i.covered);
    const have = list.filter(i => i.covered);
    const line = (i: GroceryItem, qty: string) => `${i.item}${qty ? `: ${qty}` : ''}`;
    return [
      `${title} — ${new Date().toLocaleDateString()}`,
      '',
      `Por comprar (${toBuy.length}):`,
      ...(toBuy.length ? toBuy.map(i => `☐ ${line(i, i.missing && i.missing !== i.amount ? `${i.missing} (de ${i.amount})` : i.amount)}`) : ['(nada, ya tienes todo)']),
      ...(have.length ? ['', `Ya tengo (${have.length}):`, ...have.map(i => `✓ ${line(i, i.amount)}`)] : []),
    ].join('\n');
  };


  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between">
        <div>
          <h4 className="font-bold text-sm text-neutral-400 uppercase tracking-widest">Grocery List</h4>
          <p className="text-xs text-neutral-500 mt-1">Check what you already have or just bought — it goes to your pantry.</p>
        </div>
        <span className="text-xs font-mono text-neutral-400 shrink-0">{done}/{list.length}</span>
      </div>
      <div className="h-1.5 bg-neutral-800 rounded-full overflow-hidden" role="progressbar" aria-valuenow={done} aria-valuemin={0} aria-valuemax={list.length} aria-label="Items covered">
        <div className="h-full bg-orange-500 transition-all" style={{ width: `${list.length ? (done / list.length) * 100 : 0}%` }} />
      </div>

      {list.length > 0 && (
        <div className="grid grid-cols-3 gap-2">
          {[
            { label: 'Copy', icon: Copy, onClick: () => copyText(exportText()) },
            { label: 'Share', icon: Share2, onClick: () => shareText(title, exportText()) },
            { label: 'Print', icon: Printer, onClick: () => printText(title, exportText()) },
          ].map(({ label, icon: Icon, onClick }) => (
            <button key={label} onClick={onClick}
              className="bg-neutral-900 border border-neutral-800 rounded-lg py-2 text-xs font-bold text-neutral-300 flex items-center justify-center gap-1.5 hover:border-orange-500 transition-colors">
              <Icon className="w-3.5 h-3.5" aria-hidden="true" />
              {label}
            </button>
          ))}
        </div>
      )}

      {list.length === 0 ? (
        <div className="text-center py-10 text-neutral-500">Your plan has no ingredients to buy.</div>
      ) : (
        <ul className="space-y-2">
          {list.map(item => {
            const partial = !item.covered && item.missing && item.missing !== item.amount;
            return (
              <li key={item.item}>
                <label className={`flex items-center justify-between gap-3 bg-neutral-900 border border-neutral-800 p-3 rounded-xl cursor-pointer transition-opacity ${item.covered ? 'opacity-50' : ''}`}>
                  <span className="flex items-center gap-3 min-w-0">
                    <input
                      type="checkbox"
                      checked={item.covered}
                      disabled={busy === item.item}
                      onChange={() => toggle(item)}
                      className="w-4 h-4 shrink-0 accent-orange-500 cursor-pointer"
                    />
                    <span className={`font-bold text-sm text-white truncate ${item.covered ? 'line-through' : ''}`}>{item.item}</span>
                  </span>
                  <span className="text-xs font-mono text-orange-500 bg-orange-500/10 px-2 py-1 rounded-md shrink-0">
                    {partial ? `buy ${item.missing} of ${item.amount}` : item.amount}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
