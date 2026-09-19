"""Regenerate results/ from the current code: every plan under BASE and MANDATORY_STRESS (+ LOW/HIGH for
the chosen plan), the comparison sheet, the price-of-protection sheet, the risk register, the extension
checks (Source-X and 2041 on data copies) and the sensitivity tables. Usage: python tools/make_results.py"""
from __future__ import annotations

import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from kosmo.api import CASE_DIR, CONFIG_DIR, PROJECT_ROOT, RESULTS_DIR, all_scenarios, code_version, load_assumptions  # noqa: E402
from kosmo.case import case_fingerprint, load_case  # noqa: E402
from kosmo.compare import price_of_protection, summarize, write_comparison  # noqa: E402
from kosmo.engine import run  # noqa: E402
from kosmo.export import export_run  # noqa: E402
from kosmo.plan import Plan  # noqa: E402
from kosmo.planner import build_plan  # noqa: E402
from kosmo.risks import evaluate_risks, load_risks, mcda_profiles, stakeholder_table  # noqa: E402
from kosmo.sensitivity import reverse_stress, standard_variations, tornado  # noqa: E402

CHOSEN = "S1_new24"


def write_csv(path: Path, rows: list[dict]) -> None:
    import csv
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 6) if isinstance(v, float) else v) for k, v in r.items()})


def main() -> int:
    case = load_case(CASE_DIR)
    params, arows = load_assumptions()
    scen = all_scenarios(case)
    ver = code_version()
    fp = case_fingerprint(case)
    RESULTS_DIR.mkdir(exist_ok=True)
    plans = {p.stem: Plan.load(p) for p in sorted((CONFIG_DIR / "plans").glob("*.json"))}
    risks = load_risks(CONFIG_DIR / "risks")

    # 1. every plan under BASE and MANDATORY_STRESS; chosen plan also LOW/HIGH
    summary_rows = []
    for name, plan in plans.items():
        scen_ids = ["BASE", "MANDATORY_STRESS"] + (["LOW_DEMAND", "HIGH_DEMAND"] if name.startswith(CHOSEN) else [])
        for sid in scen_ids:
            res = run(case, plan, scen[sid], params)
            out = RESULTS_DIR / f"{name}__{sid}"
            risk_rows = evaluate_risks(case, plan, scen[sid], params, risks) if (name == CHOSEN and sid in ("BASE", "MANDATORY_STRESS")) else None
            export_run(res, out, assumptions_rows=arows, risk_rows=risk_rows, code_version=ver, case_fingerprint=fp, write_daily=(name.startswith(CHOSEN)))
            (out / "plan.json").write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            s = summarize(res, case)
            s["strategy"] = plan.meta.get("strategy") or name.split("_stress")[0]
            summary_rows.append(s)
            print(f"{name:34s} {sid:16s} feasible={res.feasible!s:5s} PV={res.horizon['discounted_expense_mln']:9.1f} short={res.horizon['shortage_total_t']:7.2f}")
    write_comparison(summary_rows, RESULTS_DIR, "comparison")
    write_comparison(price_of_protection(summary_rows), RESULTS_DIR, "price_of_protection")

    # 2. stakeholders + MCDA sensitivity for the chosen plan
    res_b = run(case, plans[CHOSEN], scen["BASE"], params, keep_daily=False)
    write_csv(RESULTS_DIR / "stakeholders_BASE.csv", stakeholder_table(res_b, case))
    res_s = run(case, plans[f"{CHOSEN}_stress_prepared"], scen["MANDATORY_STRESS"], params, keep_daily=False)
    write_csv(RESULTS_DIR / "stakeholders_STRESS_prepared.csv", stakeholder_table(res_s, case))
    write_csv(RESULTS_DIR / "mcda_profiles.csv", mcda_profiles(str(CASE_DIR), json.dumps(params, sort_keys=True)))

    # 3. sensitivity for the chosen plan in BASE and for the prepared plan in stress
    for name, sid in ((CHOSEN, "BASE"), (f"{CHOSEN}_stress_prepared", "MANDATORY_STRESS")):
        rows = tornado(case, plans[name], scen[sid], params)
        write_csv(RESULTS_DIR / f"sensitivity_{name}__{sid}.csv", rows)
        thresholds = []
        for v in standard_variations(scen[sid]):
            if v.param == "rate":
                continue
            hi = v.high * 1.6 if v.param != "isru_share" else 1.0
            lo = v.low if v.param != "isru_share" else 0.0
            out = reverse_stress(case, plans[name], scen[sid], params, v, lambda r: r.feasible, lo, hi)
            thresholds.append({"plan": name, "scenario": sid, "parameter": v.name, "criterion": "план неисполним", "threshold": out["threshold"],
                               "all_ok_in_range": out["all_ok"], "none_ok_in_range": out["none_ok"], "range": f"{lo:g}..{hi:g}"})
            out2 = reverse_stress(case, plans[name], scen[sid], params, v, lambda r: r.horizon["shortage_total_t"] < 1e-6, lo, hi)
            thresholds.append({"plan": name, "scenario": sid, "parameter": v.name, "criterion": "дефицит > 0", "threshold": out2["threshold"],
                               "all_ok_in_range": out2["all_ok"], "none_ok_in_range": out2["none_ok"], "range": f"{lo:g}..{hi:g}"})
        write_csv(RESULTS_DIR / f"reverse_stress_{name}__{sid}.csv", thresholds)

    # 4. extension checks on copies: Source-X (over-capacity example + a plan using X) and 2041
    sx_dir = PROJECT_ROOT / "data" / "copies" / "source_x"
    sx_case = load_case(sx_dir)
    raw = json.loads((PROJECT_ROOT / "data" / "examples" / "invalid_plan_examples" / "over_capacity.json").read_text(encoding="utf-8"))
    raw["decisions"]["capacity_reservations"][0]["source_id"] = "X"
    res = run(sx_case, Plan.from_dict(raw), all_scenarios(sx_case)["BASE"], params, keep_daily=False)
    export_run(res, RESULTS_DIR / "extension_source_x__over_capacity_example", assumptions_rows=arows, code_version=ver,
               case_fingerprint=case_fingerprint(sx_case), write_daily=False)
    raw2 = plans[CHOSEN].to_dict()
    raw2["plan_id"] = f"{CHOSEN}_with_source_x"
    raw2["decisions"]["capacity_reservations"] += [{"source_id": "X", "year": y, "reserved_t_per_year": 10.0} for y in range(2036, 2041)]
    raw2["decisions"]["supply_orders"] += [{"source_id": "X", "year": y, "volume_t": 10.0, "role": "planned"} for y in range(2036, 2041)]
    res = run(sx_case, Plan.from_dict(raw2), all_scenarios(sx_case)["BASE"], params, keep_daily=False)
    export_run(res, RESULTS_DIR / "extension_source_x__S1_plus_X", assumptions_rows=arows, code_version=ver, case_fingerprint=case_fingerprint(sx_case), write_daily=False)
    (RESULTS_DIR / "extension_source_x__S1_plus_X" / "plan.json").write_text(json.dumps(raw2, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Source-X: plan feasible={res.feasible} delivered X={sum(r['delivered_by_source'].get('X', 0) for r in res.yearly):.1f} t")

    h_dir = PROJECT_ROOT / "data" / "copies" / "horizon_2041"
    h_case = load_case(h_dir)
    from build_plans import STRATEGIES  # noqa: E402
    (CONFIG_DIR / "plans_copies").mkdir(exist_ok=True)
    for strat in (CHOSEN, "S3"):
        spec = STRATEGIES[strat]
        spec41 = replace(spec, reservations={sid: {**yrs, 2041: list(yrs.values())[-1]} for sid, yrs in spec.reservations.items()})
        for sid in ("BASE", "MANDATORY_STRESS"):
            plan41, rep = build_plan(h_case, all_scenarios(h_case)[sid], spec41, f"{strat}_h2041_{sid}", params)
            plan41.save(CONFIG_DIR / "plans_copies" / f"{strat}_h2041_{sid}.json")
            res = run(h_case, plan41, all_scenarios(h_case)[sid], params, keep_daily=False)
            out = RESULTS_DIR / f"extension_2041__{strat}__{sid}"
            export_run(res, out, assumptions_rows=arows, code_version=ver, case_fingerprint=case_fingerprint(h_case), write_daily=False)
            (out / "plan.json").write_text(json.dumps(plan41.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"2041 {strat} {sid}: feasible={res.feasible} PV={res.horizon['discounted_expense_mln']:.1f} shortage={res.horizon['shortage_total_t']:.2f} warnings={rep.warnings}")

    # 5. invalid demo plan for the jury route (step 7): chosen plan without Earth-New
    raw3 = plans[CHOSEN].to_dict()
    raw3["plan_id"] = "invalid_demo_no_earth_new"
    raw3["description"] = "Заведомо неисполнимый план для проверки: S1 без опциона Earth-New (заказы Earth-New остаются в плане и не могут быть поставлены)."
    raw3["decisions"]["investments"] = [i for i in raw3["decisions"]["investments"] if i["investment_id"] != "EARTH_NEW"]
    raw3["meta"] = {"strategy": "invalid_demo", "purpose": "jury route step 7: deliberately infeasible plan"}
    (CONFIG_DIR / "plans" / "invalid_demo_no_earth_new.json").write_text(json.dumps(raw3, ensure_ascii=False, indent=2), encoding="utf-8")
    res = run(case, Plan.from_dict(raw3), scen["BASE"], params, keep_daily=False)
    export_run(res, RESULTS_DIR / "invalid_demo_no_earth_new__BASE", assumptions_rows=arows, code_version=ver, case_fingerprint=fp, write_daily=False)
    print(f"invalid demo: feasible={res.feasible} violations={[v.rule_id + '@' + v.period for v in res.violations][:6]}")
    (RESULTS_DIR / "INDEX.md").write_text(index_md(), encoding="utf-8")
    return 0


def index_md() -> str:
    return """# results/

Каждая папка `<план>__<сценарий>/` — один прогон ядра: `yearly_balance.csv`, `source_schedule.csv`, `financial_breakdown.csv`,
`constraint_checks.csv` (все правила с PASS/FAIL), `violations.csv`, `inventory_trace.csv` (дневной след; в репозитории не хранится из-за
размера, генерируется командой ниже, а для выбранного плана лежит листом `inventory_trace` в `export.xlsx`),
`assumptions.csv`, `risk_register.csv` (для выбранного плана), `meta.json` (сценарий, план, единицы, допущения, даты ввода, хэш чисел, версия кода),
`plan.json` (план для повторного открытия), `export.xlsx` (те же листы).

Сводки: `comparison.csv/xlsx` (все планы × сценарии), `price_of_protection.csv/xlsx`, `stakeholders_*.csv`, `mcda_profiles.csv`,
`sensitivity_*.csv`, `reverse_stress_*.csv`, `extension_*` (Source-X и 2041 на копиях), `invalid_demo_*` (заведомо неисполнимый план).

Пересборка: `python tools/make_results.py`. Числа в интерфейсе, выгрузках и записке берутся отсюда.
"""


if __name__ == "__main__":
    raise SystemExit(main())
