import { useEffect, useState } from 'react';
import { Archive, Loader2, Upload } from 'lucide-react';

type Summary = {
  total: number;
  por_estado: Record<string, number>;
  colecciones: ({ nombre: string; total: number } & Record<string, number | string>)[];
  leidos?: number;
  nuevos?: number;
};

// Bulk import of saved posts from Instagram's official data export: the app never logs
// into the account (logging in with instagrapi got the account flagged).
export default function SavedExportImport() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [lastImport, setLastImport] = useState<{ leidos: number; nuevos: number } | null>(null);

  useEffect(() => {
    fetch('/api/import/saved')
      .then(r => (r.ok ? r.json() : null))
      .then(d => d && setSummary(d))
      .catch(() => { /* backend down: the upload shows its own error */ });
  }, []);

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    if (file.size > 14 * 1024 * 1024) {
      setError('El archivo es muy grande. Al exportar, elige solo la sección "Guardado".');
      return;
    }
    setError('');
    setUploading(true);
    try {
      const data_base64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '');
        reader.onerror = () => reject(new Error('No se pudo leer el archivo'));
        reader.readAsDataURL(file);
      });
      const res = await fetch('/api/import/instagram-export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: file.name, data_base64 }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || data.error || 'No se pudo importar');
      setSummary(data);
      setLastImport({ leidos: data.leidos, nuevos: data.nuevos });
    } catch (err: any) {
      setError(err.message);
    } finally {
      setUploading(false);
    }
  };

  const pendientes = summary?.por_estado?.pendiente ?? 0;

  return (
    <section className="bg-neutral-900 border border-neutral-800 rounded-2xl p-5 space-y-4">
      <div className="flex items-center gap-2">
        <Archive className="w-5 h-5 text-orange-500" aria-hidden="true" />
        <h2 className="font-bold text-lg">Importar tus guardados de Instagram</h2>
      </div>

      <details className="text-sm text-neutral-400">
        <summary className="cursor-pointer text-neutral-300">Cómo sacar tu exportación (una vez, sin dar tu contraseña)</summary>
        <ol className="list-decimal pl-5 mt-2 space-y-1">
          <li>En Instagram: <b>Centro de cuentas → Tu información y permisos → Descargar tu información</b>.</li>
          <li>Elige <b>solo "Guardado"</b>, formato <b>JSON</b>.</li>
          <li>Cuando Instagram te avise que está lista, descarga el ZIP y súbelo aquí.</li>
        </ol>
      </details>

      <label className={`w-full border border-dashed border-neutral-700 rounded-xl py-4 text-sm font-bold flex items-center justify-center gap-2 transition-colors focus-within:border-orange-500 ${uploading ? 'text-neutral-500' : 'text-neutral-300 hover:border-orange-500 cursor-pointer'}`}>
        {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
        {uploading ? 'Leyendo tus guardados…' : 'Subir exportación (.zip o .json)'}
        <input type="file" accept=".zip,.json,application/zip,application/json" onChange={handleFile} disabled={uploading} className="sr-only" />
      </label>

      {error && <p role="alert" className="text-sm text-red-400">{error}</p>}

      {lastImport && (
        <p role="status" className="text-sm text-green-400">
          Leí {lastImport.leidos} guardados · {lastImport.nuevos} nuevos en la cola.
        </p>
      )}

      {summary && summary.total > 0 && (
        <div className="space-y-2">
          <p className="text-sm text-neutral-400">
            {summary.total} guardados importados · <span className="text-white font-bold">{pendientes}</span> por procesar
            · {summary.por_estado?.en_recetario ?? 0} ya están en tu recetario.
          </p>
          <ul className="divide-y divide-neutral-800 border border-neutral-800 rounded-xl">
            {summary.colecciones.map(c => (
              <li key={c.nombre} className="flex items-center justify-between px-3 py-2 text-sm">
                <span className="text-white truncate">{c.nombre}</span>
                <span className="text-neutral-400 shrink-0 text-xs">
                  {c.total} · <span className="text-orange-400">{(c.pendiente as number) ?? 0} pendientes</span>
                </span>
              </li>
            ))}
          </ul>
          {pendientes > 0 && (
            <p className="text-xs text-neutral-500">
              El procesamiento automático se activa al conectar la API oficial de Instagram (siguiente paso).
            </p>
          )}
        </div>
      )}
    </section>
  );
}
