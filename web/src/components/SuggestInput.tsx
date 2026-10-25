import { useEffect, useRef, useState } from "react";
import type { Suggestion } from "../lib/suggest";

/** Champ texte avec propositions (clavier : ↑ ↓ Entrée Échap). La liste est en position fixe pour ne pas être coupée par le tableau. */
export default function SuggestInput({ value, onChange, onPick, getSuggestions, placeholder, className, onEnterEmpty }: {
  value: string;
  onChange: (v: string) => void;
  onPick: (s: Suggestion) => void;
  getSuggestions: (q: string) => Suggestion[];
  placeholder?: string;
  className?: string;
  onEnterEmpty?: () => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Suggestion[]>([]);
  const [hi, setHi] = useState(0);
  const [pos, setPos] = useState<{ left: number; top: number; width: number } | null>(null);

  const refresh = (q: string) => {
    const list = getSuggestions(q);
    setItems(list); setHi(0); setOpen(list.length > 0);
    const r = ref.current?.getBoundingClientRect();
    if (r) setPos({ left: r.left, top: r.bottom + 2, width: Math.max(r.width, 380) });
  };

  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => { window.removeEventListener("scroll", close, true); window.removeEventListener("resize", close); };
  }, [open]);

  const pick = (s: Suggestion) => { onPick(s); setOpen(false); };

  return (
    <>
      <input ref={ref} className={className} value={value} placeholder={placeholder} autoComplete="off"
        role="combobox" aria-expanded={open} aria-autocomplete="list"
        onChange={(e) => { onChange(e.target.value); refresh(e.target.value); }}
        onFocus={(e) => { if (e.target.value.length >= 2) refresh(e.target.value); }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (open && items.length) {
            if (e.key === "ArrowDown") { e.preventDefault(); setHi((h) => (h + 1) % items.length); return; }
            if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => (h - 1 + items.length) % items.length); return; }
            if (e.key === "Enter" || e.key === "Tab") { if (e.key === "Enter") e.preventDefault(); pick(items[hi]); return; }
            if (e.key === "Escape") { setOpen(false); return; }
          }
          if (e.key === "Enter" && onEnterEmpty) { e.preventDefault(); onEnterEmpty(); }
        }} />
      {open && pos && (
        <ul className="suggest" role="listbox" style={{ left: pos.left, top: pos.top, width: pos.width }}>
          {items.map((s, i) => (
            <li key={s.kind + s.name} role="option" aria-selected={i === hi} className={i === hi ? "on" : ""}
              onMouseDown={(e) => { e.preventDefault(); pick(s); }} onMouseEnter={() => setHi(i)}>
              <span className={`tag ${s.kind}`}>{s.kind === "atelier" ? "Atelier" : "Catalogue"}</span>
              <span className="sname">{s.name}</span>
              <span className="sdetail">{s.detail}{s.machine_type ? ` · ${s.machine_type.replace(/_/g, " ")}` : ""}</span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
