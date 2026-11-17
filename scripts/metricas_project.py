#!/usr/bin/env python3
"""Mantiene al día los campos derivados y el avance Plan vs Real del GitHub Project del backlog.

Para cada issue del Project:
  - *Puntos*: del label `points:N`.
  - *Épica*: siguiendo la cadena de padres hasta el issue con label `epic`. Las opciones del campo
    se crean a partir de las épicas (`E3 · Gobernanza`, descripción `#3`).
  - *Fecha objetivo*: último día hábil de su *Sprint*. En las épicas, la mayor fecha de sus descendientes.
  - *Completado %*: 100 si está en Done o cerrado; 0 si no (no aplica a épicas).
  - *Status*: Done si el issue está cerrado.

Avance acumulado (gráfico de Insights «Avance del proyecto vs plan»):
  Mantiene ítems borrador «📈 Plan acumulado · Sprint N» y «📈 Real acumulado · Sprint N» con los
  campos *Serie* (Plan/Real), *Sprint* y *Avance acumulado %*. Se calcula sobre los puntos de
  historias y bugs:
    Plan = puntos planificados hasta ese sprint / total.
    Real = puntos en Done de los sprints hasta ese sprint / total (solo sprints ya iniciados).
  Las vistas ocultan estos marcadores con el filtro `-is:draft`. No los borres a mano.

Solo usa la biblioteca estándar y `gh`. Requiere un token con permiso de escritura sobre Projects
(classic con scopes `repo` y `project`) en GH_TOKEN.

Uso:
  python scripts/metricas_project.py --owner mignacio0803-hue --project 1 [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time

EPIC_LABEL = "epic"
PROGRESS_TYPES = {"type: user-story", "type: tech-story", "type: bug"}
POINTS_RE = re.compile(r"^points:(\d+)$")
BACKLOG_ID_RE = re.compile(r"<!-- backlog-id: (\w+) -->")
EPIC_TITLE_RE = re.compile(r"\[Épica\]\s*([^·]+?)\s*·")
DRY = False


def gql(query: str, **variables) -> dict:
    payload = json.dumps({"query": query, "variables": variables})
    for attempt in range(5):
        res = subprocess.run(["gh", "api", "graphql", "--input", "-"], input=payload, text=True, capture_output=True)
        out = json.loads(res.stdout or "{}")
        if res.returncode == 0 and not out.get("errors"):
            return out["data"]
        if "Something went wrong" in res.stdout and attempt < 4:
            time.sleep(3 * (attempt + 1))
            continue
        sys.exit(f"Error de GraphQL: {res.stdout or res.stderr}")
    raise AssertionError


def mutate(query: str, **variables) -> dict | None:
    if DRY:
        print(f"  [dry-run] {query.split('(')[0].split()[-1]} {json.dumps(variables, ensure_ascii=False)[:150]}")
        return None
    return gql(query, **variables)


FIELDS_Q = """
query($owner:String!, $number:Int!) {
  user(login:$owner) { projectV2(number:$number) { id
    fields(first:50) { nodes {
      ... on ProjectV2FieldCommon { id name dataType }
      ... on ProjectV2SingleSelectField { options { id name description } }
      ... on ProjectV2IterationField { configuration { iterations { id title startDate duration }
                                                       completedIterations { id title startDate duration } } }
    } } } }
}"""

ITEMS_Q = """
query($owner:String!, $number:Int!, $after:String) {
  user(login:$owner) { projectV2(number:$number) {
    items(first:100, after:$after) { pageInfo { hasNextPage endCursor } nodes { id type
      content {
        ... on Issue { number title state body labels(first:20) { nodes { name } } parent { number } }
        ... on DraftIssue { id title }
      }
      fieldValues(first:30) { nodes {
        ... on ProjectV2ItemFieldSingleSelectValue { optionId field { ... on ProjectV2FieldCommon { name } } }
        ... on ProjectV2ItemFieldNumberValue { number field { ... on ProjectV2FieldCommon { name } } }
        ... on ProjectV2ItemFieldDateValue { date field { ... on ProjectV2FieldCommon { name } } }
        ... on ProjectV2ItemFieldIterationValue { iterationId field { ... on ProjectV2FieldCommon { name } } }
      } }
    } } } }
}"""

SET_VALUE = """mutation($p:ID!, $i:ID!, $f:ID!, $v:ProjectV2FieldValue!) {
  updateProjectV2ItemFieldValue(input:{projectId:$p, itemId:$i, fieldId:$f, value:$v}) { projectV2Item { id } } }"""
CLEAR_VALUE = """mutation($p:ID!, $i:ID!, $f:ID!) {
  clearProjectV2ItemFieldValue(input:{projectId:$p, itemId:$i, fieldId:$f}) { projectV2Item { id } } }"""


class Project:
    def __init__(self, owner: str, number: int):
        self.owner, self.number = owner, number
        self.reload_fields()

    def reload_fields(self) -> None:
        data = gql(FIELDS_Q, owner=self.owner, number=self.number)["user"]["projectV2"]
        self.id = data["id"]
        self.fields = {f["name"]: f for f in data["fields"]["nodes"] if f}

    def ensure_field(self, name: str, data_type: str, options: list[dict] | None = None) -> None:
        if name in self.fields:
            return
        inp = {"projectId": self.id, "name": name, "dataType": data_type}
        if options:
            inp["singleSelectOptions"] = options
        mutate("""mutation($i:CreateProjectV2FieldInput!) { createProjectV2Field(input:$i) {
                  projectV2Field { ... on ProjectV2FieldCommon { id } } } }""", i=inp)
        print(f"  campo creado: {name}")
        if not DRY:
            self.reload_fields()

    def option_id(self, field: str, name: str) -> str | None:
        return next((o["id"] for o in self.fields.get(field, {}).get("options", []) if o["name"] == name), None)

    def iterations(self) -> list[dict]:
        cfg = self.fields["Sprint"]["configuration"]
        its = cfg["completedIterations"] + cfg["iterations"]
        return sorted(its, key=lambda i: i["startDate"])

    def items(self) -> list[dict]:
        out, after = [], None
        while True:
            page = gql(ITEMS_Q, owner=self.owner, number=self.number, after=after)["user"]["projectV2"]["items"]
            out += page["nodes"]
            if not page["pageInfo"]["hasNextPage"]:
                return out
            after = page["pageInfo"]["endCursor"]

    def set(self, item_id: str, field: str, value: dict | None) -> None:
        fid = self.fields[field]["id"]
        if value is None:
            mutate(CLEAR_VALUE, p=self.id, i=item_id, f=fid)
        else:
            mutate(SET_VALUE, p=self.id, i=item_id, f=fid, v=value)


def values(item: dict) -> dict:
    out = {}
    for v in item["fieldValues"]["nodes"]:
        if not v or not v.get("field"):
            continue
        out[v["field"]["name"]] = next(v[k] for k in ("optionId", "number", "date", "iterationId") if k in v)
    return out


def last_workday(it: dict) -> str:
    d = dt.date.fromisoformat(it["startDate"]) + dt.timedelta(days=it["duration"] - 1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d.isoformat()


def sync_epic_options(p: Project, epics: dict[int, dict]) -> None:
    wanted = []
    for n, it in sorted(epics.items()):
        bid = BACKLOG_ID_RE.search(it["content"]["body"] or "")
        mod = EPIC_TITLE_RE.search(it["content"]["title"])
        name = f"{bid.group(1) if bid else '#' + str(n)} · {mod.group(1).strip() if mod else it['content']['title'][:30]}"
        wanted.append({"name": name, "color": "BLUE", "description": f"#{n}"})
    current = [{"name": o["name"], "description": o["description"]} for o in p.fields["Épica"]["options"]]
    if current == [{"name": w["name"], "description": w["description"]} for w in wanted]:
        return
    print("  opciones de Épica actualizadas:", ", ".join(w["name"] for w in wanted))
    mutate("""mutation($f:ID!, $o:[ProjectV2SingleSelectFieldOptionInput!]) {
              updateProjectV2Field(input:{fieldId:$f, singleSelectOptions:$o}) {
                projectV2Field { ... on ProjectV2SingleSelectField { id } } } }""",
           f=p.fields["Épica"]["id"], o=wanted)
    if not DRY:
        p.reload_fields()


def main() -> None:
    global DRY
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--owner", required=True)
    ap.add_argument("--project", type=int, required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    DRY = args.dry_run

    p = Project(args.owner, args.project)
    print("1) Campos")
    for name, kind in [("Puntos", "NUMBER"), ("Completado %", "NUMBER"), ("Fecha objetivo", "DATE"),
                       ("Avance acumulado %", "NUMBER")]:
        p.ensure_field(name, kind)
    p.ensure_field("Serie", "SINGLE_SELECT", [
        {"name": "Plan", "color": "GRAY", "description": "Avance planificado acumulado"},
        {"name": "Real", "color": "GREEN", "description": "Avance real acumulado"}])
    for required in ("Status", "Sprint", "Épica"):
        if required not in p.fields:
            sys.exit(f"Falta el campo «{required}» en el Project.")

    items = p.items()
    issues = {i["content"]["number"]: i for i in items if i["type"] == "ISSUE" and i["content"]}
    labels = {n: {lb["name"] for lb in i["content"]["labels"]["nodes"]} for n, i in issues.items()}
    epics = {n: i for n, i in issues.items() if EPIC_LABEL in labels[n]}
    sync_epic_options(p, epics)
    epic_option = {f"#{n}": p.option_id("Épica", o["name"]) for o in p.fields["Épica"]["options"]
                   for n in [int(o["description"][1:])] if o["description"].startswith("#")}
    done = p.option_id("Status", "Done")
    its = {i["id"]: i for i in p.iterations()}
    if not DRY:
        items = p.items()  # los valores de Épica pudieron reiniciarse al cambiar sus opciones
        issues = {i["content"]["number"]: i for i in items if i["type"] == "ISSUE" and i["content"]}

    def epic_of(n: int) -> int | None:
        seen = set()
        while n in issues and n not in seen:
            seen.add(n)
            if n in epics:
                return n
            parent = issues[n]["content"]["parent"]
            if not parent:
                return None
            n = parent["number"]
        return n if n in epics else None

    print("2) Campos derivados")
    changes = 0
    epic_dates: dict[int, str] = {}
    for n, it in sorted(issues.items()):
        v = values(it)
        closed = it["content"]["state"] == "CLOSED"
        is_epic = n in epics
        want: dict[str, dict | None] = {}

        if closed and v.get("Status") != done:
            want["Status"] = {"singleSelectOptionId": done}
        is_done = closed or v.get("Status") == done

        pts = next((int(m.group(1)) for lb in labels[n] if (m := POINTS_RE.match(lb))), None)
        if (v.get("Puntos") or None) != (float(pts) if pts else None):
            want["Puntos"] = {"number": float(pts)} if pts else None

        e = epic_of(n)
        opt = epic_option.get(f"#{e}") if e else None
        if v.get("Épica") != opt:
            want["Épica"] = {"singleSelectOptionId": opt} if opt else None

        if not is_epic:
            pct = 100.0 if is_done else 0.0
            if v.get("Completado %") != pct:
                want["Completado %"] = {"number": pct}
            sprint = its.get(v.get("Sprint"))
            if sprint:
                date = last_workday(sprint)
                if v.get("Fecha objetivo") != date:
                    want["Fecha objetivo"] = {"date": date}
                if e:
                    epic_dates[e] = max(epic_dates.get(e, ""), date)

        for field, value in want.items():
            p.set(it["id"], field, value)
            changes += 1
        if want:
            print(f"  #{n}: {', '.join(want)}")

    for e, date in epic_dates.items():
        if values(issues[e]).get("Fecha objetivo") != date:
            p.set(issues[e]["id"], "Fecha objetivo", {"date": date})
            changes += 1
            print(f"  #{e} (épica): Fecha objetivo")
    print(f"  {changes} cambios")

    print("3) Avance acumulado Plan vs Real")
    sprint_list = p.iterations()
    order = {s["id"]: k for k, s in enumerate(sprint_list)}
    planned = [0.0] * len(sprint_list)
    real = [0.0] * len(sprint_list)
    total = 0.0
    for n, it in issues.items():
        if not labels[n] & PROGRESS_TYPES:
            continue
        pts = next((int(m.group(1)) for lb in labels[n] if (m := POINTS_RE.match(lb))), 0)
        if not pts:
            continue
        total += pts
        v = values(it)
        k = order.get(v.get("Sprint"))
        if k is None:
            continue
        planned[k] += pts
        if it["content"]["state"] == "CLOSED" or v.get("Status") == done:
            real[k] += pts
    today = dt.date.today().isoformat()
    markers = {i["content"]["title"]: i for i in items if i["type"] == "DRAFT_ISSUE" and i["content"]}
    acc_p = acc_r = 0.0
    for k, s in enumerate(sprint_list):
        acc_p += planned[k]
        acc_r += real[k]
        series = [("Plan", acc_p)]
        if s["startDate"] <= today:
            series.append(("Real", acc_r))
        for serie, acc in series:
            pct = round(100 * acc / total, 1) if total else 0.0
            title = f"📈 {serie} acumulado · {s['title']}"
            item = markers.get(title)
            if not item:
                body = ("Marcador para el gráfico de Insights «Avance del proyecto vs plan (%)». No borrar. "
                        "Lo mantiene scripts/metricas_project.py.")
                res = mutate("""mutation($p:ID!, $t:String!, $b:String) { addProjectV2DraftIssue(
                                input:{projectId:$p, title:$t, body:$b}) { projectItem { id } } }""",
                             p=p.id, t=title, b=body)
                if DRY:
                    continue
                item = {"id": res["addProjectV2DraftIssue"]["projectItem"]["id"], "fieldValues": {"nodes": []}}
                print(f"  marcador creado: {title}")
            v = values(item)
            if v.get("Serie") != p.option_id("Serie", serie):
                p.set(item["id"], "Serie", {"singleSelectOptionId": p.option_id("Serie", serie)})
            if v.get("Sprint") != s["id"]:
                p.set(item["id"], "Sprint", {"iterationId": s["id"]})
            if v.get("Avance acumulado %") != pct:
                p.set(item["id"], "Avance acumulado %", {"number": pct})
            if v.get("Status") != done:
                p.set(item["id"], "Status", {"singleSelectOptionId": done})
        print(f"  {s['title']}: plan {round(100 * acc_p / total, 1) if total else 0} %"
              + (f", real {round(100 * acc_r / total, 1) if total else 0} %" if s["startDate"] <= today else ""))
    print("Listo.")


if __name__ == "__main__":
    main()
