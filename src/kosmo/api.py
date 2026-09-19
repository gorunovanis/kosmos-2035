"""Convenience layer used by CLI, UI and tests: locate project folders, load assumptions,
resolve scenarios by id (organiser, derived, team), run and export."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

import yaml

from .case import Case, case_fingerprint, load_case
from .engine import RunResult, run
from .export import export_run
from .plan import Plan
from .scenario import Scenario, apply_geo_event, builtin_scenarios

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASE_DIR = PROJECT_ROOT / "data" / "case"
CONFIG_DIR = PROJECT_ROOT / "configs"
RESULTS_DIR = PROJECT_ROOT / "results"


def code_version() -> str:
    try:
        out = subprocess.run(["git", "describe", "--tags", "--always", "--dirty"], cwd=PROJECT_ROOT,
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return "unversioned"


def load_assumptions(path: Optional[Path] = None) -> tuple[dict, list[dict]]:
    """Returns (engine parameters, registry rows for export)."""
    p = path or (CONFIG_DIR / "assumptions.yaml")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    params = dict(raw.get("engine", {}))
    rows = []
    for item in raw.get("registry", []):
        rows.append({"id": item.get("id"), "name": item.get("name"), "value": item.get("value"), "unit": item.get("unit", ""),
                     "basis": item.get("basis", ""), "scope": item.get("scope", ""), "status": item.get("status", "TEAM_ASSUMPTION")})
    return params, rows


def all_scenarios(case: Case, team_dir: Optional[Path] = None) -> dict[str, Scenario]:
    scen = builtin_scenarios(case)
    tdir = team_dir or (CONFIG_DIR / "scenarios")
    if tdir.is_dir():
        for p in sorted(tdir.glob("*.yaml")):
            raw = yaml.safe_load(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and raw.get("scenario_id"):
                s = Scenario.from_dict(raw)
                scen[s.scenario_id] = s
    return scen


def get_scenario(case: Case, scenario_id: str, geo_event: Optional[dict] = None) -> Scenario:
    scen = all_scenarios(case)
    if scenario_id not in scen:
        raise KeyError(f"UNKNOWN_SCENARIO: {scenario_id}; known: {', '.join(sorted(scen))}")
    s = scen[scenario_id]
    if geo_event:
        s = apply_geo_event(s, geo_event, case)
    return s


def run_plan(plan: Plan, scenario_id: str, case: Optional[Case] = None, case_dir: Optional[Path] = None,
             assumptions: Optional[dict] = None, geo_event: Optional[dict] = None, keep_daily: bool = True) -> RunResult:
    case = case or load_case(case_dir or CASE_DIR)
    params, _ = load_assumptions()
    if assumptions:
        params.update(assumptions)
    scen = get_scenario(case, scenario_id, geo_event)
    return run(case, plan, scen, params, keep_daily=keep_daily)


def run_and_export(plan_path: Path, scenario_id: str, out_dir: Path, case_dir: Optional[Path] = None,
                   geo_event: Optional[dict] = None, write_daily: bool = True) -> tuple[RunResult, dict]:
    case = load_case(case_dir or CASE_DIR)
    plan = Plan.load(plan_path)
    params, rows = load_assumptions()
    scen = get_scenario(case, scenario_id, geo_event)
    res = run(case, plan, scen, params)
    meta = export_run(res, out_dir, assumptions_rows=rows, code_version=code_version(),
                      case_fingerprint=case_fingerprint(case), write_daily=write_daily)
    # keep the plan next to its results so the folder reopens on its own
    (Path(out_dir) / "plan.json").write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return res, meta
