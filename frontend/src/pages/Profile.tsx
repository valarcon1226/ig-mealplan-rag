import React, { useState, useEffect } from 'react';
import { useStore } from '../lib/store';
import { Settings, RefreshCw, UserCircle, ActivitySquare, Link2, Calendar, HeartPulse } from 'lucide-react';
import { calculateMacros, getCyclePhase } from '../lib/macroCalculator';
import DatePicker from 'react-datepicker';
import 'react-datepicker/dist/react-datepicker.css';
import toast from 'react-hot-toast';

export default function Profile() {
  const { profile, updateProfile, loadFromCloud } = useStore();
  const [loading, setLoading] = useState(false);
  const [showStaticDataModal, setShowStaticDataModal] = useState(false);
  const [macroSuccess, setMacroSuccess] = useState(false);
  const [showHealthConnectModal, setShowHealthConnectModal] = useState(false);
  
  const [n8n, setN8n] = useState(profile.n8nWebhookUrl || '');
  const [showIgModal, setShowIgModal] = useState(false);
  const [showIgConnectionModal, setShowIgConnectionModal] = useState(false);
  const [igFolders, setIgFolders] = useState<any[]>([]);
  const [igFoldersLoading, setIgFoldersLoading] = useState(false);
  const [igUsername, setIgUsername] = useState('');
  const [igPassword, setIgPassword] = useState('');
  const [igLoading, setIgLoading] = useState(false);
  const [igError, setIgError] = useState('');
  
  const [showGarminModal, setShowGarminModal] = useState(false);
  const [showGarminConnectionModal, setShowGarminConnectionModal] = useState(false);
  const [garminUser, setGarminUser] = useState('');
  const [garminPassword, setGarminPassword] = useState('');
  const [garminLoading, setGarminLoading] = useState(false);

  const handleProfileChange = (updates: Partial<typeof profile>) => {
    const newProfile = { ...profile, ...updates };
    const newMacros = calculateMacros(newProfile);
    updateProfile({ ...updates, dailyGoals: newMacros });
  };

  const saveN8n = () => {
    updateProfile({ n8nWebhookUrl: n8n });
    toast.success("Saved");
  }

  const handleIgLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setIgError('');
    if (!igUsername) {
      setIgError("Please enter your username");
      return;
    }
    
    setIgLoading(true);
    try {
      // BYPASS: Usar sesión local existente sin validar con el backend
      localStorage.setItem('ig_username', igUsername);
      localStorage.setItem('ig_password', igPassword || 'dummy');
      updateProfile({ instagramApiKey: JSON.stringify({ username: igUsername, password: igPassword || 'dummy' }) });
      await loadFromCloud(igUsername);
      setShowIgModal(false);
    } catch (e) {
       setIgError("Network error. Please try again later.");
    } finally {
      setIgLoading(false);
    }
  };

  const handleGarminLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!garminUser || !garminPassword) return toast.error("Enter Garmin credentials");
    setGarminLoading(true);
    
    try {
      const res = await fetch("/api/garmin/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: garminUser, password: garminPassword })
      });
      const data = await res.json();
      
      if (res.ok && data.success) {
        updateProfile({ 
          garminConnected: true,
          garminCredentials: { user: garminUser, pass: garminPassword, displayName: data.displayName }
        });
        setShowGarminModal(false);
        toast.success(`Connected to Garmin as ${data.displayName}!`);
      } else {
        toast.error(data.error || "Garmin login failed");
      }
    } catch (err: any) {
       toast.error("Error connecting to Garmin");
    } finally {
       setGarminLoading(false);
    }
  };

  const handleFetchFolders = async () => {
    if (!profile.instagramApiKey) return;
    setIgFoldersLoading(true);
    setIgFolders([]);
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
      let fetchedFolders: any[] = [];
      if (Array.isArray(data)) {
        fetchedFolders = data;
      } else if (data.collections) {
         fetchedFolders = data.collections;
      } else if (data.folders) {
         fetchedFolders = data.folders;
      } else {
         throw new Error(data.error || "Webhook did not return correctly.");
      }
      setIgFolders(fetchedFolders);
      updateProfile({ igFolders: fetchedFolders });
      toast.success("Folders synced!");
    } catch (err: any) {
      toast.error(err.message || 'Error fetching folders.');
    } finally {
      setIgFoldersLoading(false);
    }
  };

  const igUserLabel = (() => {
    try {
       const keyData = JSON.parse(profile.instagramApiKey || '{}');
       return keyData.username || 'IG User';
    } catch {
       return profile.instagramApiKey ? 'IG User' : '';
    }
  })();

  return (
    <div className="p-4 max-w-lg mx-auto space-y-8 pt-8 pb-20">
      <header className="flex justify-between items-start mb-2">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-white mb-2">Profile</h1>
          <p className="text-neutral-400 text-sm">Manage your goals and integrations.</p>
        </div>
        <div className="flex flex-col gap-2 items-end">
          <div className="flex gap-2">
            <button 
              onClick={() => setShowHealthConnectModal(true)}
              className="bg-blue-500/10 hover:bg-blue-500/20 text-blue-400 border border-blue-500/20 text-xs font-bold px-3 py-2 rounded-xl transition-colors cursor-pointer flex items-center gap-1.5"
            >
              <HeartPulse className="w-3.5 h-3.5" /> Health Connect
            </button>
            {!profile.instagramApiKey ? (
              <button 
                onClick={() => setShowIgModal(true)}
                className="bg-gradient-to-tr from-pink-500 via-red-500 to-orange-500 text-white text-xs font-bold px-4 py-2 rounded-xl shadow-lg hover:opacity-90 transition-opacity"
              >
                Connect IG
              </button>
            ) : (
              <button 
                onClick={() => setShowIgConnectionModal(true)}
                className="bg-green-500/10 hover:bg-green-500/20 text-green-400 border border-green-500/20 text-xs font-bold px-4 py-2 rounded-xl transition-colors cursor-pointer"
              >
                IG Connected
              </button>
            )}
          </div>
        </div>
      </header>

      {/* IG Modal */}
      {showIgModal && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
          <div className="bg-neutral-900 border border-neutral-800 p-6 rounded-3xl w-full max-w-sm shadow-2xl relative overflow-hidden">
            <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-pink-500 via-red-500 to-orange-500"></div>
            <h3 className="text-xl font-bold mb-4 text-white mt-2">Instagram Login</h3>
            
            <form onSubmit={handleIgLogin} className="space-y-4">
              {igError && (
                <div className="bg-red-500/10 border border-red-500/20 text-red-500 text-xs px-4 py-3 rounded-xl mb-4">
                  {igError}
                </div>
              )}
              <input 
                type="text" 
                value={igUsername}
                onChange={e => setIgUsername(e.target.value)}
                placeholder="Username" 
                className="w-full bg-neutral-950 border border-neutral-800 rounded-xl px-4 py-3 text-sm outline-none text-white focus:border-pink-500 transition-colors"
                required
              />
              <input 
                type="password" 
                value={igPassword}
                onChange={e => setIgPassword(e.target.value)}
                placeholder="Password" 
                className="w-full bg-neutral-950 border border-neutral-800 rounded-xl px-4 py-3 text-sm outline-none text-white focus:border-pink-500 transition-colors"
                required
              />
              
              <div className="flex gap-2 pt-4">
                <button type="button" onClick={() => setShowIgModal(false)} className="flex-1 py-3 bg-neutral-800 hover:bg-neutral-700 rounded-xl text-white text-sm font-bold transition-colors">Cancel</button>
                <button type="submit" disabled={igLoading} className="flex-1 bg-gradient-to-r from-pink-500 to-orange-500 hover:opacity-90 rounded-xl text-white text-sm font-bold transition-opacity">
                  {igLoading ? "Connecting..." : "Login"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* IG Connected Details Modal */}
      {showIgConnectionModal && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
          <div className="bg-neutral-900 border border-neutral-800 p-6 rounded-3xl w-full max-w-sm shadow-2xl relative overflow-hidden">
            {/* Background design */}
            <div className="absolute top-0 left-0 right-0 h-24 bg-gradient-to-r from-pink-500 via-red-500 to-orange-500 opacity-20"></div>

            <div className="relative pt-6 flex flex-col items-center mb-6">
              <div className="w-20 h-20 rounded-full p-1 bg-gradient-to-tr from-yellow-400 via-pink-500 to-blue-500 mb-3">
                <div className="w-full h-full bg-neutral-900 rounded-full flex items-center justify-center overflow-hidden">
                  <UserCircle className="w-12 h-12 text-neutral-500" />
                </div>
              </div>
              <h3 className="text-xl font-bold text-white">{igUserLabel}</h3>
              <p className="text-sm text-neutral-400 flex items-center gap-1 mt-1">
                <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
                Connected
              </p>
            </div>

            <div className="space-y-3">
                <div className="bg-neutral-950 p-4 rounded-xl border border-neutral-800">
                  <div className="flex justify-between items-center mb-2">
                    <p className="text-xs font-bold text-neutral-400 uppercase tracking-wider">Your Folders</p>
                    <button onClick={handleFetchFolders} className="text-xs text-orange-500 font-bold hover:text-orange-400 transition-colors bg-orange-500/10 px-2 py-1 rounded">
                      {igFoldersLoading ? "Syncing..." : "Sync Folders"}
                    </button>
                  </div>
                  {igFoldersLoading ? (
                    <div className="flex justify-center py-4">
                      <RefreshCw className="w-5 h-5 text-neutral-500 animate-spin" />
                    </div>
                  ) : igFolders.length > 0 ? (
                    <ul className="text-sm text-white space-y-2 mt-3 max-h-40 overflow-y-auto pr-2 custom-scrollbar">
                      {igFolders.map((f, i) => (
                        <li key={i} className="flex items-center justify-between p-2 rounded-lg bg-neutral-900/50 border border-neutral-800/50">
                          <span className="font-medium truncate">{typeof f === 'string' ? f : f.name || f.id}</span>
                          {f.media_count !== undefined && (
                            <span className="text-[10px] bg-neutral-800 px-2 py-1 rounded-md text-neutral-400 font-bold">{f.media_count}</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-neutral-500 italic mt-2 py-2 text-center bg-neutral-900/30 rounded-lg">Click sync to fetch folders.</p>
                  )}
                </div>
              
              <div className="flex gap-2 pt-2">
                <button type="button" onClick={() => setShowIgConnectionModal(false)} className="flex-1 py-3 text-white text-sm font-bold bg-neutral-800 rounded-xl hover:bg-neutral-700 transition-colors">Done</button>
                <button 
                  onClick={() => {
                    updateProfile({ instagramApiKey: undefined, igSyncWebhookUrl: undefined, igFolders: undefined });
                    setShowIgConnectionModal(false);
                    setIgFolders([]);
                  }} 
                  className="flex-1 bg-red-500/10 text-red-500 text-sm border border-red-500/20 font-bold rounded-xl py-3 hover:bg-red-500/20 transition-colors"
                >
                  Logout
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Garmin Login Modal */}
      {showGarminModal && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
          <div className="bg-neutral-900 border border-neutral-800 p-6 rounded-2xl w-full max-w-sm">
            <h3 className="text-xl font-bold mb-4 text-white flex items-center gap-2">
              <ActivitySquare className="w-5 h-5 text-blue-400" /> Garmin Connect API
            </h3>
            <form onSubmit={handleGarminLogin} className="space-y-4">
              <input 
                type="email" 
                value={garminUser}
                onChange={e => setGarminUser(e.target.value)}
                placeholder="Garmin Email" 
                className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-3 text-sm outline-none text-white focus:border-blue-500"
              />
              <input 
                type="password" 
                value={garminPassword}
                onChange={e => setGarminPassword(e.target.value)}
                placeholder="Password" 
                className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-3 text-sm outline-none text-white focus:border-blue-500"
              />
              <div className="flex gap-2 pt-2">
                <button type="button" onClick={() => setShowGarminModal(false)} className="flex-1 py-2 text-neutral-400 font-bold">Cancel</button>
                <button type="submit" disabled={garminLoading} className="flex-1 bg-blue-600 text-white font-bold rounded-lg py-2 hover:bg-blue-500 transition-colors">
                  {garminLoading ? "Connecting..." : "Connect"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Garmin Connected Details Modal */}
      {showGarminConnectionModal && profile.garminConnected && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
          <div className="bg-neutral-900 border border-neutral-800 p-6 rounded-3xl w-full max-w-sm shadow-2xl relative overflow-hidden">
            {/* Background design */}
            <div className="absolute top-0 left-0 right-0 h-24 bg-gradient-to-r from-blue-500 via-cyan-500 to-indigo-500 opacity-20"></div>

            <div className="relative pt-6 flex flex-col items-center mb-6">
              <div className="w-20 h-20 rounded-full p-1 bg-gradient-to-tr from-cyan-400 via-blue-500 to-indigo-500 mb-3">
                <div className="w-full h-full bg-neutral-900 rounded-full flex items-center justify-center overflow-hidden">
                  <ActivitySquare className="w-10 h-10 text-neutral-500" />
                </div>
              </div>
              <h3 className="text-xl font-bold text-white">{profile.garminCredentials?.displayName || profile.garminCredentials?.user || 'Garmin User'}</h3>
              <p className="text-sm text-neutral-400 flex items-center gap-1 mt-1">
                <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse"></span>
                Connected
              </p>
            </div>

            <div className="space-y-3">
              <div className="flex gap-2 pt-2">
                <button type="button" onClick={() => setShowGarminConnectionModal(false)} className="flex-1 py-3 text-white text-sm font-bold bg-neutral-800 rounded-xl hover:bg-neutral-700 transition-colors">Done</button>
                <button 
                  onClick={() => {
                    updateProfile({ garminConnected: false, garminCredentials: undefined });
                    setShowGarminConnectionModal(false);
                  }} 
                  className="flex-1 bg-red-500/10 text-red-500 text-sm border border-red-500/20 font-bold rounded-xl py-3 hover:bg-red-500/20 transition-colors"
                >
                  Logout
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Target Macros */}
      <section className="bg-neutral-900 border border-neutral-800 rounded-2xl p-6">
        <div className="flex justify-between items-center mb-4">
          <h2 className="font-bold text-lg flex items-center gap-2"><TargetIcon className="w-5 h-5 text-orange-500" /> Daily Targets</h2>
          <button 
            onClick={() => setShowStaticDataModal(true)}
            className="text-xs bg-neutral-800 hover:bg-neutral-700 text-white px-3 py-1.5 rounded-lg flex items-center gap-1 transition-colors"
          >
            <Settings className="w-3 h-3" /> Datos Estáticos
          </button>
        </div>
        
        <div className="grid grid-cols-2 gap-4 mb-6">
          <div className="space-y-1">
            <label className="text-xs text-neutral-500 uppercase tracking-wider">Current Weight (kg)</label>
            <input 
              type="number" 
              value={profile.currentWeight || ''} 
              onChange={e => handleProfileChange({ currentWeight: parseFloat(e.target.value) || undefined })} 
              className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-sm text-white focus:border-orange-500 outline-none transition-colors" 
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-neutral-500 uppercase tracking-wider">Target Weight (kg)</label>
            <input 
              type="number" 
              value={profile.goalWeight || ''} 
              onChange={e => handleProfileChange({ goalWeight: parseFloat(e.target.value) || undefined })} 
              className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-sm text-white focus:border-orange-500 outline-none transition-colors" 
            />
          </div>
        </div>

        <div className="bg-neutral-950 p-4 rounded-xl border border-neutral-800 shadow-inner">
          <p className="text-xs text-neutral-500 uppercase tracking-wider mb-3 text-center">Calculated Daily Intake</p>
          <div className="grid grid-cols-4 gap-2 text-center">
             <div><div className="text-orange-500 font-bold text-xl">{profile.dailyGoals.calories}</div><div className="text-[10px] text-neutral-500 mt-1">KCAL</div></div>
             <div><div className="text-white font-bold text-xl">{profile.dailyGoals.protein}g</div><div className="text-[10px] text-neutral-500 mt-1">PRO</div></div>
             <div><div className="text-white font-bold text-xl">{profile.dailyGoals.carbs}g</div><div className="text-[10px] text-neutral-500 mt-1">CARB</div></div>
             <div><div className="text-white font-bold text-xl">{profile.dailyGoals.fat}g</div><div className="text-[10px] text-neutral-500 mt-1">FAT</div></div>
          </div>
        </div>
      </section>

      {/* Static Data Modal */}
      {showStaticDataModal && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
          <div className="bg-neutral-900 border border-neutral-800 p-6 rounded-3xl w-full max-w-sm shadow-2xl relative overflow-hidden">
            <div className="absolute top-0 left-0 right-0 h-1 bg-neutral-700"></div>
            <h3 className="text-xl font-bold mb-1 text-white mt-2">Datos Estáticos</h3>
            <p className="text-xs text-neutral-400 mb-6">Información base para calcular tus macros.</p>
            
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label className="text-xs text-neutral-500">Height (cm)</label>
                  <input type="number" value={profile.height || ''} onChange={e => handleProfileChange({ height: parseFloat(e.target.value) || undefined })} className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-sm text-white focus:border-orange-500 outline-none transition-colors" />
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-neutral-500">Age (Years)</label>
                  <input type="number" value={profile.age || ''} onChange={e => handleProfileChange({ age: parseInt(e.target.value) || undefined })} className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-sm text-white focus:border-orange-500 outline-none transition-colors" />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-xs text-neutral-500 block">Gender</label>
                <select value={profile.gender || ''} onChange={e => handleProfileChange({ gender: e.target.value as any })} className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-sm text-white outline-none">
                  <option value="" disabled>Select</option>
                  <option value="male">Male</option>
                  <option value="female">Female</option>
                </select>
              </div>

              <div className="space-y-1">
                <label className="text-xs text-neutral-500 block">Activity Level</label>
                <select value={profile.activityLevel || ''} onChange={e => handleProfileChange({ activityLevel: e.target.value as any })} className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-sm text-white outline-none">
                  <option value="" disabled>Select</option>
                  <option value="sedentary">Sedentary (Little/no exercise)</option>
                  <option value="light">Light (1-3 days/week)</option>
                  <option value="moderate">Moderate (3-5 days/week)</option>
                  <option value="active">Active (6-7 days/week)</option>
                  <option value="very_active">Very Active (Physical job)</option>
                </select>
              </div>

              <div className="space-y-1">
                <label className="text-xs text-neutral-500 block">Goal</label>
                <select 
                  value={profile.goal || ''} 
                  onChange={e => {
                    const newGoal = e.target.value as any;
                    if (profile.isPregnant && newGoal === 'lose') {
                      const confirmDeficit = window.confirm("No es recomendable hacer déficit en embarazo, ¿quieres continuar de todos modos?");
                      if (!confirmDeficit) return;
                    }
                    handleProfileChange({ goal: newGoal });
                  }} 
                  className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-sm text-white outline-none"
                >
                  <option value="" disabled>Select</option>
                  <option value="lose">Lose Weight (Deficit)</option>
                  <option value="maintain">Maintain Weight</option>
                  <option value="gain">Build Muscle (Surplus)</option>
                </select>
              </div>
              
              <button onClick={() => setShowStaticDataModal(false)} className="w-full bg-neutral-800 hover:bg-neutral-700 text-white font-bold py-3 rounded-xl mt-4 transition-colors">
                Done
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Cycle Sync & Pregnancy */}
      <section className="bg-neutral-900 border border-neutral-800 rounded-2xl p-6">
        <div className="flex justify-between items-center mb-4">
          <h2 className="font-bold text-lg flex items-center gap-2">
            <ActivitySquare className="w-5 h-5 text-orange-500" /> 
            {profile.isPregnant ? "Pregnancy Mode" : "Cycle Sync"}
          </h2>
          {profile.gender === 'female' && (
            <label className="flex items-center cursor-pointer relative">
              <input 
                type="checkbox" 
                className="sr-only" 
                checked={profile.isPregnant || false}
                onChange={(e) => {
                   const isPreg = e.target.checked;
                   handleProfileChange({ 
                     isPregnant: isPreg, 
                     goal: isPreg ? 'maintain' : profile.goal 
                   });
                }}
              />
              <div className={`w-10 h-5 rounded-full shadow-inner transition-colors ${profile.isPregnant ? 'bg-orange-500' : 'bg-neutral-800'}`}></div>
              <div className={`absolute left-0.5 top-0.5 bg-white w-4 h-4 rounded-full shadow transition-transform ${profile.isPregnant ? 'translate-x-5' : ''}`}></div>
              <span className="ml-2 text-xs font-bold text-neutral-400">Embarazada</span>
            </label>
          )}
        </div>

        {profile.gender === 'female' ? (
          <>
            {profile.isPregnant ? (
               <div className="space-y-4">
                 <div className="grid grid-cols-2 gap-4">
                   <div>
                     <label className="text-xs font-bold text-neutral-400 block mb-2">Peso Pre-Embarazo (kg)</label>
                     <input 
                       type="number" 
                       value={profile.prePregnancyWeight || profile.currentWeight || ''} 
                       onChange={e => handleProfileChange({ prePregnancyWeight: parseFloat(e.target.value) || undefined })} 
                       className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-3 text-sm text-white focus:border-orange-500 outline-none" 
                     />
                   </div>
                   <div>
                     <label className="text-xs font-bold text-neutral-400 block mb-2">Fecha Probable de Parto</label>
                     <div className="relative">
                       <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                         <Calendar className="h-4 w-4 text-neutral-500" />
                       </div>
                       <DatePicker
                         selected={profile.pregnancyDueDate ? new Date(profile.pregnancyDueDate + 'T12:00:00Z') : null}
                         onChange={(date: Date | null) => {
                           if (date) {
                             const yyyy = date.getFullYear();
                             const mm = String(date.getMonth() + 1).padStart(2, '0');
                             const dd = String(date.getDate()).padStart(2, '0');
                             handleProfileChange({ pregnancyDueDate: `${yyyy}-${mm}-${dd}` });
                           } else {
                              handleProfileChange({ pregnancyDueDate: undefined });
                           }
                         }}
                         dateFormat="yyyy-MM-dd"
                         className="w-full bg-neutral-950 border border-neutral-800 rounded-lg pl-10 pr-3 py-3 text-sm outline-none text-white focus:border-orange-500 cursor-pointer"
                         placeholderText="Due Date"
                         minDate={new Date()}
                       />
                     </div>
                   </div>
                 </div>

                 {profile.pregnancyDueDate && (
                   <div className="bg-orange-500/10 text-orange-400 border border-orange-500/20 p-4 rounded-xl mt-4">
                     <p className="text-xs font-bold uppercase tracking-wider mb-2 flex items-center gap-1">
                       <HeartPulse className="w-4 h-4" /> Alertas Nutricionales Clínicas
                     </p>
                     <ul className="text-xs space-y-2 list-disc pl-4 mt-2">
                       <li><strong>Ácido Fólico:</strong> Toma 400-600mcg diarios.</li>
                       <li><strong>Hierro & Calcio:</strong> Aumenta la ingesta de hierro (27mg) y calcio (1000mg).</li>
                       <li><strong>DHA:</strong> Consume mínimo 200mg de Omega-3 para el desarrollo cerebral.</li>
                       <li className="text-red-400 font-bold">Prohibido crudos (sushi, tartar) y lácteos no pasteurizados.</li>
                       <li>Límite de cafeína: 200mg/día.</li>
                     </ul>
                   </div>
                 )}
               </div>
            ) : (
              <>
                <p className="text-xs text-neutral-400 mb-4 leading-relaxed">Enter the start date of your last period. The AI will adapt your meal plan suggestions based on your current cycle phase.</p>
                <div className="space-y-4">
                  <div>
                    <label className="text-xs font-bold text-neutral-400 block mb-2">Last Period Start Date</label>
                    <div className="relative">
                      <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                        <Calendar className="h-4 w-4 text-neutral-500" />
                      </div>
                      <DatePicker
                        selected={profile.lastPeriodStart ? new Date(profile.lastPeriodStart + 'T12:00:00Z') : null}
                        onChange={(date: Date | null) => {
                          if (date) {
                            const yyyy = date.getFullYear();
                            const mm = String(date.getMonth() + 1).padStart(2, '0');
                            const dd = String(date.getDate()).padStart(2, '0');
                            handleProfileChange({ lastPeriodStart: `${yyyy}-${mm}-${dd}` });
                          } else {
                             handleProfileChange({ lastPeriodStart: undefined });
                          }
                        }}
                        dateFormat="yyyy-MM-dd"
                        className="w-full bg-neutral-950 border border-neutral-800 rounded-lg pl-10 pr-3 py-3 text-sm outline-none text-white focus:border-orange-500 cursor-pointer"
                        placeholderText="Select a date"
                        maxDate={new Date()}
                      />
                    </div>
                  </div>
                  {profile.lastPeriodStart && (
                    (() => {
                      const cycleInfo = getCyclePhase(profile.lastPeriodStart);
                      if (!cycleInfo) return null;
                      
                      return (
                        <div className="space-y-3">
                          <div className="bg-orange-500/10 text-orange-400 border border-orange-500/20 p-3 rounded-lg text-sm flex justify-between items-center">
                            <span><strong>Fase actual:</strong> {cycleInfo.phase} (Día {cycleInfo.day})</span>
                            {cycleInfo.isLate && <span className="text-xs bg-red-500/20 text-red-400 px-2 py-0.5 rounded font-bold">Retraso</span>}
                          </div>
                          {cycleInfo.isLate && (
                            <div className="bg-red-500/10 text-red-400 border border-red-500/20 p-3 rounded-lg text-xs font-bold flex items-center gap-2">
                              <RefreshCw className="w-4 h-4 shrink-0" /> ¡Tu ciclo ha superado los 28 días! Sigues en fase Lútea. Si ya inició tu nuevo ciclo, actualiza la fecha arriba.
                            </div>
                          )}
                        </div>
                      );
                    })()
                  )}
                </div>
              </>
            )}
          </>
        ) : (
          <p className="text-xs text-neutral-400 leading-relaxed bg-neutral-950 p-4 rounded-xl border border-neutral-800">
            Did you know? If you set your gender to <strong>Female</strong> in the "Datos Estáticos" settings, you can unlock our Cycle Sync feature. The AI will adapt your meal plans and nutritional needs based on your menstrual cycle phases.
          </p>
        )}
      </section>

      {/* Health Connect Modal */}
      {showHealthConnectModal && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
          <div className="bg-neutral-900 border border-neutral-800 p-6 rounded-3xl w-full max-w-sm shadow-2xl relative overflow-hidden">
            <div className="absolute top-0 left-0 right-0 h-1 bg-blue-500"></div>
            <h3 className="text-xl font-bold mb-1 text-white mt-2 flex items-center gap-2">
              <HeartPulse className="w-5 h-5 text-blue-500" /> Health Connect
            </h3>
            <p className="text-xs text-neutral-400 mb-6">Connect your fitness apps to automatically sync burned calories.</p>
            
            <div className="space-y-3">
              <button 
                onClick={() => toast("Apple Health connection coming soon!", { icon: '🍎' })}
                className="w-full flex items-center justify-between p-3 rounded-xl bg-neutral-950 border border-neutral-800 hover:border-neutral-700 transition-colors text-left"
              >
                <div className="font-bold text-sm text-white">Apple Health</div>
                <span className="text-xs text-neutral-500 bg-neutral-800 px-2 py-1 rounded">Connect</span>
              </button>

              <button 
                onClick={() => toast("Samsung Health connection coming soon!", { icon: '📱' })}
                className="w-full flex items-center justify-between p-3 rounded-xl bg-neutral-950 border border-neutral-800 hover:border-neutral-700 transition-colors text-left"
              >
                <div className="font-bold text-sm text-white">Samsung Health</div>
                <span className="text-xs text-neutral-500 bg-neutral-800 px-2 py-1 rounded">Connect</span>
              </button>

              <button 
                onClick={() => {
                  setShowHealthConnectModal(false);
                  if (profile.garminConnected) {
                    setShowGarminConnectionModal(true);
                  } else {
                    setShowGarminModal(true);
                  }
                }}
                className={`w-full flex items-center justify-between p-3 rounded-xl border transition-colors text-left ${profile.garminConnected ? 'bg-green-500/10 border-green-500/20' : 'bg-neutral-950 border-neutral-800 hover:border-neutral-700'}`}
              >
                <div className={`font-bold text-sm ${profile.garminConnected ? 'text-green-400' : 'text-white'}`}>Garmin</div>
                <span className={`text-xs px-2 py-1 rounded ${profile.garminConnected ? 'bg-green-500/20 text-green-400' : 'bg-neutral-800 text-neutral-500'}`}>{profile.garminConnected ? "Connected ✓" : "Connect"}</span>
              </button>

              <button 
                onClick={() => toast("Other devices coming soon!", { icon: '⌚' })}
                className="w-full flex items-center justify-between p-3 rounded-xl bg-neutral-950 border border-neutral-800 hover:border-neutral-700 transition-colors text-left"
              >
                <div className="font-bold text-sm text-white">Other Device</div>
                <span className="text-xs text-neutral-500 bg-neutral-800 px-2 py-1 rounded">Connect</span>
              </button>
            </div>

            <button onClick={() => setShowHealthConnectModal(false)} className="w-full bg-neutral-800 hover:bg-neutral-700 text-white font-bold py-3 rounded-xl mt-6 transition-colors text-sm">
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function TargetIcon(props: any) {
  return <svg {...props} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>
}

