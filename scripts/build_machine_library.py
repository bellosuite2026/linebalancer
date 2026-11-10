"""Génère web/src/lib/machineLibrary.ts depuis engine/machine_library.py (source unique).

    python scripts/build_machine_library.py
"""
from __future__ import annotations

import json
from pathlib import Path

from engine.machine_library import CATEGORIES, LIBRARY, SOURCES

OUT = Path(__file__).resolve().parents[1] / "web" / "src" / "lib" / "machineLibrary.ts"


def render() -> str:
    lines = [
        "// Fichier généré par scripts/build_machine_library.py depuis engine/machine_library.py : ne pas modifier à la main.",
        "export interface MachineDef { label: string; category: string; w: number; d: number; h: number; machine_type: string;",
        "  ops: string[]; shape: string; short: string; source: string }",
        f"export const MACHINE_CATEGORIES: Record<string, string> = {json.dumps(CATEGORIES, ensure_ascii=False)};",
        f"export const MACHINE_SOURCES: Record<string, string> = {json.dumps(SOURCES, ensure_ascii=False, indent=1)};",
        "export const MACHINE_LIBRARY: Record<string, MachineDef> = {",
    ]
    for k, v in LIBRARY.items():
        lines.append(f"  {k}: {json.dumps(v, ensure_ascii=False)},")
    lines.append("};")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    OUT.write_text(render(), encoding="utf-8")
    print(f"{OUT} : {len(LIBRARY)} machines")
