import React, { useState } from 'react';
import { useStore } from '../lib/store';

const inputClass = 'w-full bg-neutral-950 border border-neutral-800 rounded-xl px-4 py-3 text-sm outline-none text-white focus:border-orange-500 transition-colors';

export default function Login() {
  const { login, register } = useStore();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      if (mode === 'login') await login(email, password);
      else await register(name, email, password);
    } catch (err: any) {
      setError(err.message || 'No se pudo conectar con el servidor');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-black text-neutral-100 flex items-center justify-center p-4">
      <div className="bg-neutral-900 border border-neutral-800 p-6 rounded-3xl w-full max-w-sm shadow-2xl">
        <h1 className="text-2xl font-bold text-white mb-1">{mode === 'login' ? 'Entrar' : 'Crear cuenta'}</h1>
        <p className="text-xs text-neutral-500 mb-6">Tu recetario, perfil y comidas se guardan en tu cuenta.</p>

        <div className="flex gap-2 mb-6" role="tablist">
          {(['login', 'register'] as const).map(m => (
            <button
              key={m} type="button" role="tab" aria-selected={mode === m}
              onClick={() => { setMode(m); setError(''); }}
              className={`flex-1 py-2 rounded-xl text-sm font-bold transition-colors ${mode === m ? 'bg-orange-500 text-black' : 'bg-neutral-800 text-neutral-300 hover:bg-neutral-700'}`}
            >
              {m === 'login' ? 'Entrar' : 'Crear cuenta'}
            </button>
          ))}
        </div>

        <form onSubmit={submit} className="space-y-4">
          {error && (
            <div role="alert" className="bg-red-500/10 border border-red-500/20 text-red-400 text-xs px-4 py-3 rounded-xl">{error}</div>
          )}
          {mode === 'register' && (
            <label className="block text-xs text-neutral-400 space-y-1">
              <span>Nombre</span>
              <input type="text" autoComplete="name" value={name} onChange={e => setName(e.target.value)} required className={inputClass} />
            </label>
          )}
          <label className="block text-xs text-neutral-400 space-y-1">
            <span>Correo</span>
            <input type="email" autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} required className={inputClass} />
          </label>
          <label className="block text-xs text-neutral-400 space-y-1">
            <span>Contraseña</span>
            <input
              type="password" minLength={8} required value={password} onChange={e => setPassword(e.target.value)}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'} className={inputClass}
            />
          </label>
          <button type="submit" disabled={loading} className="w-full py-3 bg-orange-500 hover:bg-orange-400 disabled:opacity-50 rounded-xl text-black text-sm font-bold transition-colors">
            {loading ? 'Cargando...' : mode === 'login' ? 'Entrar' : 'Crear cuenta'}
          </button>
        </form>
      </div>
    </main>
  );
}
