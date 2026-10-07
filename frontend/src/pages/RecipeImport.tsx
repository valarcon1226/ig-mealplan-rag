import SavedExportImport from './SavedExportImport';
import { useState } from 'react';
import { useStore } from '../lib/store';
import { useNavigate } from 'react-router-dom';
import { Sparkles, Image as ImageIcon, Video, Loader2, FolderDown } from 'lucide-react';

export default function RecipeImport() {
  const { addRecipe } = useStore();
  const navigate = useNavigate();
  const [text, setText] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState<'single' | 'bulk'>('single');

  const handleImport = async () => {
    if (!text.trim() && !file) return;
    setLoading(true);
    setError('');
    
    try {
      const formData = new FormData();
      if (text) formData.append('text', text);
      if (file) formData.append('media', file);

      const res = await fetch('/api/analyze-recipe', {
        method: 'POST',
        body: formData
      });
      
      const data = await res.json();
      
      if (!res.ok) throw new Error(data.error || 'Failed to parse recipe');
      
      const newRecipe = {
        ...data,
        id: crypto.randomUUID(),
        createdAt: Date.now()
      };
      
      addRecipe(newRecipe);
      navigate('/cookbook');
    } catch (err: any) {
      setError(err.message || 'Something went wrong');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-4 max-w-lg mx-auto space-y-6 pt-8 pb-24">
      <header className="mb-4">
        <h1 className="text-3xl font-bold tracking-tight text-white mb-2">Import Recipe</h1>
        <p className="text-neutral-400 text-sm">Upload an Instagram video, image, or paste a caption. The AI will extract the macros and ingredients automatically.</p>
      </header>

      <div className="flex bg-neutral-900 rounded-xl p-1 border border-neutral-800">
        <button 
          onClick={() => setActiveTab('single')}
          className={`flex-1 py-2 text-sm font-bold rounded-lg transition-colors ${activeTab === 'single' ? 'bg-neutral-800 text-white' : 'text-neutral-500 hover:text-neutral-300'}`}
        >
          Manual Upload
        </button>
        <button 
          onClick={() => setActiveTab('bulk')}
          className={`flex-1 py-2 text-sm font-bold rounded-lg transition-colors ${activeTab === 'bulk' ? 'bg-neutral-800 text-white' : 'text-neutral-500 hover:text-neutral-300'}`}
        >
          Importar guardados
        </button>
      </div>

      {activeTab === 'single' ? (
        <>
          <div className="bg-neutral-900 border border-neutral-800 rounded-2xl p-4">
            <textarea
              value={text}
              onChange={e => setText(e.target.value)}
              placeholder="Paste recipe text or Instagram post link here..."
              className="w-full h-32 bg-transparent text-white placeholder:text-neutral-600 outline-none resize-none mb-4"
            />

            <div className="pt-4 border-t border-neutral-800 flex flex-col gap-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-neutral-400 uppercase tracking-widest">Video / Image (Optional)</span>
                {file && (
                  <button onClick={() => setFile(null)} className="text-xs text-red-400 font-bold hover:text-red-300">
                    Remove
                  </button>
                )}
              </div>
              
              <label className="flex items-center justify-center gap-2 border-2 border-dashed border-neutral-800 rounded-xl p-4 cursor-pointer hover:border-orange-500/50 transition-colors">
                {file ? (
                  <span className="text-sm text-neutral-300 font-mono truncate max-w-[200px]">{file.name}</span>
                ) : (
                  <div className="flex items-center gap-4 text-neutral-500">
                    <div className="flex items-center gap-1"><Video className="w-4 h-4"/> Video</div>
                    <div className="flex items-center gap-1"><ImageIcon className="w-4 h-4"/> Image</div>
                  </div>
                )}
                <input 
                  type="file" 
                  accept="video/*,image/*" 
                  className="hidden" 
                  onChange={e => setFile(e.target.files?.[0] || null)}
                />
              </label>
              <p className="text-[10px] text-neutral-600 leading-tight">You can upload a downloaded Instagram video directly to analyze its spoken audio, visuals, and text accurately.</p>
            </div>
          </div>

          {error && <div className="text-red-400 text-sm bg-red-400/10 p-3 rounded-lg border border-red-500/20">{error}</div>}

          <button
            onClick={handleImport}
            disabled={loading || (!text.trim() && !file)}
            className="w-full bg-white text-black font-bold py-4 rounded-xl flex items-center justify-center gap-2 transition-transform active:scale-95 disabled:opacity-50 disabled:active:scale-100"
          >
            {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Sparkles className="w-5 h-5" />}
            {loading ? 'Analyzing with AI...' : 'Analyze & Save'}
          </button>
        </>
      ) : (
        <div className="space-y-6">
          <SavedExportImport />

          <div className="bg-neutral-900 border border-neutral-800 rounded-2xl p-6 space-y-3">
            <h2 className="font-bold text-lg flex items-center gap-2 text-orange-500">
              <FolderDown className="w-5 h-5" /> Recetas ya extraídas (JSON)
            </h2>
            <p className="text-xs text-neutral-500">Agrega recetas desde un respaldo JSON del recetario, sin pasar por la IA.</p>
                <label className="flex items-center justify-center gap-2 border-2 border-dashed border-neutral-800 rounded-xl p-4 cursor-pointer hover:border-orange-500/50 transition-colors text-sm text-neutral-400 text-center relative bg-neutral-950">
                  Select Recipes JSON File
                  <input type="file" accept=".json" className="absolute inset-0 opacity-0 cursor-pointer w-full h-full" onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) {
                      const reader = new FileReader();
                      reader.onload = (evt) => {
                        try {
                          const data = JSON.parse(evt.target?.result as string);
                          // Assume it's an array of recipes or a dictionary of recipes
                          const arr = Array.isArray(data) ? data : Object.values(data);
                          let added = 0;
                          arr.forEach((item: any) => {
                             if (item && item.macros) {
                               addRecipe({ ...item, id: item.id || crypto.randomUUID(), createdAt: Date.now() });
                               added++;
                             }
                          });
                          alert(`Successfully imported ${added} extracted recipes!`);
                          navigate('/cookbook');
                        } catch (err) {
                          alert('Error parsing JSON');
                        }
                      }
                      reader.readAsText(file);
                    }
                  }} />
                </label>
          </div>

          {error && <div className="text-orange-400 text-xs bg-orange-400/10 p-4 rounded-lg border border-orange-500/20 leading-relaxed">{error}</div>}
        </div>
      )}
    </div>
  );
}
