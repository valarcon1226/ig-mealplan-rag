import { useState, useEffect } from 'react';
import { useStore } from '../lib/store';
import { useNavigate } from 'react-router-dom';
import { Sparkles, Image as ImageIcon, Video, Loader2, FolderDown } from 'lucide-react';

export default function RecipeImport() {
  const { addRecipe, profile, recipes, folderPosts, setFolderPosts } = useStore();
  const navigate = useNavigate();
  const [text, setText] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState<'single' | 'bulk'>(folderPosts.length > 0 ? 'bulk' : 'single');
  const [folderName, setFolderName] = useState('');
  const [visibleCount, setVisibleCount] = useState(13);

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

  const [folders, setFolders] = useState<any[]>(profile.igFolders || []);
  
  useEffect(() => {
    if (profile.igFolders) {
        setFolders(profile.igFolders);
    }
  }, [profile.igFolders]);

  const handleFetchFolders = async () => {
    if (!profile.instagramApiKey) {
      setError("Please login to Instagram in the Profile tab first.");
      return;
    }
    setLoading(true);
    setError('');
    setFolders([]);
    try {
      const igCreds = JSON.parse(profile.instagramApiKey || '{}');
      const res = await fetch('/api/collections', { 
        method: 'GET',
        headers: { 
          'X-IG-Username': localStorage.getItem('ig_username') || igCreds.username || '',
          'X-IG-Password': localStorage.getItem('ig_password') || igCreds.password || '',
          'ngrok-skip-browser-warning': 'true'
        }
      });
      const data = await res.json();
      if (Array.isArray(data)) {
        setFolders(data);
      } else if (data.collections) {
         setFolders(data.collections);
      } else if (data.folders) {
         setFolders(data.folders);
      } else {
         throw new Error(data.error || "Server did not return an array of folders or a 'collections' property.");
      }
    } catch (err: any) {
      setError(err.message || 'Error fetching folders.');
    } finally {
      setLoading(false);
    }
  };

  const handleFetchPosts = async () => {
    if (!profile.instagramApiKey) {
      setError('Please connect your Instagram account in the Profile tab first.');
      return;
    }
    if (!folderName.trim()) return setError("Select or enter a folder/collection ID.");
    
    setLoading(true);
    setError('');
    
    try {
      // 1. Fetch saved items from the selected collection
      const igCreds = JSON.parse(profile.instagramApiKey || '{}');
      
      const baseUrl = "/api";
      const url = folderName 
          ? `${baseUrl}/collection-posts?collection_id=${folderName}&since=0`
          : `${baseUrl}/saved-posts?limit=20`;

      const igRes = await fetch(url, {
        method: 'GET',
        headers: { 
          'X-IG-Username': localStorage.getItem('ig_username') || igCreds.username || '',
          'X-IG-Password': localStorage.getItem('ig_password') || igCreds.password || '',
          'ngrok-skip-browser-warning': 'true'
        }
      });
      const igData = await igRes.json();
      
      if (!igRes.ok) throw new Error(igData.error || 'Failed to fetch saved Instagram posts.');
      
      const items = igData.posts || igData.items || [];

      if (items.length === 0) {
        throw new Error('No saved items found in this collection.');
      }

      const normalizedItems = items.map((item: any) => {
        const id = item.id || item.media_id || item.pk;
        return {
          ...item,
          id,
          imageUrl: `/api/static/thumbnails/${id}.png`,
          videoUrl: item.videoUrl || (item.media_type === 'video' ? item.url : null)
        };
      });

      setFolderPosts(normalizedItems);
    } catch (err: any) {
      setError(err.message || 'Error executing Instagram sync.');
    } finally {
      setLoading(false);
    }
  };

  const [postStatus, setPostStatus] = useState<Record<string, "analyzing" | "completed" | "failed">>({});

  const handleAnalyzePost = async (item: any) => {
    setPostStatus(prev => ({ ...prev, [item.id]: 'analyzing' }));
    setError('');
    try {
       const res = await fetch('/api/analyze-langchain-by-id', {
         method: 'POST',
         headers: { 
           'Content-Type': 'application/json',
           'ngrok-skip-browser-warning': 'true'
         },
         body: JSON.stringify({ 
           media_id: item.id || item.media_id || item.pk,
           gemini_api_key: "",
           target_servings: 0,
           x_ig_username: localStorage.getItem('ig_username') || "",
           x_ig_password: localStorage.getItem('ig_password') || ""
         })
       });
       
       if (!res.ok) throw new Error("Failed to analyze.");
       const data = await res.json();
       
       if (data.status === "success" || data.id) {
         setPostStatus(prev => ({ ...prev, [item.id]: 'completed' }));
       } else {
         throw new Error(data.message || "Failed to analyze.");
       }
    } catch (err: any) {
       setError("Error analyzing post: " + err.message);
       setPostStatus(prev => ({ ...prev, [item.id]: 'failed' }));
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
          IG Folder Sync
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
          <div className="bg-neutral-900 border border-neutral-800 rounded-2xl p-6">
            <h2 className="font-bold text-lg mb-4 flex items-center gap-2 text-orange-500">
              <FolderDown className="w-5 h-5" /> Import Options
            </h2>
            <div className="space-y-6">
              <div>
                <div className="flex items-center mb-2">
                   <label className="text-xs font-bold text-neutral-400">Choose your folder</label>
                </div>
                
                {folders.length > 0 ? (
                  <select 
                    value={folderName} 
                    onChange={e => setFolderName(e.target.value)}
                    className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-3 text-sm outline-none text-white focus:border-orange-500 mb-3"
                  >
                    <option value="">Select a folder...</option>
                    {folders.map((f, i) => (
                       <option key={i} value={f.collection_id || f.id || (typeof f === 'string' ? f : f.name)}>{f.name || (typeof f === 'string' ? f : f.id)}</option>
                    ))}
                  </select>
                ) : (
                  <input 
                    type="text" 
                    value={folderName}
                    onChange={e => setFolderName(e.target.value)}
                    placeholder="e.g. Healthy Recipes" 
                    className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-3 text-sm outline-none text-white focus:border-orange-500 mb-3"
                  />
                )}
                
                <button
                  onClick={handleFetchPosts}
                  disabled={loading || !folderName.trim()}
                  className="w-full bg-neutral-800 text-white font-bold py-3 rounded-xl flex items-center justify-center gap-2 transition-transform active:scale-95 disabled:opacity-50 disabled:active:scale-100"
                >
                  {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <FolderDown className="w-4 h-4" />}
                  {loading ? 'Fetching...' : 'Fetch Posts'}
                </button>
              </div>

              {folderPosts.length > 0 && (
                <div className="pt-6 border-t border-neutral-800">
                  <h3 className="font-bold text-white mb-4">Select Posts to Analyze</h3>
                  <div className="space-y-4">
                    {folderPosts.slice(0, visibleCount).map((post: any) => (
                      <div key={post.id} className="bg-neutral-950 border border-neutral-800 p-3 rounded-xl flex gap-4 overflow-hidden">
                        <div className="flex-1 min-w-0 flex flex-col justify-between">
                          <p className="text-xs text-neutral-400 line-clamp-2 leading-relaxed mb-2">{post.caption}</p>
                          <button
                            onClick={() => handleAnalyzePost(post)}
                            disabled={postStatus[post.id] === 'analyzing' || postStatus[post.id] === 'completed' || recipes.some(r => r.media_id === post.id || r.id === post.id)}
                            className={`w-full self-start text-xs font-bold py-2 rounded-lg transition-colors flex items-center gap-2 justify-center border ${
                               (postStatus[post.id] === 'completed' || recipes.some(r => r.media_id === post.id || r.id === post.id))
                               ? 'bg-green-500/10 text-green-500 border-green-500/20' 
                               : postStatus[post.id] === 'failed'
                               ? 'bg-red-500/10 text-red-500 border-red-500/20 hover:bg-red-500/20'
                               : 'bg-orange-500/10 text-orange-500 border-orange-500/20 hover:bg-orange-500/20'
                            }`}
                          >
                            {postStatus[post.id] === 'analyzing' ? <Loader2 className="w-3 h-3 animate-spin"/> : <Sparkles className="w-3 h-3"/>}
                            {postStatus[post.id] === 'analyzing' 
                              ? 'Analyzing...' 
                              : (postStatus[post.id] === 'completed' || recipes.some(r => r.media_id === post.id || r.id === post.id))
                              ? 'Saved' 
                              : postStatus[post.id] === 'failed'
                              ? 'Failed, click to retry'
                              : 'Analyze & Import'
                            }
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                  {visibleCount < folderPosts.length && (
                    <button 
                      onClick={() => setVisibleCount(prev => prev + 13)}
                      className="w-full mt-4 py-3 bg-neutral-900 border border-neutral-800 rounded-xl text-neutral-400 font-bold hover:bg-neutral-800 hover:text-white transition-colors"
                    >
                      Load More ({folderPosts.length - visibleCount} remaining)
                    </button>
                  )}
                </div>
              )}

              <div className="pt-6 border-t border-neutral-800">
                <label className="text-xs font-bold text-neutral-400 block mb-2">Upload Pre-Extracted JSON</label>
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

              <p className="text-[10px] text-neutral-500 leading-relaxed bg-neutral-950 p-3 rounded-lg border border-neutral-800">
                <strong className="text-neutral-300">Note:</strong> Folder sync automatically utilizes your connected account (Profile tab) to fetch videos from the collection. JSON upload skips AI analysis and adds them straight to your cookbook.
              </p>
            </div>
          </div>

          {error && <div className="text-orange-400 text-xs bg-orange-400/10 p-4 rounded-lg border border-orange-500/20 leading-relaxed">{error}</div>}
        </div>
      )}
    </div>
  );
}
