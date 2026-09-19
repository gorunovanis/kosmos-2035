"""Command line entry: python -m kosmo <command>.

  run       --plan configs/plans/S1_new18.json --scenario BASE [--out results/S1_new18_BASE] [--no-daily]
  vectors   print organiser control vectors V01-V10 against expected_checks.json
  validate  --plan file.json   structural + case validation without running
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .api import CASE_DIR, PROJECT_ROOT, RESULTS_DIR, run_and_export
from .case import load_case, load_expected_checks
from .plan import Plan, PlanError
from .vectors import run_vectors


def _cmd_run(args) -> int:
    plan_path = Path(args.plan)
    out = Path(args.out) if args.out else RESULTS_DIR / f"{plan_path.stem}_{args.scenario}"
    try:
        res, meta = run_and_export(plan_path, args.scenario, out, case_dir=Path(args.case) if args.case else None,
                                   write_daily=not args.no_daily)
    except PlanError as exc:
        print(f"PLAN ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"plan={res.plan_id} scenario={res.scenario_id} feasible={res.feasible} hash={meta['canonical_hash'][:12]}")
    print(f"{'year':>5} {'demand':>8} {'deliv':>8} {'loss':>6} {'served':>8} {'short':>7} {'SLt':>6} {'SLc':>6} {'open':>7} {'close':>7} {'cost':>9} {'PV':>9}")
    for r in res.yearly:
        print(f"{r['year']:>5} {r['demand_total_t']:8.2f} {r['delivered_t']:8.2f} {r['losses_t']:6.2f} {r['served_total_t']:8.2f} "
              f"{r['shortage_total_t']:7.2f} {r['SL_total']:6.3f} {r['SL_critical']:6.3f} {r['opening_inventory_t']:7.2f} "
              f"{r['closing_inventory_t']:7.2f} {r['total_expense_mln']:9.2f} {r['discounted_expense_mln']:9.2f}")
    h = res.horizon
    print(f"horizon: total={h['total_expense_mln']:.3f} PV={h['discounted_expense_mln']:.3f} served={h['served_total_t']:.3f} "
          f"shortage={h['shortage_total_t']:.3f} capex={h['cumulative_capex_mln']:.1f} cost/t={h['cost_per_served_t_mln']:.4f}")
    if res.violations:
        print("violations:")
        for v in res.violations:
            print(f"  {v.rule_id} period={v.period} actual={v.actual} limit={v.limit} excess={v.excess} {v.unit} [{v.severity}] {v.cause}")
    else:
        print("violations: none")
    print(f"exported to {out}")
    return 0 if res.feasible else 1


def _cmd_vectors(args) -> int:
    expected = load_expected_checks(CASE_DIR)
    actual = run_vectors()
    ok = True
    for item in expected:
        cid = item["case_id"]
        exp = item["expected"]
        got = actual.get(cid, {})
        for k, v in exp.items():
            g = got.get(k)
            match = (abs(float(g) - float(v)) < 1e-9) if isinstance(v, (int, float)) else (g == v)
            ok &= bool(match)
            print(f"{cid} {k}: expected={v} actual={g} {'PASS' if match else 'FAIL'}")
    print("ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


def _cmd_validate(args) -> int:
    from .api import load_assumptions, get_scenario
    from .engine import run
    try:
        plan = Plan.load(args.plan)
    except PlanError as exc:
        print(f"INVALID: {exc}")
        return 2
    case = load_case(Path(args.case) if args.case else CASE_DIR)
    params, _ = load_assumptions()
    res = run(case, plan, get_scenario(case, args.scenario), params, keep_daily=False)
    print(f"plan={plan.plan_id} scenario={args.scenario} feasible={res.feasible}")
    for v in res.violations:
        print(f"  {v.rule_id} period={v.period} actual={v.actual} limit={v.limit} excess={v.excess} {v.unit} [{v.severity}] {v.cause}")
    return 0 if res.feasible else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="kosmo", description="Fuel node planning core (Топливный космоконтур 2035)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a plan under a scenario and export CSV/XLSX")
    r.add_argument("--plan", required=True)
    r.add_argument("--scenario", default="BASE")
    r.add_argument("--out")
    r.add_argument("--case", help="alternative case directory (copy for Source-X / 2041)")
    r.add_argument("--no-daily", action="store_true")
    r.set_defaults(func=_cmd_run)
    v = sub.add_parser("vectors", help="organiser control vectors V01-V10")
    v.set_defaults(func=_cmd_vectors)
    val = sub.add_parser("validate", help="validate a plan without exporting")
    val.add_argument("--plan", required=True)
    val.add_argument("--scenario", default="BASE")
    val.add_argument("--case")
    val.set_defaults(func=_cmd_validate)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
