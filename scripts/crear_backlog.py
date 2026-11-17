#!/usr/bin/env python3
"""Crea o actualiza en GitHub el backlog definido en backlog/backlog.yaml.

Crea etiquetas, milestones (sprints) e issues con jerarquía Épica → Historia → Tarea
(usando sub-issues de GitHub) y, cuando la API lo permite, relaciones de dependencia
("bloqueado por"). Los cuerpos siguen el formato de las plantillas de
`.github/ISSUE_TEMPLATE/` (historia INVEST con escenarios y requisitos de seguridad).

Requisitos:
  - GitHub CLI (`gh`) autenticado con permisos sobre el repositorio: `gh auth login`
  - PyYAML: `pip install pyyaml`  (o ejecutar con `uv run --with pyyaml ...`)

Uso:
  python scripts/crear_backlog.py --repo usuario/repositorio --dry-run       # simula la creación
  python scripts/crear_backlog.py --repo usuario/repositorio                 # crea
  python scripts/crear_backlog.py --repo usuario/repositorio --actualizar    # reescribe títulos, cuerpos
                                                                             # y labels de los issues ya creados
  python scripts/crear_backlog.py --repo usuario/repositorio --actualizar --limpiar-labels
                                                                             # además borra labels sin uso
                                                                             # que no están en el catálogo
  python scripts/crear_backlog.py --vista-previa                             # genera backlog/vista_previa.md

La creación es re-ejecutable: si un issue con el mismo título ya existe, lo reutiliza.
`--actualizar` usa backlog/mapa_issues.json para saber qué número tiene cada ítem.
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
PREVIEW = ROOT / "backlog" / "vista_previa.md"
SECURITY_CATALOG = ROOT / "docs" / "seguridad.md"
PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")

PREFIX = "[GOB]"
TYPE_LABEL = {
    "epica": "epic",
    "historia": "type: user-story",
    "historia-tecnica": "type: tech-story",
    "tarea": "type: task",
}
LEGACY_LABEL_PREFIXES = ("tipo:", "capa:", "pts:")
MANUAL_LABELS = {"bloqueado", "needs-triage"}  # se conservan si alguien los puso a mano

DOD = [
    "Criterios de aceptación de la tarea cumplidos",
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

    def api_json(self, path: str, method: str, payload: dict) -> str:
        args = ["api", "-X", method, path, "-H", "Accept: application/vnd.github+json", "--input", "-"]
        return self.run(args, stdin=json.dumps(payload))

    def fake_number(self) -> int:
        self._fake += 1
        return self._fake


# ----------------------------------------------------------------- modelo

class Backlog:
    def __init__(self, data: dict):
        self.data = data
        self.items: list[dict] = data["items"]
        self.by_id = {i["id"]: i for i in self.items}
        self.sprints = {m["key"]: m for m in data["milestones"]}
        self.sprint_order = [m["key"] for m in data["milestones"]]
        self.children: dict[str, list[dict]] = {}
        for it in self.items:
            if it.get("padre"):
                self.children.setdefault(it["padre"], []).append(it)
        self.security = load_security_catalog()

    def epic_of(self, item: dict) -> dict:
        cur = item
        while cur.get("padre"):
            cur = self.by_id[cur["padre"]]
        return cur

    def story_of(self, item: dict) -> dict | None:
        cur = item
        while cur and cur["tipo"] == "tarea":
            cur = self.by_id.get(cur.get("padre"))
        return cur if cur and cur["tipo"] in ("historia", "historia-tecnica") else None

    def story_deps(self, story: dict) -> tuple[list[str], list[str]]:
        """Dependencias entre historias, derivadas de las dependencias de sus tareas."""
        own = {story["id"], *(t["id"] for t in self.children.get(story["id"], []))}
        depends, blocks = set(), set()
        for it in self.items:
            for d in it.get("depende") or []:
                src, dst = self.story_of(it), self.story_of(self.by_id[d])
                if not src or not dst or src["id"] == dst["id"]:
                    continue
                if it["id"] in own:
                    depends.add(dst["id"])
                if d in own:
                    blocks.add(src["id"])
        order = {i["id"]: n for n, i in enumerate(self.items)}
        return sorted(depends, key=order.get), sorted(blocks, key=order.get)

    def sprint_title(self, key: str | None) -> str:
        return self.sprints[key]["title"] if key else "sin sprint"

    def title(self, item: dict) -> str:
        if item["tipo"] == "epica":
            return f"{PREFIX} [Épica] {item['modulo']} · {item['resultado']}"
        if item["tipo"] == "tarea":
            return f"{PREFIX} [Task] {item['titulo']}"
        return f"{PREFIX} {item['titulo']}"

    def labels(self, item: dict) -> list[str]:
        labels = [TYPE_LABEL[item["tipo"]]]
        if item.get("prioridad"):
            labels.append(f"priority:{item['prioridad']}")
        if item.get("puntos"):
            labels.append(f"points:{item['puntos']}")
        labels.append(f"module:{item['capa']}")
        if item["tipo"] in ("historia", "historia-tecnica") and not all(v for _, v in self.invest(item)):
            labels.append("invest: needs-refinement")
        labels += item.get("labels") or []
        return labels

    def invest(self, story: dict) -> list[tuple[str, bool]]:
        depends, _ = self.story_deps(story)
        pts = story.get("puntos") or 0
        return [
            ("Independiente: se puede construir sola", not depends),
            ("Negociable: deja espacio a conversar", bool(story.get("supuestos"))),
            ("Valiosa: el beneficio para el usuario es claro", bool(story.get("contexto"))),
            ("Estimable: tiene story points", bool(pts)),
            ("Pequeña: cabe en un sprint", 0 < pts <= 8),
            ("Testeable: tiene criterios de aceptación en lenguaje de negocio", bool(story.get("escenarios"))),
            ("Segura: requisitos de seguridad completos", bool((story.get("seguridad") or {}).get("criterios"))),
        ]


def load_security_catalog() -> dict[str, str]:
    if not SECURITY_CATALOG.exists():
        return {}
    rows = re.findall(r"^\| (RS-[A-Z]+-\d+) \| (.+?) \|", SECURITY_CATALOG.read_text(encoding="utf-8"), re.M)
    return dict(rows)


# ----------------------------------------------------------------- render de cuerpos

def checklist(items: list[str], checked: bool = False) -> str:
    mark = "x" if checked else " "
    return "\n".join(f"- [{mark}] {i}" for i in items)


def ref(b: Backlog, key: str) -> str:
    it = b.by_id[key]
    name = f"Épica {it['modulo']} · {it['resultado']}" if it["tipo"] == "epica" else it["titulo"]
    return f"{{{{{key}}}}} · {name}"


def security_section(b: Backlog, seg: dict | None, heredado_de: str | None = None) -> list[str]:
    out = ["### 🔐 Requisitos de seguridad", ""]
    if not seg:
        return out + ["**Datos involucrados:** Ninguno.", "",
                      "Sin requisitos específicos; aplican los invariantes de `AGENTS.md`.", ""]
    if heredado_de:
        out += [f"Hereda los requisitos de {{{{{heredado_de}}}}}. Detalle en [`docs/seguridad.md`](../blob/dev/docs/seguridad.md).", ""]
    out += [f"**Datos involucrados:** {', '.join(seg.get('datos') or ['Ninguno'])}.", "",
            "**Requisitos aplicables** ([catálogo](../blob/dev/docs/seguridad.md)):", ""]
    out += [f"- [x] **{c}** {b.security.get(c, '')}".rstrip() for c in seg.get("requisitos") or []]
    if seg.get("criterios") and not heredado_de:
        out += ["", "**Criterios de aceptación de seguridad:**", "", checklist(seg["criterios"])]
    return out + [""]


def render_epic(item: dict, b: Backlog, closed: set[str]) -> list[str]:
    stories = b.children.get(item["id"], [])
    sprint_keys = sorted({s["sprint"] for s in b.items if s.get("sprint") and b.epic_of(s)["id"] == item["id"]},
                         key=b.sprint_order.index)
    out = ["### 🎯 Objetivo de negocio", "", item["objetivo"].strip(), "",
           "### 📋 Contexto", "", item["alcance"].strip(), "",
           "### 🧩 Historias que la componen", ""]
    out += [f"- [{'x' if c['id'] in closed else ' '}] {ref(b, c['id'])}" for c in stories] or ["- (sin historias)"]
    out += ["", "### 📊 Métrica de éxito", "", item["indicadores"].strip(), ""]
    if sprint_keys:
        first, last = b.sprints[sprint_keys[0]], b.sprints[sprint_keys[-1]]
        out += ["### 📅 Horizonte estimado", "",
                f"{first['title'].split(' · ')[0]} a {last['title'].split(' · ')[0]} "
                f"(hasta el {last['due'][8:10]}/{last['due'][5:7]}/{last['due'][:4]}).", ""]
    reqs = sorted({r for s in stories for r in (s.get("seguridad") or {}).get("requisitos", [])})
    if reqs:
        out += ["### 🔐 Requisitos de seguridad", "",
                "Requisitos que cubren sus historias ([catálogo](../blob/dev/docs/seguridad.md)):", ""]
        out += [f"- **{r}** {b.security.get(r, '')}".rstrip() for r in reqs] + [""]
    return out


def render_story(item: dict, b: Backlog) -> list[str]:
    if item["tipo"] == "historia":
        story = f"**Como** {item['como']},\n**Quiero** {item['quiero']},\n**Para** {item['para']}."
    else:
        story = f"_Historia técnica._ {item['descripcion'].strip()}"
    out = ["### 🎯 Historia de usuario (Valiosa)", "", story, "",
           "### 📋 Contexto", "", (item.get("contexto") or "Por completar en refinamiento.").strip(), "",
           "### ✅ Criterios de aceptación (Testeable)", ""]
    for n, e in enumerate(item.get("escenarios") or [], 1):
        if n > 1:
            out += ["---", ""]
        out += [f"**Escenario {n}: {e['nombre']}**", "",
                f"- **Dado** {e['dado']}", f"- **Cuando** {e['cuando']}", f"- **Entonces** {e['entonces']}", ""]
    out += ["**Resumen verificable** (criterios del plan del proyecto):", "", checklist(item["criterios"]), ""]
    out += security_section(b, item.get("seguridad"))
    depends, blocks = b.story_deps(item)
    out += ["### 📏 Story Points (Estimable / Pequeña)", "",
            f"**{item['puntos']} puntos** · {b.sprint_title(item.get('sprint'))} · Prioridad {item.get('prioridad', '—')}", "",
            "### 🔗 Dependencias (Independiente)", "",
            f"- Épica: {ref(b, b.epic_of(item)['id'])}",
            f"- Depende de: {', '.join(ref(b, d) for d in depends) if depends else 'ninguna'}",
            f"- Bloquea a: {', '.join(ref(b, d) for d in blocks) if blocks else 'ninguna'}", ""]
    if item.get("supuestos"):
        out += ["### 🤝 Supuestos y puntos a negociar (Negociable)", "", item["supuestos"].strip(), ""]
    if item.get("fuera_de_alcance"):
        out += ["### 🚫 Fuera de alcance (No-objetivos)", "", item["fuera_de_alcance"].strip(), ""]
    out += ["### 💻 Notas técnicas / Contexto DEV", ""]
    if item.get("notas_tecnicas"):
        out += [item["notas_tecnicas"].strip(), ""]
    out += ["Las tareas de implementación son los *sub-issues* de esta historia. La historia se cierra cuando "
            "todas sus tareas están cerradas y se verificaron los criterios de aceptación.", "",
            "### 🔍 Checklist INVEST (Definition of Ready)", ""]
    out += [f"- [{'x' if ok else ' '}] {label}" for label, ok in b.invest(item)]
    return out + [""]


def render_task(item: dict, b: Backlog) -> list[str]:
    parent = b.by_id[item["padre"]]
    epic = b.epic_of(item)
    story = b.story_of(item)
    out = ["### 🎯 Historia de usuario (Valiosa)", ""]
    if story:
        out.append(f"Aporta a la historia {ref(b, story['id'])}.")
        if story["tipo"] == "historia":
            out += ["", f"**Como** {story['como']},\n**Quiero** {story['quiero']},\n**Para** {story['para']}."]
    else:
        out.append(f"Aporta a la épica {ref(b, epic['id'])}.")
    out += ["", "### 📋 Contexto", "", item["objetivo"].strip(), "",
            "### ✅ Criterios de aceptación (Testeable)", "", checklist(item["criterios"]), ""]
    out += security_section(b, (story or {}).get("seguridad"), heredado_de=story["id"] if story else None)
    out += ["### 💻 Especificación técnica", "", item["especificacion"].strip(), ""]
    if item.get("archivos"):
        out += ["**Archivos involucrados:**", "", "\n".join(f"- `{a}`" for a in item["archivos"]), ""]
    deps = item.get("depende") or []
    out += ["### 🔗 Dependencias", "",
            f"- {'Historia' if parent['tipo'] != 'epica' else 'Épica'}: {ref(b, parent['id'])}"]
    if parent["id"] != epic["id"]:
        out.append(f"- Épica: {ref(b, epic['id'])}")
    out += [f"- Depende de: {', '.join(ref(b, d) for d in deps) if deps else 'ninguna'}", "",
            f"**{b.sprint_title(item.get('sprint'))}** · Prioridad {item.get('prioridad', '—')}", "",
            "### ✔️ Definición de terminado", "", checklist(DOD), "",
            "### 🤖 Notas para agentes", "",
            "- Lee `AGENTS.md` y la historia padre antes de empezar.",
            "- Implementa solo este alcance; el trabajo extra va en un issue nuevo.",
            "- Rama: `feat/<número>-<descripción-corta>` desde `dev`; el PR debe incluir `Closes #<número>`."]
    if item.get("notas"):
        out.append(f"- {item['notas'].strip()}")
    return out + [""]


def render(item: dict, b: Backlog, closed: set[str] | None = None) -> str:
    out = [f"<!-- backlog-id: {item['id']} -->", ""]
    if item["tipo"] == "epica":
        out += render_epic(item, b, closed or set())
    elif item["tipo"] in ("historia", "historia-tecnica"):
        out += render_story(item, b)
    else:
        out += render_task(item, b)
    return "\n".join(out).strip() + "\n"


def resolve(text: str, numbers: dict[str, int]) -> str:
    def repl(m: re.Match) -> str:
        key = m.group(1)
        return f"#{numbers[key]}" if key in numbers else key
    return PLACEHOLDER.sub(repl, text)


# ----------------------------------------------------------------- validación

def validate(b: Backlog) -> None:
    for it in b.items:
        for r in [it.get("padre"), *(it.get("depende") or [])]:
            if r and r not in b.by_id:
                sys.exit(f"{it['id']}: referencia desconocida {r}")
        if it["tipo"] != "epica" and it.get("sprint") not in b.sprints:
            sys.exit(f"{it['id']}: sprint inválido {it.get('sprint')}")
        if it["tipo"] == "epica" and not (it.get("modulo") and it.get("resultado")):
            sys.exit(f"{it['id']}: la épica necesita 'modulo' y 'resultado' para su título")
        for r in (it.get("seguridad") or {}).get("requisitos", []):
            if b.security and r not in b.security:
                sys.exit(f"{it['id']}: requisito de seguridad {r} no está en docs/seguridad.md")
    seen: set[str] = set()
    for it in b.items:
        if it.get("padre") and it["padre"] not in seen:
            sys.exit(f"{it['id']}: su padre {it['padre']} debe aparecer antes en el archivo")
        seen.add(it["id"])


# ----------------------------------------------------------------- acciones

def sync_labels(gh: GH, b: Backlog, R: str) -> None:
    print("\n1) Etiquetas")
    for lb in b.data["labels"]:
        gh.run(["label", "create", lb["name"], "--repo", R, "--color", lb["color"],
                "--description", lb.get("description", ""), "--force"])
        print(f"  ✓ {lb['name']}")


def update_existing(gh: GH, b: Backlog, R: str, clean_labels: bool) -> None:
    if not MAP_FILE.exists():
        sys.exit("No existe backlog/mapa_issues.json: crea primero el backlog sin --actualizar.")
    numbers: dict[str, int] = json.loads(MAP_FILE.read_text(encoding="utf-8"))
    sync_labels(gh, b, R)

    raw = gh.run(["issue", "list", "--repo", R, "--state", "all", "--limit", "1000",
                  "--json", "number,state,labels"], mutating=False)
    current = {i["number"]: i for i in json.loads(raw or "[]")}
    closed = {k for k, n in numbers.items() if current.get(n, {}).get("state") == "CLOSED"}
    catalog = {lb["name"] for lb in b.data["labels"]}

    print("\n2) Issues")
    for it in b.items:
        n = numbers.get(it["id"])
        if not n:
            print(f"  ! {it['id']} no está en el mapa; se omite (créalo sin --actualizar)")
            continue
        keep = [lb["name"] for lb in current.get(n, {}).get("labels", []) if lb["name"] in MANUAL_LABELS]
        labels = list(dict.fromkeys(b.labels(it) + keep))
        gh.api_json(f"repos/{R}/issues/{n}", "PATCH",
                    {"title": b.title(it), "body": resolve(render(it, b, closed), numbers), "labels": labels})
        print(f"  ✓ #{n} {b.title(it)}")

    print("\n3) Etiquetas antiguas")
    raw = gh.run(["label", "list", "--repo", R, "--limit", "200", "--json", "name"], mutating=False)
    for lb in json.loads(raw or "[]"):
        name = lb["name"]
        if name in catalog:
            continue
        legacy = name.startswith(LEGACY_LABEL_PREFIXES)
        if not legacy and not clean_labels:
            continue
        if not legacy:
            used = gh.run(["issue", "list", "--repo", R, "--state", "all", "--label", name, "--json", "number",
                           "--limit", "1"], mutating=False)
            if json.loads(used or "[]"):
                print(f"  = {name} (en uso, se conserva)")
                continue
        gh.run(["label", "delete", name, "--repo", R, "--yes"])
        print(f"  ✗ {name}")


def write_preview(b: Backlog) -> None:
    numbers = json.loads(MAP_FILE.read_text(encoding="utf-8")) if MAP_FILE.exists() else {}
    parts = ["# Vista previa del backlog", "",
             "Generado con `python scripts/crear_backlog.py --vista-previa`. No editar a mano.", ""]
    for it in b.items:
        n = numbers.get(it["id"])
        parts += ["---", "", f"## {'#' + str(n) + ' ' if n else ''}{b.title(it)}", "",
                  f"**Labels:** {', '.join(f'`{lb}`' for lb in b.labels(it))}", "",
                  resolve(render(it, b), numbers), ""]
    PREVIEW.write_text("\n".join(parts), encoding="utf-8")
    print(f"Vista previa guardada en {PREVIEW.relative_to(ROOT)}")


def create(gh: GH, b: Backlog, R: str, dry: bool) -> None:
    sync_labels(gh, b, R)

    print("\n2) Milestones")
    existing_ms: set[str] = set()
    if not dry:
        raw = gh.api(f"repos/{R}/milestones?state=all&per_page=100")
        existing_ms = {m["title"] for m in json.loads(raw or "[]")}
    for m in b.data["milestones"]:
        if m["title"] in existing_ms:
            print(f"  = {m['title']} (ya existe)")
            continue
        gh.api(f"repos/{R}/milestones", "POST",
               {"title": m["title"], "due_on": f"{m['due']}T12:00:00Z", "description": m.get("description", "")})
        print(f"  ✓ {m['title']}")

    print("\n3) Issues")
    existing: dict[str, int] = {}
    if not dry:
        raw = gh.run(["issue", "list", "--repo", R, "--state", "all", "--limit", "1000",
                      "--json", "number,title"], mutating=False)
        existing = {i["title"]: i["number"] for i in json.loads(raw or "[]")}

    numbers: dict[str, int] = {}
    db_ids: dict[str, int] = {}
    bodies: dict[str, str] = {}
    for it in b.items:
        title = b.title(it)
        body = render(it, b)
        bodies[it["id"]] = body
        if title in existing:
            numbers[it["id"]] = existing[title]
            print(f"  = #{numbers[it['id']]} {title} (ya existe)")
        else:
            cmd = ["issue", "create", "--repo", R, "--title", title, "--body-file", "-"]
            for lb in b.labels(it):
                cmd += ["--label", lb]
            if it.get("sprint"):
                cmd += ["--milestone", b.sprint_title(it["sprint"])]
            url = gh.run(cmd, stdin=resolve(body, numbers))
            numbers[it["id"]] = gh.fake_number() if dry else int(url.rstrip("/").split("/")[-1])
            print(f"  ✓ #{numbers[it['id']]} {title}")
        if not dry:
            raw = gh.api(f"repos/{R}/issues/{numbers[it['id']]}", mutating=False)
            db_ids[it["id"]] = int(json.loads(raw)["id"])

    print("\n4) Referencias cruzadas")
    for it in b.items:
        if PLACEHOLDER.search(bodies[it["id"]]):
            gh.run(["issue", "edit", str(numbers[it["id"]]), "--repo", R, "--body-file", "-"],
                   stdin=resolve(bodies[it["id"]], numbers))
    print("  ✓ cuerpos actualizados")

    print("\n5) Jerarquía Épica → Historia → Tarea")
    for it in b.items:
        if not it.get("padre"):
            continue
        try:
            gh.api(f"repos/{R}/issues/{numbers[it['padre']]}/sub_issues", "POST",
                   {"sub_issue_id": db_ids.get(it["id"], 0)})
        except RuntimeError as e:
            if "already" in str(e).lower() or "duplicate" in str(e).lower():
                continue
            print(f"  ! No se pudo enlazar {it['id']} a {it['padre']}: {str(e).splitlines()[-1]}")
    print("  ✓ sub-issues enlazados")

    print("\n6) Dependencias")
    dep_ok = True
    for it in b.items:
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

    if not dry:
        MAP_FILE.write_text(json.dumps(numbers, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nMapa ID → número guardado en {MAP_FILE.relative_to(ROOT)}")


# ----------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", help="usuario/repositorio")
    ap.add_argument("--dry-run", action="store_true", help="muestra lo que haría sin cambiar nada")
    ap.add_argument("--actualizar", action="store_true",
                    help="reescribe título, cuerpo y labels de los issues que ya existen")
    ap.add_argument("--limpiar-labels", action="store_true",
                    help="con --actualizar, borra también los labels sin uso que no están en el catálogo")
    ap.add_argument("--vista-previa", action="store_true", help="genera backlog/vista_previa.md y termina")
    args = ap.parse_args()

    b = Backlog(yaml.safe_load(BACKLOG.read_text(encoding="utf-8")))
    validate(b)

    if args.vista_previa:
        write_preview(b)
        return
    if not args.repo:
        ap.error("--repo es obligatorio salvo con --vista-previa")

    gh = GH(args.repo, args.dry_run)
    print(f"Repositorio: {args.repo}{'  (simulación)' if args.dry_run else ''}")
    if args.actualizar:
        update_existing(gh, b, args.repo, args.limpiar_labels)
    else:
        create(gh, b, args.repo, args.dry_run)
    print("\nListo.")


if __name__ == "__main__":
    main()
