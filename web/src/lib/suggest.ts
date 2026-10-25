// Saisie intelligente des opérations : historique de l'atelier + catalogue de temps publiés.
import { supabase } from "./supabase";

export interface CatalogEntry {
  id: string;
  nom: string;
  vetements: string[];
  section: string;
  machine: string;
  sam: { min: number; med: number; max: number; n: number };
  sources: number[];
}
export interface Catalog { version: string; sources: { id: number; titre: string; url: string }[]; operations: CatalogEntry[] }

export interface HistoryEntry {
  name: string;
  count: number;
  duration: number; // médiane des temps saisis par l'atelier
  machine_type: string;
  section: string;
  skills: string;
}

export interface Suggestion {
  kind: "atelier" | "catalogue";
  name: string;
  duration: number;
  machine_type: string;
  section: string;
  skills: string;
  detail: string; // texte court affiché sous la proposition
  range?: [number, number];
  score: number;
}

export const GARMENTS: { value: string; label: string }[] = [
  { value: "", label: "Tous vêtements" },
  { value: "chemise", label: "Chemise / chemisier" },
  { value: "pantalon", label: "Pantalon / jean / short" },
  { value: "maille", label: "T-shirt, polo, sweat (maille)" },
  { value: "veste", label: "Veste / blouson / manteau" },
  { value: "robe", label: "Robe, jupe, top" },
  { value: "travail", label: "Vêtement de travail / blouse" },
];
// Famille de vêtement → valeurs « vetements » du catalogue
const FAMILY: Record<string, string[]> = {
  chemise: ["chemise", "chemisier"],
  pantalon: ["pantalon", "jean", "short", "cargo"],
  maille: ["t-shirt", "polo", "sweat", "jogging", "debardeur", "leggings", "sous-vetement"],
  veste: ["veste", "blazer", "blouson", "parka", "gilet"],
  robe: ["robe", "jupe", "top", "combinaison", "chemisier"],
  travail: ["blouse-travail", "cargo", "veste", "pantalon"],
};

export const norm = (s: string) =>
  s.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[œ]/g, "oe").replace(/[^a-z0-9]+/g, " ").trim();

// Mots de même sens dans les ateliers (tous normalisés). Un mot tapé qui commence comme l'un d'eux
// cherche aussi les autres.
const SYNONYMS: string[][] = [
  ["ourler", "ourlet", "rempli", "remplier"],
  ["assembler", "fermer", "joindre", "unir", "piquer"],
  ["monter", "poser", "attacher", "fixer", "coudre"],
  ["surpiquer", "surpiqure", "nervure", "nervurer", "rabattre", "rabattu"],
  ["surjeter", "surjet", "surfiler", "surfilage", "surjeteuse"],
  ["recouvrir", "recouvreuse", "recouvrement"],
  ["thermocoller", "thermocollage", "entoiler", "entoilage", "thermo"],
  ["repasser", "repassage", "presser", "fer", "pressage"],
  ["ebouter", "eboutage", "nettoyer", "nettoyage", "fils", "fil"],
  ["controler", "controle", "verifier", "verification", "inspection", "inspecter"],
  ["braguette", "fermeture", "zip", "eclair", "glissiere"],
  ["boutonniere", "boutonnieres"],
  ["bouton", "boutons"],
  ["bride", "brides", "brider", "renfort"],
  ["empiecement", "empiecements", "dos", "tiepoint"],
  ["encolure", "col"],
  ["bord", "bordcote", "rib"],
  ["poche", "poches"],
  ["passant", "passants"],
  ["ceinture", "ceintures"],
  ["manche", "manches"],
  ["poignet", "poignets", "manchette"],
  ["epaule", "epaules"],
  ["etiquette", "etiquettes", "griffe", "label"],
  ["plier", "pliage", "ensacher", "emballer", "emballage"],
  ["marquer", "marquage", "tracer", "repere", "reperer"],
  ["pince", "pinces"],
  ["parementure", "parement"],
  ["doublure", "doubler"],
];
const SYN_INDEX = new Map<string, string[]>();
for (const g of SYNONYMS) for (const w of g) SYN_INDEX.set(w, g);

function expand(token: string): string[] {
  const out = new Set([token]);
  if (token.length >= 3) for (const [w, g] of SYN_INDEX) if (w.startsWith(token)) g.forEach((x) => out.add(x));
  return [...out];
}

/** Part des mots tapés retrouvés (en début de mot) dans le texte, synonymes compris. */
function matchScore(qTokens: string[][], text: string): number {
  const words = text.split(" ");
  let hit = 0;
  for (const alts of qTokens) if (alts.some((a) => words.some((w) => w.startsWith(a)))) hit++;
  return qTokens.length ? hit / qTokens.length : 0;
}

let catalogPromise: Promise<Catalog | null> | null = null;
export function loadCatalog(): Promise<Catalog | null> {
  catalogPromise ??= fetch("/catalogue/operations.json").then((r) => (r.ok ? r.json() : null)).catch(() => null);
  return catalogPromise;
}

const histCache = new Map<string, Promise<HistoryEntry[]>>();
/** Opérations déjà saisies dans les gammes enregistrées de l'atelier (lecture directe, droits RLS). */
export function loadHistory(orgId: string, refresh = false): Promise<HistoryEntry[]> {
  if (refresh) histCache.delete(orgId);
  if (!histCache.has(orgId)) {
    histCache.set(orgId, (async () => {
      const { data, error } = await supabase.from("problems").select("ops:payload->operations, created_at")
        .eq("org_id", orgId).order("created_at", { ascending: false }).limit(200);
      if (error || !data) return [];
      return aggregateHistory((data as { ops: unknown }[]).flatMap((r) => (Array.isArray(r.ops) ? r.ops : [])));
    })().catch(() => []));
  }
  return histCache.get(orgId)!;
}

interface RawOp { name?: string; duration?: number; machine_type?: string; section?: string; required_skills?: string[] }
/** Regroupe par désignation (sans accents ni casse) ; les gammes les plus récentes donnent machine et section. */
export function aggregateHistory(ops: RawOp[]): HistoryEntry[] {
  const by = new Map<string, { e: HistoryEntry; times: number[] }>();
  for (const o of ops) {
    const name = (o.name ?? "").trim();
    if (!name) continue;
    const k = norm(name);
    let g = by.get(k);
    if (!g) {
      g = { e: { name, count: 0, duration: 0, machine_type: o.machine_type ?? "", section: o.section ?? "", skills: (o.required_skills ?? []).join(", ") }, times: [] };
      by.set(k, g);
    }
    g.e.count++;
    if (o.duration && o.duration > 0) g.times.push(o.duration);
  }
  return [...by.values()].map(({ e, times }) => {
    times.sort((a, b) => a - b);
    const m = times.length ? (times.length % 2 ? times[(times.length - 1) / 2] : (times[times.length / 2 - 1] + times[times.length / 2]) / 2) : 0;
    return { ...e, duration: Math.round(m * 1000) / 1000 };
  });
}

const fmt = (n: number) => n.toLocaleString("fr-FR", { maximumFractionDigits: 2 });

export function suggest(query: string, opts: { history: HistoryEntry[]; catalog: Catalog | null; garment?: string; local?: HistoryEntry[]; limit?: number }): Suggestion[] {
  const q = norm(query);
  if (q.length < 2) return [];
  const qTokens = q.split(" ").filter(Boolean).map(expand);
  const minScore = qTokens.length > 1 ? 0.5 : 1;
  const out: Suggestion[] = [];
  const seen = new Set<string>();

  const hist = [...(opts.local ?? []), ...opts.history];
  for (const h of hist) {
    const k = norm(h.name);
    if (seen.has(k)) continue;
    const s = matchScore(qTokens, k);
    if (s < minScore) continue;
    seen.add(k);
    out.push({
      kind: "atelier", name: h.name, duration: h.duration, machine_type: h.machine_type, section: h.section, skills: h.skills,
      detail: `Vos gammes${h.count > 1 ? ` · ${h.count} fois` : ""}${h.duration ? ` · ${fmt(h.duration)} min` : ""}`,
      score: 10 + s * 5 + Math.min(h.count, 10) * 0.3 + (k.startsWith(q) ? 2 : 0),
    });
  }

  const fam = opts.garment ? FAMILY[opts.garment] ?? [] : [];
  for (const c of opts.catalog?.operations ?? []) {
    const k = norm(c.nom);
    if (seen.has(k)) continue;
    const sName = matchScore(qTokens, k);
    const s = Math.max(sName, matchScore(qTokens, `${k} ${norm(c.section)}`));
    if (s < minScore) continue;
    const famHit = fam.length ? c.vetements.some((v) => fam.includes(v)) : false;
    if (fam.length && !famHit && s < 1) continue;
    seen.add(k);
    const range: [number, number] = [c.sam.min, c.sam.max];
    out.push({
      kind: "catalogue", name: c.nom, duration: c.sam.med, machine_type: c.machine, section: c.section, skills: "",
      detail: `Temps publié ${c.sam.min === c.sam.max ? fmt(c.sam.med) : `${fmt(c.sam.min)} à ${fmt(c.sam.max)}`} min · ${c.vetements.slice(0, 2).join(", ")}${c.sam.n > 1 ? ` · ${c.sam.n} relevés` : ""}`,
      range, score: s * 3 + sName * 3 + (famHit ? 3 : 0) + (k.startsWith(q) ? 2 : 0) + Math.min(c.sam.n, 5) * 0.2,
    });
  }
  return out.sort((a, b) => b.score - a.score).slice(0, opts.limit ?? 8);
}
