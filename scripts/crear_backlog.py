#!/usr/bin/env python3
"""Crea en GitHub el backlog definido en backlog/backlog.yaml.

Crea etiquetas, milestones (sprints) e issues con jerarquía Épica → Historia → Tarea
(usando sub-issues de GitHub) y, cuando la API lo permite, relaciones de dependencia
("bloqueado por").

Requisitos:
  - GitHub CLI (`gh`) autenticado con permisos sobre el repositorio: `gh auth login`
  - PyYAML: `pip install pyyaml`  (o ejecutar con `uv run --with pyyaml ...`)

Uso:
  python scripts/crear_backlog.py --repo usuario/repositorio --dry-run   # simula
  python scripts/crear_backlog.py --repo usuario/repositorio             # crea

Es re-ejecutable: si un issue con el mismo título ya existe, lo reutiliza.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("Falta PyYAML: pip install pyyaml  (o: uv run --with pyyaml python scripts/crear_backlog.py ...)")

ROOT = Path(__file__).resolve().parent.parent
BACKLOG = ROOT / "backlog" / "backlog.yaml"
MAP_FILE = ROOT / "backlog" / "mapa_issues.json"
PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")

TIPO_LABEL = {
    "epica": "tipo:epica",
    "historia": "tipo:historia",
    "historia-tecnica": "tipo:historia-tecnica",
    "tarea": "tipo:tarea",
}

DOD = [
    "Pruebas nuevas en verde y `ruff` sin errores",
    "Ningún invariante de `AGENTS.md` (sección 2) roto",
    "Documentación actualizada si cambió configuración, comandos o arquitectura",
    "Revisión cruzada aprobada por el otro integrante",
]


# ----------------------------------------------------------------- utilidades gh

class GH:
    def __init__(self, repo: str, dry_run: bool):
        self.repo = repo
        self.dry = dry_run
        self._fake = 1000

    def run(self, args: list[str], stdin: str | None = None, mutating: bool = True) -> str:
        if self.dry and mutating:
            shown = " ".join(a if " " not in a else repr(a) for a in args)
            print(f"  [dry-run] gh {shown[:160]}")
            return ""
        res = subprocess.run(["gh", *args], input=stdin, text=True, capture_output=True)
        if res.returncode != 0:
            raise RuntimeError(f"gh {' '.join(args[:4])}… falló:\n{res.stderr.strip()}")
        return res.stdout.strip()

    def api(self, path: str, method: str = "GET", fields: dict | None = None, mutating: bool | None = None) -> str:
        args = ["api", "-X", method, path, "-H", "Accept: application/vnd.github+json"]
        for k, v in (fields or {}).items():
            flag = "-F" if isinstance(v, int) else "-f"
            args += [flag, f"{k}={v}"]
        return self.run(args, mutating=(method != "GET") if mutating is None else mutating)

    def fake_number(self) -> int:
        self._fake += 1
        return self._fake


# ----------------------------------------------------------------- render de cuerpos

def checklist(items: list[str]) -> str:
    return "\n".join(f"- [ ] {i}" for i in items)


def find(items_by_id: dict, key: str) -> dict:
    return items_by_id[key]


def epic_of(item: dict, items_by_id: dict) -> str | None:
    cur = item
    while cur.get("padre"):
        cur = items_by_id[cur["padre"]]
    return cur["id"] if cur["tipo"] == "epica" and cur is not item else None


def render(item: dict, items_by_id: dict, sprints: dict) -> str:
    t = item["tipo"]
    out: list[str] = [f"<!-- backlog-id: {item['id']} -->"]

    if t == "epica":
        out += ["## Objetivo", item["objetivo"].strip(), "",
                "## Alcance", item["alcance"].strip(), "",
                "## Indicadores", item["indicadores"].strip(), "",
                "## Historias y tareas",
                "Ver los *sub-issues* de esta épica."]

    elif t in ("historia", "historia-tecnica"):
        if t == "historia":
            out += [f"> Como **{item['como']}**, quiero {item['quiero']}, para {item['para']}.", ""]
        else:
            out += ["## Descripción", item["descripcion"].strip(), ""]
        out += ["## Criterios de aceptación", checklist(item["criterios"]), "",
                "## Estimación",
                f"- **Puntos:** {item['puntos']}",
                f"- **Sprint:** {sprints[item['sprint']]}",
                f"- **Épica:** {{{{{item['padre']}}}}}", "",
                "## Tareas",
                "Ver los *sub-issues*. La historia se cierra cuando todas sus tareas están cerradas "
                "y se verificaron los criterios de aceptación."]

    else:  # tarea
        parent = items_by_id[item["padre"]]
        ctx = f"Parte de {{{{{parent['id']}}}}} · {parent['titulo']}"
        ep = epic_of(item, items_by_id)
        if ep and ep != parent["id"]:
            ctx += f"\n\nÉpica: {{{{{ep}}}}} · {items_by_id[ep]['titulo']}"
        out += ["## Contexto", ctx, "",
                "## Objetivo", item["objetivo"].strip(), "",
                "## Especificación técnica", item["especificacion"].strip(), "",
                "## Criterios de aceptación", checklist(item["criterios"]), "",
                "## Definición de terminado", checklist(DOD), ""]
        deps = item.get("depende") or []
        out += ["## Dependencias",
                "\n".join(f"- {{{{{d}}}}} · {items_by_id[d]['titulo']}" for d in deps) if deps else "Ninguna.", ""]
        if item.get("archivos"):
            out += ["## Archivos involucrados", "\n".join(f"- `{a}`" for a in item["archivos"]), ""]
        out += ["## Notas para agentes",
                "- Lee `AGENTS.md` y la historia padre antes de empezar.",
                "- Implementa solo este alcance; el trabajo extra va en un issue nuevo.",
                "- Rama sugerida: `feat/<número>-<descripción-corta>`; el PR debe incluir `Closes #<número>`."]
        if item.get("notas"):
            out.append(f"- {item['notas'].strip()}")
        out.append("")
        out += [f"**Sprint:** {sprints[item['sprint']]}"]

    return "\n".join(out).strip() + "\n"


def resolve(text: str, numbers: dict[str, int]) -> str:
    def repl(m: re.Match) -> str:
        key = m.group(1)
        return f"#{numbers[key]}" if key in numbers else key
    return PLACEHOLDER.sub(repl, text)


# ----------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, help="usuario/repositorio")
    ap.add_argument("--dry-run", action="store_true", help="muestra lo que haría sin crear nada")
    args = ap.parse_args()

    data = yaml.safe_load(BACKLOG.read_text(encoding="utf-8"))
    items: list[dict] = data["items"]
    items_by_id = {i["id"]: i for i in items}
    sprints = {m["key"]: m["title"] for m in data["milestones"]}

    # Validaciones previas
    for it in items:
        for ref in [it.get("padre"), *(it.get("depende") or [])]:
            if ref and ref not in items_by_id:
                sys.exit(f"{it['id']}: referencia desconocida {ref}")
        if it["tipo"] != "epica" and it.get("sprint") not in sprints:
            sys.exit(f"{it['id']}: sprint inválido {it.get('sprint')}")
    seen: set[str] = set()
    for it in items:
        if it.get("padre") and it["padre"] not in seen:
            sys.exit(f"{it['id']}: su padre {it['padre']} debe aparecer antes en el archivo")
        seen.add(it["id"])

    gh = GH(args.repo, args.dry_run)
    R = args.repo
    print(f"Repositorio: {R}{'  (simulación)' if args.dry_run else ''}")

    # 1. Etiquetas
    print("\n1) Etiquetas")
    for lb in data["labels"]:
        gh.run(["label", "create", lb["name"], "--repo", R, "--color", lb["color"],
                "--description", lb.get("description", ""), "--force"])
        print(f"  ✓ {lb['name']}")

    # 2. Milestones
    print("\n2) Milestones")
    existing_ms: set[str] = set()
    if not args.dry_run:
        raw = gh.api(f"repos/{R}/milestones?state=all&per_page=100")
        existing_ms = {m["title"] for m in json.loads(raw or "[]")}
    for m in data["milestones"]:
        if m["title"] in existing_ms:
            print(f"  = {m['title']} (ya existe)")
            continue
        gh.api(f"repos/{R}/milestones", "POST",
               {"title": m["title"], "due_on": f"{m['due']}T12:00:00Z", "description": m.get("description", "")})
        print(f"  ✓ {m['title']}")

    # 3. Issues
    print("\n3) Issues")
    existing: dict[str, int] = {}
    if not args.dry_run:
        raw = gh.run(["issue", "list", "--repo", R, "--state", "all", "--limit", "1000",
                      "--json", "number,title"], mutating=False)
        existing = {i["title"]: i["number"] for i in json.loads(raw or "[]")}

    numbers: dict[str, int] = {}
    db_ids: dict[str, int] = {}
    bodies: dict[str, str] = {}
    for it in items:
        body = render(it, items_by_id, sprints)
        bodies[it["id"]] = body
        labels = [TIPO_LABEL[it["tipo"]], f"capa:{it['capa']}", *(it.get("labels") or [])]
        if it.get("puntos"):
            labels.append(f"pts:{it['puntos']}")

        if it["titulo"] in existing:
            numbers[it["id"]] = existing[it["titulo"]]
            print(f"  = #{numbers[it['id']]} {it['titulo']} (ya existe)")
        else:
            cmd = ["issue", "create", "--repo", R, "--title", it["titulo"], "--body-file", "-"]
            for lb in labels:
                cmd += ["--label", lb]
            if it.get("sprint"):
                cmd += ["--milestone", sprints[it["sprint"]]]
            url = gh.run(cmd, stdin=resolve(body, numbers))
            numbers[it["id"]] = gh.fake_number() if args.dry_run else int(url.rstrip("/").split("/")[-1])
            print(f"  ✓ #{numbers[it['id']]} {it['titulo']}")

        if not args.dry_run:
            raw = gh.api(f"repos/{R}/issues/{numbers[it['id']]}", mutating=False)
            db_ids[it["id"]] = int(json.loads(raw)["id"])

    # 4. Reemplazar referencias {{ID}} por #número en todos los cuerpos
    print("\n4) Referencias cruzadas")
    for it in items:
        if PLACEHOLDER.search(bodies[it["id"]]):
            gh.run(["issue", "edit", str(numbers[it["id"]]), "--repo", R, "--body-file", "-"],
                   stdin=resolve(bodies[it["id"]], numbers))
    print("  ✓ cuerpos actualizados")

    # 5. Jerarquía (sub-issues)
    print("\n5) Jerarquía Épica → Historia → Tarea")
    for it in items:
        if not it.get("padre"):
            continue
        parent_n = numbers[it["padre"]]
        try:
            gh.api(f"repos/{R}/issues/{parent_n}/sub_issues", "POST",
                   {"sub_issue_id": db_ids.get(it["id"], 0)})
        except RuntimeError as e:
            if "already" in str(e).lower() or "duplicate" in str(e).lower():
                continue
            print(f"  ! No se pudo enlazar {it['id']} a {it['padre']}: {str(e).splitlines()[-1]}")
    print("  ✓ sub-issues enlazados")

    # 6. Dependencias (bloqueado por) — mejor esfuerzo
    print("\n6) Dependencias")
    dep_ok = True
    for it in items:
        for d in it.get("depende") or []:
            try:
                gh.api(f"repos/{R}/issues/{numbers[it['id']]}/dependencies/blocked_by", "POST",
                       {"issue_id": db_ids.get(d, 0)})
            except RuntimeError as e:
                if "already" in str(e).lower():
                    continue
                dep_ok = False
                print(f"  ! Dependencias nativas no disponibles ({str(e).splitlines()[-1]}). "
                      "Quedan documentadas en el cuerpo de cada issue.")
                break
        if not dep_ok:
            break
    if dep_ok:
        print("  ✓ dependencias registradas")

    if not args.dry_run:
        MAP_FILE.write_text(json.dumps(numbers, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nMapa ID → número guardado en {MAP_FILE.relative_to(ROOT)}")
    print("\nListo.")


if __name__ == "__main__":
    main()
