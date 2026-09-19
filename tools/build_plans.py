"""Generate the strategy plans S0–S3 (BASE-planned and stress-prepared) into configs/plans and run
them under BASE and MANDATORY_STRESS. Usage: python tools/build_plans.py"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kosmo.api import CASE_DIR, CONFIG_DIR, RESULTS_DIR, get_scenario, load_assumptions  # noqa: E402
from kosmo.case import load_case  # noqa: E402
from kosmo.engine import run  # noqa: E402
from kosmo.planner import StrategySpec, build_plan  # noqa: E402

YEARS = list(range(2035, 2041))


def full(sid_years: dict[str, tuple[int, int]], levels: dict[str, float]) -> dict[str, dict[int, float]]:
    out = {}
    for sid, (y0, y1) in sid_years.items():
        out[sid] = {y: levels[sid] for y in range(y0, y1 + 1)}
    return out


NEW18 = {"investment_id": "EARTH_NEW", "option_fee_date": "2035-01-15", "exercise_date": "2035-07-01", "lead_months": 18,
         "commissioning_date": "2037-01-01"}
NEW24 = {"investment_id": "EARTH_NEW", "option_fee_date": "2035-01-15", "exercise_date": "2035-07-01", "lead_months": 24}
ZBO36 = {"investment_id": "ZBO", "decision_date": "2036-01-01", "lead_months": 0}
ISRU37 = {"investment_id": "LUNAR_ISRU", "financing_date": "2037-06-01"}

STRATEGIES = {
    "S0": StrategySpec(
        strategy_id="S0", label="S0: Core + Flex + ZBO, Emergency as planned base in 2039-2040 (no new supply CAPEX)",
        reservations=full({"A": (2035, 2040), "B": (2035, 2040), "E": (2035, 2040)}, {"A": 190, "B": 110, "E": 80}),
        investments=[ZBO36], fill_priority=["A", "B", "E"], planned_emergency_years=[2039, 2040]),
    "S0min": StrategySpec(
        strategy_id="S0min", label="S0-min: Core + Flex + ZBO only, Emergency insurance, no terminal reserve (fragile minimum)",
        reservations=full({"A": (2035, 2040), "B": (2035, 2040), "E": (2035, 2040)}, {"A": 190, "B": 110, "E": 80}),
        investments=[ZBO36], fill_priority=["A", "B"], terminal_reserve=False),
    "S1_new18": StrategySpec(
        strategy_id="S1_new18", label="S1: Core + Flex + ZBO + Earth-New (18 months, from 2037-01-01)",
        reservations=full({"A": (2035, 2040), "B": (2035, 2040), "C": (2037, 2040), "E": (2035, 2040)},
                          {"A": 190, "B": 110, "C": 130, "E": 80}),
        investments=[NEW18, ZBO36], fill_priority=["A", "C", "B"]),
    "S1_new24": StrategySpec(
        strategy_id="S1_new24", label="S1: Core + Flex + ZBO + Earth-New (24 months, from 2037-07-01)",
        reservations=full({"A": (2035, 2040), "B": (2035, 2040), "C": (2037, 2040), "E": (2035, 2040)},
                          {"A": 190, "B": 110, "C": 130, "E": 80}),
        investments=[NEW24, ZBO36], fill_priority=["A", "C", "B"]),
    "S1_new24_margin10": StrategySpec(
        strategy_id="S1_new24_margin10", label="S1 (24 months) with a 10 % safety margin above the 45-day reserve",
        reservations=full({"A": (2035, 2040), "B": (2035, 2040), "C": (2037, 2040), "E": (2035, 2040)},
                          {"A": 190, "B": 110, "C": 130, "E": 80}),
        investments=[NEW24, ZBO36], fill_priority=["A", "C", "B"], reserve_margin_share=0.10),
    "S2": StrategySpec(
        strategy_id="S2", label="S2: Core + Flex + ZBO + Lunar-ISRU (financed 2037-06-01, from 2038)",
        reservations=full({"A": (2035, 2040), "B": (2035, 2040), "E": (2035, 2040)}, {"A": 190, "B": 110, "E": 80}),
        investments=[ISRU37, ZBO36], fill_priority=["D", "A", "B"]),
    "S3": StrategySpec(
        strategy_id="S3", label="S3: Core + Flex + ZBO + Earth-New (18 months) + Lunar-ISRU (CAPEX 1790)",
        reservations=full({"A": (2035, 2040), "B": (2035, 2040), "C": (2037, 2040), "E": (2035, 2040)},
                          {"A": 190, "B": 110, "C": 130, "E": 80}),
        investments=[NEW18, ISRU37, ZBO36], fill_priority=["D", "A", "C", "B"]),
}


def main() -> int:
    case = load_case(CASE_DIR)
    params, _ = load_assumptions()
    out_dir = CONFIG_DIR / "plans"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for sid, spec in STRATEGIES.items():
        base_plan = None
        for plan_scen, suffix in (("BASE", ""), ("MANDATORY_STRESS", "_stress_prepared"), ("MANDATORY_STRESS", "_stress_reactive")):
            scen = get_scenario(case, plan_scen)
            plan_id = f"{sid}{suffix}"
            if suffix == "_stress_reactive":
                if base_plan is None:
                    continue
                fixed = {(o.source_id, o.year): o.volume for o in base_plan.orders if o.year is not None}
                rspec = replace(spec, reaction_from="2038-01-01", reactive_sources=["B", "E"],
                                fill_priority=[s for s in spec.fill_priority if s in ("B", "E")] + (["E"] if "E" not in spec.fill_priority else []),
                                label=spec.label + " — reaction after observing the stress on 2038-01-01 (Flex +122 d, Emergency +42 d)")
                plan, rep = build_plan(case, scen, rspec, plan_id, params, fixed_orders=fixed)
            else:
                plan, rep = build_plan(case, scen, spec, plan_id, params)
                if suffix == "":
                    base_plan = plan
            path = out_dir / f"{plan_id}.json"
            plan.save(path)
            for run_scen in ("BASE", "MANDATORY_STRESS"):
                res = run(case, plan, get_scenario(case, run_scen), params, keep_daily=False)
                h = res.horizon
                hard = [v for v in res.violations if v.severity == "hard"]
                summary.append((plan_id, run_scen, res.feasible, h["total_expense_mln"], h["discounted_expense_mln"],
                                h["shortage_total_t"], h["cumulative_capex_mln"], h["closing_inventory_t"],
                                "; ".join(sorted({f"{v.rule_id}@{v.period}" for v in hard})[:4])))
            if rep.warnings:
                print(f"[{plan_id}] planner warnings: " + " | ".join(rep.warnings))
    print(f"{'plan':32s} {'run':16s} {'feas':5s} {'total':>10s} {'PV':>10s} {'short':>8s} {'capex':>7s} {'end':>7s}  violations")
    for row in summary:
        print(f"{row[0]:32s} {row[1]:16s} {str(row[2]):5s} {row[3]:10.1f} {row[4]:10.1f} {row[5]:8.2f} {row[6]:7.0f} {row[7]:7.2f}  {row[8]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
