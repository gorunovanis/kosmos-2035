"""Exports: CSV set and one XLSX workbook, same numbers as the UI (same RunResult)."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from .engine import RunResult

YEARLY_COLUMNS = [
    "year", "scenario_id", "plan_id", "demand_total_t", "demand_critical_t", "required_opening_reserve_t",
    "opening_inventory_t", "scheduled_t", "delivered_t", "losses_t", "loss_ratio", "served_total_t", "served_critical_t",
    "shortage_total_t", "shortage_critical_t", "closing_inventory_t", "SL_total", "SL_critical", "mean_inventory_t",
    "peak_before_losses_t", "first_shortage_date", "shortage_days", "procurement_mln", "reservation_mln", "holding_mln",
    "opex_zbo_mln", "opex_isru_mln", "capex_mln", "cumulative_capex_mln", "preparation_cost_mln", "total_expense_mln",
    "discount_factor", "discounted_expense_mln", "cost_per_served_t_mln", "pv_per_served_t_mln",
]
CHECK_COLUMNS = ["rule_id", "scenario", "period", "status", "actual", "operator", "limit", "margin", "unit", "severity", "cause"]
VIOL_COLUMNS = ["rule_id", "scenario", "period", "actual", "limit", "excess", "unit", "cause", "severity"]
SOURCE_COLUMNS = ["year", "source_id", "source", "reserved_t_per_year", "contract_period_fraction", "scheduled_t", "delivered_t",
                  "top_minimum_t", "paid_quantity_t", "paid_unused_t", "unit_price_mln_per_t", "procurement_mln",
                  "reservation_rate_mln_per_t_year", "reservation_mln"]
DAILY_COLUMNS = ["date", "year", "opening_t", "inflow_scheduled_t", "inflow_actual_t", "losses_t", "stock_after_inflow_t",
                 "served_critical_t", "served_other_t", "shortage_t", "closing_t", "storage_capacity_t", "regime"]


def _round(v, nd=6):
    if isinstance(v, float):
        return round(v, nd)
    return v


def _write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: _round(r.get(c)) for c in columns})


def canonical_hash(res: RunResult) -> str:
    """Hash of the numbers only (no timestamps): yearly, source-year, checks."""
    payload = {
        "yearly": [[_round(r.get(c)) for c in YEARLY_COLUMNS] for r in res.yearly],
        "source_year": [[_round(r.get(c)) for c in SOURCE_COLUMNS] for r in res.source_year],
        "checks": [[_round(r.get(c)) for c in CHECK_COLUMNS] for r in res.checks],
        "horizon": {k: _round(v) for k, v in res.horizon.items()},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def export_run(res: RunResult, out_dir: str | Path, assumptions_rows: list[dict] | None = None,
               risk_rows: list[dict] | None = None, code_version: str = "", case_fingerprint: str = "",
               write_daily: bool = True, xlsx: bool = True) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_csv(out / "yearly_balance.csv", res.yearly, YEARLY_COLUMNS)
    _write_csv(out / "source_schedule.csv", res.source_year, SOURCE_COLUMNS)
    _write_csv(out / "constraint_checks.csv", res.checks, CHECK_COLUMNS)
    _write_csv(out / "violations.csv", res.violations_dicts(), VIOL_COLUMNS)
    if write_daily:
        _write_csv(out / "inventory_trace.csv", res.daily, DAILY_COLUMNS)
    fin_cols = ["year", "procurement_mln", "reservation_mln", "holding_mln", "opex_zbo_mln", "opex_isru_mln", "capex_mln",
                "preparation_cost_mln", "total_expense_mln", "discount_factor", "discounted_expense_mln",
                "cost_per_served_t_mln", "pv_per_served_t_mln"]
    _write_csv(out / "financial_breakdown.csv", res.yearly, fin_cols)
    if assumptions_rows:
        _write_csv(out / "assumptions.csv", assumptions_rows, ["id", "name", "value", "unit", "basis", "scope", "status"])
    if risk_rows:
        _write_csv(out / "risk_register.csv", risk_rows, list(risk_rows[0].keys()))
    h = canonical_hash(res)
    meta = {
        "scenario_id": res.scenario_id, "plan_id": res.plan_id, "feasible": res.feasible,
        "units": res.meta.get("units"), "years": res.years, "preparatory_year": res.meta.get("preparatory_year"),
        "assumptions_reference": "assumptions.csv / configs/assumptions.yaml",
        "assumptions": res.meta.get("assumptions"), "scenario_changes": res.meta.get("scenario_changes"),
        "capex_events": res.meta.get("capex_events"), "commissioning": {
            "ZBO": res.meta.get("zbo_commissioning"), "Earth-New": res.meta.get("earth_new_commissioning"),
            "Lunar-ISRU": res.meta.get("isru_commissioning")},
        "horizon": res.horizon, "canonical_hash": h, "code_version": code_version, "case_fingerprint": case_fingerprint,
        "n_violations_hard": sum(1 for v in res.violations if v.severity == "hard"),
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if xlsx:
        try:
            _write_xlsx(out / "export.xlsx", res, meta, assumptions_rows or [], risk_rows or [], write_daily)
        except ImportError:
            pass
    return meta


def _write_xlsx(path: Path, res: RunResult, meta: dict, assumptions_rows, risk_rows, write_daily: bool) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "meta"
    ws.append(["key", "value"])
    for k in ("scenario_id", "plan_id", "feasible", "canonical_hash", "code_version", "case_fingerprint", "assumptions_reference"):
        ws.append([k, str(meta.get(k))])
    ws.append(["years", ", ".join(str(y) for y in meta.get("years", []))])
    ws.append(["preparatory_year", str(meta.get("preparatory_year"))])
    for k, v in (meta.get("units") or {}).items():
        ws.append([f"unit.{k}", v])
    for k, v in (meta.get("commissioning") or {}).items():
        ws.append([f"commissioning.{k}", str(v)])
    for ch in meta.get("scenario_changes") or []:
        ws.append(["scenario_change", ch])
    for k, v in (meta.get("assumptions") or {}).items():
        ws.append([f"assumption.{k}", str(v)])
    for k, v in (meta.get("horizon") or {}).items():
        ws.append([f"horizon.{k}", v])

    def sheet(name, rows, cols):
        w = wb.create_sheet(name)
        w.append(cols)
        for r in rows:
            w.append([_round(r.get(c)) for c in cols])

    sheet("yearly_balance", res.yearly, YEARLY_COLUMNS)
    sheet("source_schedule", res.source_year, SOURCE_COLUMNS)
    fin_cols = ["year", "procurement_mln", "reservation_mln", "holding_mln", "opex_zbo_mln", "opex_isru_mln", "capex_mln",
                "preparation_cost_mln", "total_expense_mln", "discount_factor", "discounted_expense_mln",
                "cost_per_served_t_mln", "pv_per_served_t_mln"]
    sheet("financial_breakdown", res.yearly, fin_cols)
    sheet("constraint_checks", res.checks, CHECK_COLUMNS)
    sheet("violations", res.violations_dicts(), VIOL_COLUMNS)
    if assumptions_rows:
        sheet("assumptions", assumptions_rows, ["id", "name", "value", "unit", "basis", "scope", "status"])
    if risk_rows:
        sheet("risk_register", risk_rows, list(risk_rows[0].keys()))
    if write_daily:
        sheet("inventory_trace", res.daily, DAILY_COLUMNS)
    wb.save(path)
