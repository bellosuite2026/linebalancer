import { useState } from "react";

const split = (s: string) => s.split(/[;,]/).map((x) => x.trim()).filter(Boolean);
const norm = (s: string) => s.trim().toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/\s+/g, "_");

/** Plusieurs compétences par cellule : étiquettes + saisie avec propositions. */
export default function SkillsInput({ value, onChange, options, priority = [], bad, placeholder }: {
  value: string; onChange: (v: string) => void; options: string[]; priority?: string[]; bad?: boolean; placeholder?: string;
}) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number; width: number } | null>(null);
  const chips = split(value);
  const set = (list: string[]) => onChange([...new Set(list)].join(", "));
  const add = (raw: string) => { const s = norm(raw); if (s) set([...chips, s]); setQ(""); };
  const nq = norm(q);
  const pool = [...new Set([...priority, ...options])].filter((o) => !chips.includes(o) && (!nq || norm(o).includes(nq))).slice(0, 8);
  return (
    <div className={`skills-input ${bad ? "bad" : ""}`} onClick={(e) => (e.currentTarget.querySelector("input") as HTMLInputElement)?.focus()}>
      {chips.map((c) => (
        <span key={c} className={`chip ${priority.includes(c) ? "req" : ""}`}>{c}
          <button type="button" title="Retirer" onClick={() => set(chips.filter((x) => x !== c))}>×</button></span>
      ))}
      <input value={q} placeholder={chips.length ? "" : placeholder}
        onFocus={(e) => { const r = (e.currentTarget.parentElement as HTMLElement).getBoundingClientRect(); setPos({ top: r.bottom + 2, left: r.left, width: Math.max(r.width, 200) }); setOpen(true); }} onBlur={() => setTimeout(() => { setOpen(false); if (q.trim()) add(q); }, 150)}
        onChange={(e) => { const v = e.target.value; if (/[;,]$/.test(v)) add(v.slice(0, -1)); else setQ(v); }}
        onKeyDown={(e) => {
          if (e.key === "Enter") { e.preventDefault(); if (q.trim()) add(pool[0] && nq && !options.includes(nq) ? pool[0] : q); }
          if (e.key === "Backspace" && !q && chips.length) set(chips.slice(0, -1));
        }} />
      {open && pool.length > 0 && (
        <div className="skills-pop" style={pos ? { position: "fixed", top: pos.top, left: pos.left, minWidth: pos.width } : undefined}>
          {pool.map((o) => (
            <button type="button" key={o} onMouseDown={(e) => { e.preventDefault(); add(o); }}>
              {o}{priority.includes(o) && <span className="badge small warn">requise</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
