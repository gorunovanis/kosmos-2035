"""Sensitivity (tornado) and reverse stress (threshold search) on top of the engine.

All variations are explicit TEAM scenarios applied on a copy of the scenario; the plan is fixed."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Callable, Optional

from .case import Case
from .engine import RunResult, run
from .plan import Plan
from .scenario import Scenario


@dataclass
class Variation:
    name: str
    param: str
    apply: Callable[[Scenario, dict, float], tuple[Scenario, dict]]   # (scenario, assumptions, x) -> modified copies
    low: float
    high: float
    base: float
    unit: str = ""
    basis: str = ""


def _demand_mult(scen: Scenario, A: dict, x: float) -> tuple[Scenario, dict]:
    s = copy.deepcopy(scen)
    dm = s.demand_multiplier if isinstance(s.demand_multiplier, dict) else {"default": s.demand_multiplier or 1.0}
    dm = dict(dm)
    years = [k for k in dm if k != "default"]
    d = dm.get("default", 1.0)
    new = {"default": float(d) * x}
    for y in years:
        new[y] = float(dm[y]) * x
    s.demand_multiplier = new
    if s.critical_demand_multiplier is not None:
        cm = dict(s.critical_demand_multiplier)
        newc = {"default": float(cm.get("default", 1.0)) * x}
        for y in [k for k in cm if k != "default"]:
            newc[y] = float(cm[y]) * x
        s.critical_demand_multiplier = newc
    if s.demand_override:
        s.demand_override = {"total": {y: v * x for y, v in s.demand_override["total"].items()},
                             "critical": {y: v * x for y, v in s.demand_override["critical"].items()}}
    s.scenario_id = f"{scen.scenario_id}~demand x{x:g}"
    return s, A


def _price_mult(source_name: str):
    def f(scen: Scenario, A: dict, x: float) -> tuple[Scenario, dict]:
        s = copy.deepcopy(scen)
        table = dict(s.variable_price_multiplier)
        cur = table.get(source_name, {"default": 1.0})
        if isinstance(cur, (int, float)):
            cur = {"default": float(cur)}
        new = {k: float(v) * x for k, v in dict(cur).items()}
        new.setdefault("default", x)
        table[source_name] = new
        s.variable_price_multiplier = table
        s.scenario_id = f"{scen.scenario_id}~{source_name} price x{x:g}"
        return s, A
    return f


def _isru_share(scen: Scenario, A: dict, x: float) -> tuple[Scenario, dict]:
    s = copy.deepcopy(scen)
    table = dict(s.actual_delivery_share)
    cur = dict(table.get("Lunar-ISRU", {}) or {})
    base = {int(k): float(v) for k, v in cur.items() if k != "default"}
    new = {"default": x if not base else 1.0}
    for y, v in base.items():
        new[y] = v * x
    if not base:
        new = {"default": x}
    table["Lunar-ISRU"] = new
    s.actual_delivery_share = table
    s.scenario_id = f"{scen.scenario_id}~ISRU share x{x:g}"
    return s, A


def _rate(scen: Scenario, A: dict, x: float) -> tuple[Scenario, dict]:
    B = dict(A)
    B["discount_rate"] = x
    return scen, B


def standard_variations(scen: Scenario) -> list[Variation]:
    return [
        Variation("Спрос (все годы)", "demand", _demand_mult, 0.8, 1.25, 1.0, "×", "low/high демонстрируют ±20 %; +25 % за пределами high"),
        Variation("Цена Earth-Core", "price_core", _price_mult("Earth-Core"), 0.9, 1.35, 1.0, "×", "стресс задаёт ×1,25; исследуем 0,9–1,35"),
        Variation("Цена Earth-Flex", "price_flex", _price_mult("Earth-Flex"), 0.9, 1.35, 1.0, "×", "стресс задаёт ×1,25"),
        Variation("Цена Earth-New", "price_new", _price_mult("Earth-New"), 0.9, 1.35, 1.0, "×", "геосценарий 1,10–1,35"),
        Variation("Фактическая поставка ISRU", "isru_share", _isru_share, 0.5, 1.0, 1.0, "×", "стресс 0,55/0,75; надёжность первого года 0,78"),
        Variation("Ставка дисконта", "rate", _rate, 0.0, 0.12, 0.07, "доля", "TEAM_ASSUMPTION 7 %, диапазон 0–12 %"),
    ]


def tornado(case: Case, plan: Plan, scen: Scenario, A: dict, variations: Optional[list[Variation]] = None,
            metric: str = "discounted_expense_mln") -> list[dict]:
    variations = variations or standard_variations(scen)
    base_res = run(case, plan, scen, A, keep_daily=False)
    base_val = base_res.horizon[metric]
    rows = []
    for v in variations:
        out = {"parameter": v.name, "unit": v.unit, "basis": v.basis, "base_value": v.base, "base_metric": base_val}
        for tag, x in (("low", v.low), ("high", v.high)):
            s2, A2 = v.apply(scen, A, x)
            r = run(case, plan, s2, A2, keep_daily=False)
            out[f"{tag}_x"] = x
            out[f"{tag}_metric"] = r.horizon[metric]
            out[f"{tag}_delta"] = r.horizon[metric] - base_val
            out[f"{tag}_shortage_t"] = r.horizon["shortage_total_t"]
            out[f"{tag}_feasible"] = r.feasible
            out[f"{tag}_SL_min"] = r.horizon["SL_total_min"]
        out["swing"] = abs(out["high_metric"] - out["low_metric"])
        rows.append(out)
    rows.sort(key=lambda r: -r["swing"])
    return rows


def reverse_stress(case: Case, plan: Plan, scen: Scenario, A: dict, variation: Variation,
                   predicate: Callable[[RunResult], bool], lo: float, hi: float, steps: int = 12, refine: int = 12) -> dict:
    """Grid search first (no monotonicity assumed), then bisection inside the first failing interval.
    predicate(res) is True while the plan is acceptable."""
    grid = [lo + (hi - lo) * i / steps for i in range(steps + 1)]
    results = []
    first_bad = None
    prev_ok = None
    for x in grid:
        s2, A2 = variation.apply(scen, A, x)
        r = run(case, plan, s2, A2, keep_daily=False)
        ok = predicate(r)
        results.append({"x": x, "ok": ok, "shortage_t": r.horizon["shortage_total_t"], "pv_mln": r.horizon["discounted_expense_mln"],
                        "SL_min": r.horizon["SL_total_min"], "hard_violations": sum(1 for v in r.violations if v.severity == "hard")})
        if prev_ok is not None and prev_ok and not ok and first_bad is None:
            first_bad = (results[-2]["x"], x)
        prev_ok = ok
    threshold = None
    if first_bad:
        a, b = first_bad
        for _ in range(refine):
            m = (a + b) / 2
            s2, A2 = variation.apply(scen, A, m)
            r = run(case, plan, s2, A2, keep_daily=False)
            if predicate(r):
                a = m
            else:
                b = m
        threshold = b
    return {"parameter": variation.name, "unit": variation.unit, "grid": results, "threshold": threshold,
            "all_ok": all(r["ok"] for r in results), "none_ok": not any(r["ok"] for r in results)}
