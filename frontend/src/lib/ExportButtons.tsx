import { useState } from 'react';
import { Copy, Share2, Printer, Download, MoreHorizontal } from 'lucide-react';
import { copyText, shareText, printText, shareTargets, canNativeShare } from './shareText';

// Copy / Share / Print row used by the recipe detail and the grocery list.
// Share opens explicit app options instead of relying only on the OS share sheet.
export default function ExportButtons({ title, getText }: { title: string; getText: () => string }) {
  const [sharing, setSharing] = useState(false);
  const btn = 'bg-neutral-900 border border-neutral-800 rounded-lg py-2 text-xs font-bold text-neutral-300 flex items-center justify-center gap-1.5 hover:border-orange-500 transition-colors';

  return (
    <div>
      <div className="grid grid-cols-3 gap-2">
        <button onClick={() => copyText(getText())} className={btn}>
          <Copy className="w-3.5 h-3.5" aria-hidden="true" /> Copy
        </button>
        <button onClick={() => setSharing(s => !s)} aria-expanded={sharing} className={`${btn} ${sharing ? 'border-orange-500' : ''}`}>
          <Share2 className="w-3.5 h-3.5" aria-hidden="true" /> Share
        </button>
        <button onClick={() => printText(title, getText())} className={btn}>
          <Printer className="w-3.5 h-3.5" aria-hidden="true" /> Print
        </button>
      </div>

      {sharing && (
        <div className="grid grid-cols-2 gap-2 mt-2" role="group" aria-label="Compartir con">
          {shareTargets(title, getText()).map(t => (
            <a key={t.label} href={t.href} target="_blank" rel="noopener noreferrer" className={btn}>{t.label}</a>
          ))}
          {/* OS share sheet when the browser has one; otherwise download a .txt */}
          <button onClick={() => shareText(title, getText())} className={btn}>
            {canNativeShare()
              ? <><MoreHorizontal className="w-3.5 h-3.5" aria-hidden="true" /> Más opciones</>
              : <><Download className="w-3.5 h-3.5" aria-hidden="true" /> Descargar .txt</>}
          </button>
        </div>
      )}
    </div>
  );
}
