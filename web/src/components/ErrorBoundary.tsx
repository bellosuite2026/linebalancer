import { Component, type ReactNode } from "react";

/** Empêche une erreur d'affichage (WebGL indisponible, données inattendues) de vider toute la page. */
export default class ErrorBoundary extends Component<{ children: ReactNode; label?: string }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error) { console.error(this.props.label ?? "Erreur d'affichage", error); }
  render() {
    if (this.state.error) return (
      <div className="notice err" role="alert">
        {this.props.label ?? "Cette partie de la page n'a pas pu s'afficher"} : {this.state.error.message}{" "}
        <button className="link" onClick={() => this.setState({ error: null })}>Réessayer</button>
      </div>
    );
    return this.props.children;
  }
}

export function hasWebGL(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch { return false; }
}
