"""Comparison of plans and scenarios on one data base, one discount rate, one method.

Comparison rows are produced by the same engine run used by the UI and the exports."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

from .case import Case
from .engine import RunResult, run
from .plan import Plan
from .scenario import Scenario

COMPARE_COLUMNS = [
    "plan_id", "strategy", "scenario_id", "feasible", "hard_violations", "reference_breaches",
    "total_expense_mln", "discounted_expense_mln", "cost_per_served_t_mln", "pv_per_served_t_mln",
    "served_total_t", "demand_total_t", "shortage_total_t", "shortage_critical_t", "SL_total_min", "SL_critical_min",
    "cumulative_capex_mln", "capex_through_2037_mln", "capex_headroom_2037_mln", "closing_inventory_t",
    "min_reserve_margin_t", "unused_flex_t", "unused_emergency_t", "procurement_mln", "reservation_mln",
    "holding_mln", "opex_mln", "capex_mln", "violations",
]


def summarize(res: RunResult, case: Case) -> dict:
    hard = [v for v in res.violations if v.severity == "hard"]
    ref = [v for v in res.violations if v.severity == "reference"]
    capex37 = next((r["cumulative_capex_mln"] for r in res.yearly if r["year"] == 2037), res.horizon["cumulative_capex_mln"])
    reserve_margins = [c["margin"] for c in res.checks if c["rule_id"] == "RESERVE_45D"]
    b = case.source_by_name("Earth-Flex").source_id
    e = case.source_by_name("Emergency").source_id
    unused_b = sum(max(0.0, r["reserved_t_per_year"] * r["contract_period_fraction"] - r["scheduled_t"]) for r in res.source_year if r["source_id"] == b)
    unused_e = sum(max(0.0, r["reserved_t_per_year"] * r["contract_period_fraction"] - r["scheduled_t"]) for r in res.source_year if r["source_id"] == e)
    h = res.horizon
    return {
        "plan_id": res.plan_id, "strategy": res.meta.get("strategy") or res.plan_id.split("_")[0], "scenario_id": res.scenario_id,
        "feasible": res.feasible, "hard_violations": len(hard), "reference_breaches": len(ref),
        "total_expense_mln": h["total_expense_mln"], "discounted_expense_mln": h["discounted_expense_mln"],
        "cost_per_served_t_mln": h["cost_per_served_t_mln"], "pv_per_served_t_mln": h["pv_per_served_t_mln"],
        "served_total_t": h["served_total_t"], "demand_total_t": h["demand_total_t"],
        "shortage_total_t": h["shortage_total_t"], "shortage_critical_t": h["shortage_critical_t"],
        "SL_total_min": h["SL_total_min"], "SL_critical_min": h["SL_critical_min"],
        "cumulative_capex_mln": h["cumulative_capex_mln"], "capex_through_2037_mln": capex37,
        "capex_headroom_2037_mln": case.constraint_value("CAPEX_2037") - capex37,
        "closing_inventory_t": h["closing_inventory_t"],
        "min_reserve_margin_t": min(reserve_margins) if reserve_margins else None,
        "unused_flex_t": unused_b, "unused_emergency_t": unused_e,
        "procurement_mln": h["procurement_mln"], "reservation_mln": h["reservation_mln"], "holding_mln": h["holding_mln"],
        "opex_mln": h["opex_mln"], "capex_mln": h["capex_mln"],
        "violations": "; ".join(sorted({f"{v.rule_id}@{v.period}" for v in hard})),
    }


def compare(case: Case, plans: list[Plan], scenarios: list[Scenario], assumptions: dict) -> list[dict]:
    rows = []
    for plan in plans:
        for scen in scenarios:
            res = run(case, plan, scen, assumptions, keep_daily=False)
            rows.append(summarize(res, case))
    return rows


def price_of_protection(rows: list[dict]) -> list[dict]:
    """For each strategy: BASE-planned cost in BASE vs the prepared plan cost in stress."""
    by = {}
    for r in rows:
        if str(r.get("strategy", "")).startswith("invalid"):
            continue
        by.setdefault(r["strategy"], {})[(r["plan_id"], r["scenario_id"])] = r
    out = []
    for strat, d in by.items():
        base = next((v for (p, s), v in d.items() if s == "BASE" and not p.endswith(("_stress_prepared", "_stress_reactive"))), None)
        fixed = next((v for (p, s), v in d.items() if s == "MANDATORY_STRESS" and not p.endswith(("_stress_prepared", "_stress_reactive"))), None)
        prep = next((v for (p, s), v in d.items() if s == "MANDATORY_STRESS" and p.endswith("_stress_prepared")), None)
        react = next((v for (p, s), v in d.items() if s == "MANDATORY_STRESS" and p.endswith("_stress_reactive")), None)
        if base is None:
            continue
        out.append({
            "strategy": strat,
            "base_pv_mln": base["discounted_expense_mln"], "base_feasible": base["feasible"], "capex_mln": base["cumulative_capex_mln"],
            "stress_fixed_shortage_t": fixed["shortage_total_t"] if fixed else None,
            "stress_fixed_SL_total_min": fixed["SL_total_min"] if fixed else None,
            "stress_prepared_pv_mln": prep["discounted_expense_mln"] if prep else None,
            "stress_prepared_feasible": prep["feasible"] if prep else None,
            "stress_reactive_pv_mln": react["discounted_expense_mln"] if react else None,
            "stress_reactive_feasible": react["feasible"] if react else None,
            "price_of_protection_pv_mln": (prep["discounted_expense_mln"] - base["discounted_expense_mln"]) if prep else None,
            "cost_of_late_reaction_pv_mln": (react["discounted_expense_mln"] - prep["discounted_expense_mln"]) if (prep and react) else None,
        })
    return out


def write_comparison(rows: list[dict], out_dir: Path, name: str = "comparison") -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    cols = list(rows[0].keys()) if rows else COMPARE_COLUMNS
    with (out_dir / f"{name}.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: (round(v, 6) if isinstance(v, float) else v) for c, v in r.items()})
    try:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = name
        ws.append(cols)
        for r in rows:
            ws.append([(round(v, 6) if isinstance(v, float) else v) for v in (r.get(c) for c in cols)])
        wb.save(out_dir / f"{name}.xlsx")
    except ImportError:
        pass
