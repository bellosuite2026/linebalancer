// Champ numérique borné : la saisie clavier reste libre (on peut effacer puis taper « 15 »),
// la valeur n'est bornée qu'à la sortie du champ (ou Entrée). Évite le champ qui « rebondit »
// quand on borne à chaque frappe.
import { useEffect, useState, type CSSProperties } from "react";

export default function NumField({ value, onChange, min, max, step, style }: {
  value: number; onChange: (v: number) => void; min: number; max: number; step?: number; style?: CSSProperties;
}) {
  const [text, setText] = useState(String(value));
  useEffect(() => { setText(String(value)); }, [value]);
  const commit = () => {
    const n = Number(text.replace(",", "."));
    const v = Number.isFinite(n) && text.trim() !== "" ? Math.max(min, Math.min(max, n)) : value;
    setText(String(v));
    if (v !== value) onChange(v);
  };
  return <input type="number" inputMode="decimal" min={min} max={max} step={step} value={text} style={style}
    onChange={(e) => {
      setText(e.target.value);
      const n = Number(e.target.value);
      // les flèches du champ (ou une valeur déjà dans les bornes) s'appliquent tout de suite
      if (e.target.value !== "" && Number.isFinite(n) && n >= min && n <= max) onChange(n);
    }}
    onBlur={commit}
    onKeyDown={(e) => { if (e.key === "Enter") commit(); }} />;
}
