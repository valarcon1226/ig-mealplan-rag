import toast from 'react-hot-toast';

// Copy / share / print plain text. Used by the grocery list and recipe export.

export async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success('Copied to clipboard');
  } catch {
    toast.error('Could not copy — try Share instead.');
  }
}

// Direct links to apps: desktop share sheets (Windows) often offer only email.
export function shareTargets(title: string, text: string) {
  const t = encodeURIComponent(text);
  return [
    { label: 'WhatsApp', href: `https://wa.me/?text=${t}` },
    { label: 'Telegram', href: `https://t.me/share/url?url=${encodeURIComponent(' ')}&text=${t}` },
    { label: 'Email', href: `mailto:?subject=${encodeURIComponent(title)}&body=${t}` },
  ];
}

export const canNativeShare = () => typeof navigator !== 'undefined' && !!navigator.share;

export async function shareText(title: string, text: string) {
  if (navigator.share) {
    try { await navigator.share({ title, text }); } catch { /* user closed the share sheet */ }
    return;
  }
  // No native share (most desktop browsers): download a small .txt instead.
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
  const filename = title.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-|-$/g, '') || 'export';
  const a = Object.assign(document.createElement('a'), { href: url, download: `${filename}.txt` });
  a.click();
  URL.revokeObjectURL(url);
}

export function printText(title: string, text: string) {
  const win = window.open('', '_blank');
  if (!win) { toast.error('Allow pop-ups to print.'); return; }
  win.document.title = title;
  const pre = win.document.createElement('pre'); // textContent, so names can't inject HTML
  pre.textContent = text;
  pre.style.cssText = 'font: 14px/1.6 system-ui, sans-serif; white-space: pre-wrap;';
  win.document.body.appendChild(pre);
  win.print();
}
