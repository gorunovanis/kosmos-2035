"""Digest of the numbers used in README, записка and slides. Everything is read from results/ so that
the documents never contain a hand-typed figure. Usage: python tools/numbers.py [--md docs/numbers.md]"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
CHOSEN = "S1_new24"


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def digest() -> dict:
    comp = read_csv(RES / "comparison.csv")
    pop = read_csv(RES / "price_of_protection.csv")
    by = {(r["plan_id"], r["scenario_id"]): r for r in comp}
    N = {"chosen": CHOSEN}
    for key, (plan, scen) in {"base": (CHOSEN, "BASE"), "fixed": (CHOSEN, "MANDATORY_STRESS"),
                              "prepared": (f"{CHOSEN}_stress_prepared", "MANDATORY_STRESS"),
                              "reactive": (f"{CHOSEN}_stress_reactive", "MANDATORY_STRESS"),
                              "low": (CHOSEN, "LOW_DEMAND"), "high": (CHOSEN, "HIGH_DEMAND"),
                              "prepared_high": (f"{CHOSEN}_stress_prepared", "HIGH_DEMAND")}.items():
        r = by.get((plan, scen))
        if r:
            N[key] = {k: (num(v) if k not in ("plan_id", "scenario_id", "feasible", "violations", "strategy") else v) for k, v in r.items()}
    N["strategies"] = {r["strategy"]: r for r in pop}
    N["comparison"] = comp
    for tag, plan, scen in (("yearly_base", CHOSEN, "BASE"), ("yearly_fixed", CHOSEN, "MANDATORY_STRESS"),
                            ("yearly_prepared", f"{CHOSEN}_stress_prepared", "MANDATORY_STRESS")):
        p = RES / f"{plan}__{scen}" / "yearly_balance.csv"
        N[tag] = [{k: (num(v) if k not in ("first_shortage_date", "scenario_id", "plan_id") else v) for k, v in r.items()} for r in read_csv(p)] if p.exists() else []
        meta = RES / f"{plan}__{scen}" / "meta.json"
        if meta.exists():
            N[tag + "_meta"] = json.loads(meta.read_text(encoding="utf-8"))
    N["risks_base"] = read_csv(RES / f"{CHOSEN}__BASE" / "risk_register.csv") if (RES / f"{CHOSEN}__BASE" / "risk_register.csv").exists() else []
    N["risks_stress"] = read_csv(RES / f"{CHOSEN}__MANDATORY_STRESS" / "risk_register.csv") if (RES / f"{CHOSEN}__MANDATORY_STRESS" / "risk_register.csv").exists() else []
    N["sens_base"] = read_csv(RES / f"sensitivity_{CHOSEN}__BASE.csv")
    N["sens_prepared"] = read_csv(RES / f"sensitivity_{CHOSEN}_stress_prepared__MANDATORY_STRESS.csv")
    N["rs_base"] = read_csv(RES / f"reverse_stress_{CHOSEN}__BASE.csv")
    N["rs_prepared"] = read_csv(RES / f"reverse_stress_{CHOSEN}_stress_prepared__MANDATORY_STRESS.csv")
    N["mcda"] = read_csv(RES / "mcda_profiles.csv")
    N["stake_base"] = read_csv(RES / "stakeholders_BASE.csv")
    for tag in ("extension_2041__S1_new24__BASE", "extension_2041__S1_new24__MANDATORY_STRESS", "extension_source_x__S1_plus_X", "invalid_demo_no_earth_new__BASE"):
        m = RES / tag / "meta.json"
        if m.exists():
            N[tag] = json.loads(m.read_text(encoding="utf-8"))
    return N


def fmt(x, nd=0):
    if x is None:
        return "—"
    s = f"{x:,.{nd}f}".replace(",", " ").replace(".", ",")
    return s


def to_markdown(N: dict) -> str:
    L = []
    L.append(f"# Числа из results/ (план {N['chosen']})\n")
    b, f_, p, r = N["base"], N["fixed"], N["prepared"], N["reactive"]
    L.append("## Выбранный план в сценариях\n")
    L.append("| Прогон | Исполним | PV, млн | Расходы, млн | Дефицит, т | SL общий min | Тонна, млн/т | CAPEX, млн |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for name, x in (("BASE (план под базу)", b), ("STRESS без адаптации", f_), ("STRESS, план подготовлен заранее", p), ("STRESS, реакция после 01.01.2038", r),
                    ("LOW_DEMAND (план под базу)", N.get("low")), ("HIGH_DEMAND (план под базу)", N.get("high")), ("HIGH_DEMAND (подготовленный план)", N.get("prepared_high"))):
        if not x:
            continue
        L.append(f"| {name} | {'да' if x['feasible']=='True' else 'нет'} | {fmt(x['discounted_expense_mln'])} | {fmt(x['total_expense_mln'])} | {fmt(x['shortage_total_t'],1)} | {fmt(100*x['SL_total_min'],1)} % | {fmt(x['cost_per_served_t_mln'],2)} | {fmt(x['cumulative_capex_mln'])} |")
    L.append("\n## Цена защиты по стратегиям\n")
    L.append("| Стратегия | PV BASE | CAPEX | Дефицит без адаптации, т | PV подготовленного стресса | Подготовленный исполним | PV реакции | Цена защиты | Цена запоздалой реакции |")
    L.append("|---|---:|---:|---:|---:|---|---:|---:|---:|")
    for s, x in N["strategies"].items():
        L.append(f"| {s} | {fmt(num(x['base_pv_mln']))} | {fmt(num(x['capex_mln']))} | {fmt(num(x['stress_fixed_shortage_t']),1)} | {fmt(num(x['stress_prepared_pv_mln']))} | {x['stress_prepared_feasible']} | {fmt(num(x['stress_reactive_pv_mln']))} | {fmt(num(x['price_of_protection_pv_mln']))} | {fmt(num(x['cost_of_late_reaction_pv_mln']))} |")
    L.append("\n## Баланс выбранного плана по годам (BASE)\n")
    L.append("| Год | Спрос | Резерв 45 дн | Запас 1 янв | Доставлено | Потери | Выдано | Дефицит | Запас конец | SL общ | Расходы | PV |")
    L.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for y in N["yearly_base"]:
        L.append(f"| {int(y['year'])} | {fmt(y['demand_total_t'],1)} | {fmt(y['required_opening_reserve_t'],1)} | {fmt(y['opening_inventory_t'],1)} | {fmt(y['delivered_t'],1)} | {fmt(y['losses_t'],2)} | {fmt(y['served_total_t'],1)} | {fmt(y['shortage_total_t'],1)} | {fmt(y['closing_inventory_t'],1)} | {fmt(100*y['SL_total'],1)} % | {fmt(y['total_expense_mln'])} | {fmt(y['discounted_expense_mln'])} |")
    L.append("\n## Баланс подготовленного плана по годам (MANDATORY_STRESS)\n")
    L.append("| Год | Спрос | Резерв 45 дн | Запас 1 янв | Доставлено | Потери | Потери/оборот | Выдано | Дефицит | Запас конец | Расходы | PV |")
    L.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for y in N["yearly_prepared"]:
        L.append(f"| {int(y['year'])} | {fmt(y['demand_total_t'],1)} | {fmt(y['required_opening_reserve_t'],1)} | {fmt(y['opening_inventory_t'],1)} | {fmt(y['delivered_t'],1)} | {fmt(y['losses_t'],2)} | {fmt(100*y['loss_ratio'],1)} % | {fmt(y['served_total_t'],1)} | {fmt(y['shortage_total_t'],1)} | {fmt(y['closing_inventory_t'],1)} | {fmt(y['total_expense_mln'])} | {fmt(y['discounted_expense_mln'])} |")
    L.append("\n## Тот же план без адаптации в стрессе\n")
    L.append("| Год | Спрос | Резерв 45 дн | Запас 1 янв | Выдано | Дефицит | SL общ | Первый дефицит | Дней с дефицитом |")
    L.append("|---:|---:|---:|---:|---:|---:|---:|---|---:|")
    for y in N["yearly_fixed"]:
        L.append(f"| {int(y['year'])} | {fmt(y['demand_total_t'],1)} | {fmt(y['required_opening_reserve_t'],1)} | {fmt(y['opening_inventory_t'],1)} | {fmt(y['served_total_t'],1)} | {fmt(y['shortage_total_t'],1)} | {fmt(100*y['SL_total'],1)} % | {y['first_shortage_date'] or '—'} | {int(y['shortage_days'] or 0)} |")
    L.append("\n## Реестр рисков (BASE, план под базу)\n")
    L.append("| ID | Событие | Δ PV, млн | Δ дефицит, т | Исполним | Мера: стоимость, млн PV | Остаточный дефицит, т | Остаточный Δ PV |")
    L.append("|---|---|---:|---:|---|---:|---:|---:|")
    for x in N["risks_base"]:
        L.append(f"| {x['risk_id']} | {x['event']} | {fmt(num(x['delta_pv_mln']))} | {fmt(num(x['delta_shortage_t']),1)} | {x['feasible']} | {fmt(num(x['mitigation_cost_pv_mln']))} | {fmt(num(x['residual_shortage_t']),1)} | {fmt(num(x['residual_pv_mln']))} |")
    L.append("\n## Чувствительность (торнадо) BASE\n")
    L.append("| Параметр | Низ | Δ PV низ | Дефицит низ | Верх | Δ PV верх | Дефицит верх |")
    L.append("|---|---:|---:|---:|---:|---:|---:|")
    for x in N["sens_base"]:
        L.append(f"| {x['parameter']} | {x['low_x']} | {fmt(num(x['low_delta']))} | {fmt(num(x['low_shortage_t']),1)} | {x['high_x']} | {fmt(num(x['high_delta']))} | {fmt(num(x['high_shortage_t']),1)} |")
    L.append("\n## Пороги обратного стресса\n")
    L.append("| План/сценарий | Параметр | Критерий | Порог | Диапазон |")
    L.append("|---|---|---|---:|---|")
    for x in N["rs_base"] + N["rs_prepared"]:
        thr = x["threshold"]
        L.append(f"| {x['plan']} / {x['scenario']} | {x['parameter']} | {x['criterion']} | {thr if thr else ('не ломается' if x['all_ok_in_range']=='True' else 'ломается на всём диапазоне')} | {x['range']} |")
    L.append("\n## Профили весов (чувствительность ранжирования)\n")
    for x in N["mcda"]:
        L.append(f"- {x['Профиль']}: {x['Ранжирование']} (веса {x['Веса (PV / дефицит / CAPEX / гибкость)']})")
    for tag in ("extension_2041__S1_new24__BASE", "extension_2041__S1_new24__MANDATORY_STRESS", "extension_source_x__S1_plus_X", "invalid_demo_no_earth_new__BASE"):
        m = N.get(tag)
        if m:
            h = m["horizon"]
            L.append(f"\n- {tag}: исполним {m['feasible']}, PV {fmt(h['discounted_expense_mln'])}, дефицит {fmt(h['shortage_total_t'],1)} т, жёстких нарушений {m['n_violations_hard']}")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    N = digest()
    md = to_markdown(N)
    if "--md" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--md") + 1])
        out.write_text(md, encoding="utf-8")
        print(f"written {out}")
    else:
        print(md)
