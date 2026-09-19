"""Risk register as executable scenarios, stakeholder table and MCDA ranking sensitivity.

A risk file (configs/risks/*.yaml) describes: event, cause, affected parameter, period, basis of the
range, owner, dependencies, the scenario overlay (same keys as a scenario YAML plus optional
plan_patch), and a mitigation (plan_patch applied on top). Consequences are computed by the engine."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml

from .case import Case
from .engine import run
from .plan import Plan
from .scenario import Scenario, effective


def load_risks(folder: Path) -> list[dict]:
    out = []
    if not folder.is_dir():
        return out
    for p in sorted(folder.glob("*.yaml")):
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and raw.get("risk_id"):
            out.append(raw)
    return out


def _overlay(scen: Scenario, overlay: dict) -> Scenario:
    s = copy.deepcopy(scen)
    for key in ("demand_multiplier", "critical_demand_multiplier", "variable_price_multiplier", "reservation_rate_multiplier",
                "capacity_multiplier", "actual_delivery_share"):
        if key in overlay:
            cur = getattr(s, key)
            if key in ("demand_multiplier", "critical_demand_multiplier"):
                base = dict(cur) if isinstance(cur, dict) else {"default": cur or 1.0}
                for k, v in overlay[key].items():
                    base[k] = float(base.get(k, base.get("default", 1.0))) * float(v)
                setattr(s, key, base)
            else:
                table = dict(cur or {})
                for src, per in overlay[key].items():
                    base = dict(table.get(src, {}) or {})
                    if isinstance(base, (int, float)):
                        base = {"default": base}
                    for k, v in per.items():
                        base[k] = float(base.get(k, base.get("default", 1.0))) * float(v)
                    table[src] = base
                setattr(s, key, table)
    s.scenario_id = f"{scen.scenario_id}+{overlay.get('tag', 'risk')}"
    s.status = "TEAM_ASSUMPTION"
    return s


def _patch_plan(plan: Plan, patch: dict | None, case: Case | None = None, scen: Scenario | None = None, A: dict | None = None) -> Plan:
    if not patch:
        return plan
    if patch.get("replan_with_planner") and case is not None and scen is not None:
        from .planner import build_plan, spec_from_plan
        spec = spec_from_plan(case, plan, strategy_id=plan.meta.get("strategy", plan.plan_id))
        plan, _ = build_plan(case, scen, spec, plan.plan_id + "+replan", A or {})
    raw = plan.to_dict()
    d = raw["decisions"]
    for o in patch.get("add_orders", []):
        d["supply_orders"].append(dict(o))
    for r in patch.get("add_reservations", []):
        d["capacity_reservations"].append(dict(r))
    for inv in patch.get("set_investments", []):
        d["investments"] = [i for i in d["investments"] if i["investment_id"] != inv["investment_id"]] + [dict(inv)]
    for iid in patch.get("remove_investments", []):
        d["investments"] = [i for i in d["investments"] if i["investment_id"] != iid]
    for o in patch.get("scale_orders", []):
        for so in d["supply_orders"]:
            if so["source_id"] == o["source_id"] and (o.get("year") is None or so.get("year") == o.get("year")):
                so["volume_t"] = float(so["volume_t"]) * float(o["factor"])
    raw["plan_id"] = plan.plan_id + "+" + patch.get("tag", "mitigation")
    return Plan.from_dict(raw)


def evaluate_risks(case: Case, plan: Plan, scen: Scenario, A: dict, risks: list[dict]) -> list[dict]:
    base = run(case, plan, scen, A, keep_daily=False)
    rows = []
    for rk in risks:
        ov = rk.get("scenario_overlay") or {}
        s_risk = _overlay(scen, dict(ov, tag=rk["risk_id"]))
        p_risk = _patch_plan(plan, rk.get("plan_patch"), case, s_risk, A)
        r = run(case, p_risk, s_risk, A, keep_daily=False)
        row = {
            "risk_id": rk["risk_id"], "event": rk.get("event", ""), "cause": rk.get("cause", ""),
            "affected_parameter": rk.get("affected_parameter", ""), "period": rk.get("period", ""),
            "probability_basis": rk.get("probability_basis", ""), "owner": rk.get("owner", ""), "dependencies": rk.get("dependencies", ""),
            "base_pv_mln": base.horizon["discounted_expense_mln"], "risk_pv_mln": r.horizon["discounted_expense_mln"],
            "delta_pv_mln": r.horizon["discounted_expense_mln"] - base.horizon["discounted_expense_mln"],
            "delta_shortage_t": r.horizon["shortage_total_t"] - base.horizon["shortage_total_t"],
            "shortage_critical_t": r.horizon["shortage_critical_t"], "SL_total_min": r.horizon["SL_total_min"], "feasible": r.feasible,
            "violations": "; ".join(sorted({f"{v.rule_id}@{v.period}" for v in r.violations if v.severity == "hard"})),
            "mitigation": (rk.get("mitigation") or {}).get("text", ""),
        }
        mit = rk.get("mitigation") or {}
        if mit.get("plan_patch") or mit.get("scenario_overlay"):
            s_mit = _overlay(s_risk, dict(mit.get("scenario_overlay") or {}, tag="mitigated")) if mit.get("scenario_overlay") else s_risk
            p_mit = _patch_plan(p_risk, dict(mit.get("plan_patch") or {}, tag="mitigated"), case, s_mit, A)
            m = run(case, p_mit, s_mit, A, keep_daily=False)
            row["mitigation_violations"] = "; ".join(sorted({f"{v.rule_id}@{v.period}" for v in m.violations if v.severity == "hard"}))
            row["mitigation_cost_pv_mln"] = m.horizon["discounted_expense_mln"] - r.horizon["discounted_expense_mln"]
            row["residual_shortage_t"] = m.horizon["shortage_total_t"] - base.horizon["shortage_total_t"]
            row["residual_pv_mln"] = m.horizon["discounted_expense_mln"] - base.horizon["discounted_expense_mln"]
            row["residual_feasible"] = m.feasible
        else:
            row["mitigation_cost_pv_mln"] = None
            row["residual_shortage_t"] = None
            row["residual_pv_mln"] = None
            row["residual_feasible"] = None
        rows.append(row)
    return rows


def stakeholder_table(res, case: Case) -> list[dict]:
    h = res.horizon
    e = case.source_by_name("Emergency").source_id
    b = case.source_by_name("Earth-Flex").source_id
    reserved_paid = sum(r["reservation_mln"] for r in res.source_year)
    unused_paid = sum(r["paid_unused_t"] * r["unit_price_mln_per_t"] for r in res.source_year)
    return [
        {"Сторона": "Оператор узла", "Интерес": "исполнимый план, гибкость, контроль стоимости", "Показатель": f"жёстких нарушений {sum(1 for v in res.violations if v.severity == 'hard')}; PV {h['discounted_expense_mln']:,.0f} млн; свободный Flex {sum(max(0.0, r['reserved_t_per_year'] * r['contract_period_fraction'] - r['scheduled_t']) for r in res.source_year if r['source_id'] == b):,.0f} т".replace(",", " "),
         "Обязательство / кто платит": "резервы, take-or-pay, хранение, OPEX; несёт цену защиты"},
        {"Сторона": "Критические потребители", "Интерес": "SL критический ≥ 0,99, резерв 45 дней", "Показатель": f"SL крит. min {100 * h['SL_critical_min']:.1f} %; дефицит крит. {h['shortage_critical_t']:.1f} т",
         "Обязательство / кто платит": "получают топливо первыми при дефиците (правило выдачи A9); риск несут только при исчерпании запаса"},
        {"Сторона": "Коммерческие потребители", "Интерес": "SL общий ≥ 0,97, цена тонны", "Показатель": f"SL общий min {100 * h['SL_total_min']:.1f} %; дефицит {h['shortage_total_t']:.1f} т; тонна {h['cost_per_served_t_mln']:.2f} млн/т" if h["cost_per_served_t_mln"] else "—",
         "Обязательство / кто платит": "первыми получают дефицит в стрессе; оплачивают тонну по стоимости обеспечения"},
        {"Сторона": "Поставщики топлива и запусков", "Интерес": "зарезервированный и оплаченный объём, take-or-pay", "Показатель": f"платежи за резерв {reserved_paid:,.0f} млн; оплачено сверх отбора {unused_paid:,.0f} млн".replace(",", " "),
         "Обязательство / кто платит": "держат мощность; получают take-or-pay даже при снижении отбора; отвечают за срок поставки (карточки договоров)"},
        {"Сторона": "Финансирующая сторона", "Интерес": "CAPEX внутри лимитов, приведённые расходы, срок ввода", "Показатель": f"CAPEX {h['cumulative_capex_mln']:,.0f} млн (лимит 1 800 к 2037, 2 800 к 2040); PV {h['discounted_expense_mln']:,.0f} млн".replace(",", " "),
         "Обязательство / кто платит": "финансирует опцион Earth-New, ZBO, ISRU; несёт риск задержки ввода и невозврата CAPEX внутри горизонта"},
    ]


PROFILES = {
    "Оператор": {"pv": 0.4, "shortage": 0.3, "capex": 0.15, "flex": 0.15},
    "Критический потребитель": {"pv": 0.1, "shortage": 0.6, "capex": 0.1, "flex": 0.2},
    "Коммерческий потребитель": {"pv": 0.5, "shortage": 0.3, "capex": 0.1, "flex": 0.1},
    "Финансирующая сторона": {"pv": 0.4, "shortage": 0.1, "capex": 0.45, "flex": 0.05},
    "Поставщик": {"pv": 0.2, "shortage": 0.2, "capex": 0.2, "flex": 0.4},
}


def mcda_profiles(case_dir: str, params_json: str) -> list[dict]:
    """Ranking of stress-prepared strategies under different weight profiles (sensitivity only)."""
    from .api import CONFIG_DIR, all_scenarios
    from .case import load_case
    cc = load_case(case_dir)
    params = json.loads(params_json)
    scen = all_scenarios(cc)
    cands = []
    for p in sorted((CONFIG_DIR / "plans").glob("*_stress_prepared.json")):
        plan = Plan.load(p)
        rs = run(cc, plan, scen["MANDATORY_STRESS"], params, keep_daily=False)
        base_plan_path = p.with_name(p.name.replace("_stress_prepared", ""))
        rb = run(cc, Plan.load(base_plan_path), scen["BASE"], params, keep_daily=False) if base_plan_path.exists() else rs
        if rs.horizon["shortage_critical_t"] > 1e-6 or not rs.feasible or not rb.feasible:
            continue   # hard critical-service constraint is not weighted away
        flex = sum(max(0.0, r["reserved_t_per_year"] * r["contract_period_fraction"] - r["scheduled_t"]) for r in rs.source_year if r["source_id"] == "B")
        cands.append({"strategy": plan.meta.get("strategy") or p.stem, "pv": rb.horizon["discounted_expense_mln"] + rs.horizon["discounted_expense_mln"],
                      "shortage": rs.horizon["shortage_total_t"], "capex": rs.horizon["cumulative_capex_mln"], "flex": -flex})
    if not cands:
        return []
    keys = ["pv", "shortage", "capex", "flex"]
    lo = {k: min(c[k] for c in cands) for k in keys}
    hi = {k: max(c[k] for c in cands) for k in keys}
    def norm(c, k):
        return 0.0 if hi[k] - lo[k] < 1e-12 else (c[k] - lo[k]) / (hi[k] - lo[k])   # 0 = best (all criteria are "less is better")
    out = []
    for name, w in PROFILES.items():
        scored = sorted(cands, key=lambda c: sum(w[k] * norm(c, k) for k in keys))
        out.append({"Профиль": name, "Веса (PV / дефицит / CAPEX / гибкость)": " / ".join(f"{w[k]:.2f}" for k in keys),
                    "Ранжирование": " > ".join(c["strategy"] for c in scored),
                    "Лучший": scored[0]["strategy"]})
    return out
