import { Link } from "react-router-dom";

type Row = [string, boolean, string, string];

const SAM: Row[] = [
  ["Op_ID", true, "OP010", "Identifiant unique de l'opération."],
  ["Description", false, "Assembler côtés", "Désignation lisible."],
  ["SAM_min", true, "0,45", "Temps standard en minutes par pièce. Virgule ou point acceptés."],
  ["Predecesseurs", false, "OP010, OP020", "Opérations à terminer avant. Vide = peut démarrer tout de suite."],
  ["Type_Machine", false, "piqueuse_plate", "Machine nécessaire. Mêmes mots que dans le fichier des postes."],
  ["Competences", false, "couture_droite, ourlet", "Compétences requises. Mêmes mots que dans le fichier des ouvriers."],
  ["Section", false, "Montage", "Section ou zone de l'atelier."],
  ["Optionnel", false, "Non", "Oui / Non. Une opération optionnelle peut être ignorée."],
];
const WS: Row[] = [
  ["Poste_ID", true, "WS01", "Identifiant unique du poste."],
  ["Nom", false, "Piqueuse plate 1", "Nom affiché."],
  ["Type_Machine", true, "piqueuse_plate", "Machine installée sur le poste."],
  ["Disponible", false, "Oui", "Oui / Non (Oui par défaut)."],
  ["Max_Ouvriers", false, "1", "Nombre maximum d'ouvriers sur le poste."],
  ["Section", false, "Montage", "Section ou zone."],
];
const WK: Row[] = [
  ["Ouvrier_ID", true, "W001", "Identifiant unique."],
  ["Nom", false, "Marie D.", "Nom ou prénom."],
  ["Competences", true, "couture_droite, surjet_5_fils", "Compétences maîtrisées."],
  ["Efficacite", false, "0,95", "1 = 100 %, 0,9 = 90 % (1 par défaut)."],
  ["Disponible", false, "Oui", "Oui / Non (Oui par défaut)."],
  ["Poste_Assigne", false, "WS03", "Poste imposé, facultatif."],
];

function Spec({ title, rows, base, example, required }: { title: string; rows: Row[]; base: string; example?: string; required?: boolean }) {
  return (
    <section className="card doc">
      <h3>{title} {required ? <span className="req">obligatoire</span> : <span className="muted small">facultatif</span>}</h3>
      <div className="dl-row">
        <a className="btn small primary" href={`/modeles/${base}_vide.xlsx`} download>Modèle vide Excel</a>
        <a className="btn small" href={`/modeles/${base}_vide.csv`} download>Modèle vide CSV</a>
        {example && <a className="btn small ghost" href={`/modeles/${example}`} download>Exemple rempli</a>}
      </div>
      <table>
        <thead><tr><th>Colonne</th><th></th><th>Exemple</th><th>Contenu</th></tr></thead>
        <tbody>{rows.map(([c, req, ex, txt]) => (
          <tr key={c}><td><code>{c}</code></td><td>{req ? <span className="req">requis</span> : ""}</td><td>{ex}</td><td>{txt}</td></tr>
        ))}</tbody>
      </table>
    </section>
  );
}

export default function FileHelp() {
  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Format des fichiers</h1><p className="muted">Préparez vos données dans Excel, puis importez-les dans <Link to="/gamme">l'éditeur de gamme</Link> ou directement dans <Link to="/calcul">Nouveau calcul</Link>.</p></div>
      </div>
      <section className="card doc">
        <h3>Règles générales</h3>
        <ul>
          <li>Formats acceptés : Excel <code>.xlsx</code>, CSV (séparateur <code>;</code> ou <code>,</code>, encodage UTF-8) ou JSON.</li>
          <li>Une ligne d'en-têtes, puis une ligne par opération, poste ou ouvrier. Les colonnes peuvent être dans n'importe quel ordre.</li>
          <li>Les en-têtes ne tiennent pas compte des majuscules (évitez les accents). Variantes reconnues, par exemple : <code>Code</code> ou <code>Ref</code> pour Op_ID, <code>SAM</code> ou <code>Minutes</code> pour SAM_min, <code>Designation</code> ou <code>Libelle</code> pour Description, <code>Machine</code> pour Type_Machine.</li>
          <li>Listes (prédécesseurs, compétences) : séparez les valeurs par des virgules.</li>
          <li>Les mots doivent être identiques d'un fichier à l'autre : si une opération demande <code>surjeteuse_5_fils</code>, un poste doit avoir exactement ce type de machine.</li>
          <li>Seul le fichier de gamme est obligatoire. Sans postes ni ouvriers, le calcul répartit les opérations sans vérifier le parc ni les compétences.</li>
        </ul>
      </section>
      <Spec title="1. Gamme opératoire (SAM)" rows={SAM} base="modele_gamme_SAM" example="exemple_chemise_SAM.csv" required />
      <Spec title="2. Postes / machines" rows={WS} base="modele_postes" example="exemple_chemise_postes.csv" />
      <Spec title="3. Ouvriers / compétences" rows={WK} base="modele_ouvriers" example="exemple_chemise_ouvriers.csv" />
    </div>
  );
}
