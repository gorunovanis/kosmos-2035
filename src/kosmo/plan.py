"""Participant plan: reservations, orders, investments, policies. Load, save, validate.

The plan is a TEAM_DECISION envelope compatible with the organiser's plan.schema.json
(plan_id, scenario_id, decisions{supply_orders, capacity_reservations, investments,
inventory_policy}). Extra fields are documented in docs/architecture.md.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import calendar as cal


class PlanError(ValueError):
    """Raised for structural problems; message starts with a rule id."""


@dataclass
class Violation:
    rule_id: str
    period: str
    actual: float | str
    limit: float | str
    excess: float | str
    unit: str
    cause: str
    severity: str = "hard"
    scenario: str = ""

    def as_dict(self) -> dict:
        return {"rule_id": self.rule_id, "scenario": self.scenario, "period": self.period,
                "actual": self.actual, "limit": self.limit, "excess": self.excess,
                "unit": self.unit, "cause": self.cause, "severity": self.severity}


@dataclass
class Reservation:
    source_id: str
    year: int
    reserved: float
    start: Optional[str] = None
    end: Optional[str] = None


@dataclass
class Order:
    source_id: str
    volume: float
    year: Optional[int] = None
    start: Optional[str] = None
    end: Optional[str] = None
    role: str = "planned"         # planned | reactive | preparatory | insurance
    decided_on: Optional[str] = None
    cause: str = ""


@dataclass
class Investment:
    investment_id: str
    option_fee_date: Optional[str] = None
    exercise_date: Optional[str] = None
    decision_date: Optional[str] = None
    financing_date: Optional[str] = None
    lead_months: Optional[float] = None
    commissioning_date: Optional[str] = None


@dataclass
class Plan:
    plan_id: str
    scenario_id: str
    description: str = ""
    reservations: list[Reservation] = field(default_factory=list)
    orders: list[Order] = field(default_factory=list)
    investments: list[Investment] = field(default_factory=list)
    inventory_policy: dict = field(default_factory=dict)
    emergency_policy: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    # ---------- serialisation ----------
    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "scenario_id": self.scenario_id,
            "description": self.description,
            "decisions": {
                "capacity_reservations": [
                    {k: v for k, v in {"source_id": r.source_id, "year": r.year, "reserved_t_per_year": r.reserved,
                                       "start": r.start, "end": r.end}.items() if v is not None}
                    for r in self.reservations],
                "supply_orders": [
                    {k: v for k, v in {"source_id": o.source_id, "year": o.year, "volume_t": o.volume, "start": o.start,
                                       "end": o.end, "role": o.role, "decided_on": o.decided_on, "cause": o.cause or None}.items()
                     if v is not None}
                    for o in self.orders],
                "investments": [
                    {k: v for k, v in {"investment_id": i.investment_id, "option_fee_date": i.option_fee_date,
                                       "exercise_date": i.exercise_date, "decision_date": i.decision_date,
                                       "financing_date": i.financing_date, "lead_months": i.lead_months,
                                       "commissioning_date": i.commissioning_date}.items() if v is not None}
                    for i in self.investments],
                "inventory_policy": dict(self.inventory_policy),
                "emergency_policy": dict(self.emergency_policy),
            },
            "meta": dict(self.meta),
        }

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def from_dict(raw: dict) -> "Plan":
        errs = structural_errors(raw)
        if errs:
            raise PlanError("; ".join(errs))
        d = raw["decisions"]
        plan = Plan(plan_id=str(raw["plan_id"]), scenario_id=str(raw["scenario_id"]),
                    description=str(raw.get("description", "")),
                    inventory_policy=dict(d.get("inventory_policy") or {}),
                    emergency_policy=dict(d.get("emergency_policy") or {}),
                    meta=dict(raw.get("meta") or {}))
        for r in d.get("capacity_reservations", []):
            plan.reservations.append(Reservation(source_id=str(r["source_id"]), year=int(r["year"]),
                                                 reserved=float(r["reserved_t_per_year"]),
                                                 start=r.get("start"), end=r.get("end")))
        for o in d.get("supply_orders", []):
            plan.orders.append(Order(source_id=str(o["source_id"]), volume=float(o["volume_t"]),
                                     year=int(o["year"]) if o.get("year") is not None else None,
                                     start=o.get("start"), end=o.get("end"), role=str(o.get("role", "planned")),
                                     decided_on=o.get("decided_on"), cause=str(o.get("cause") or "")))
        for i in d.get("investments", []):
            plan.investments.append(Investment(investment_id=str(i["investment_id"]),
                                               option_fee_date=i.get("option_fee_date"),
                                               exercise_date=i.get("exercise_date"),
                                               decision_date=i.get("decision_date"),
                                               financing_date=i.get("financing_date"),
                                               lead_months=float(i["lead_months"]) if i.get("lead_months") is not None else None,
                                               commissioning_date=i.get("commissioning_date")))
        return plan

    @staticmethod
    def load(path: str | Path) -> "Plan":
        p = Path(path)
        if not p.exists():
            raise PlanError(f"FILE_NOT_FOUND: {p}")
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PlanError(f"INVALID_INPUT: {p.name} is not valid JSON ({exc})") from exc
        return Plan.from_dict(raw)

    def investment(self, investment_id: str) -> Optional[Investment]:
        for i in self.investments:
            if i.investment_id == investment_id:
                return i
        return None


def structural_errors(raw) -> list[str]:
    """Format/semantic checks that do not need the case. Each message starts with a rule id."""
    errs: list[str] = []
    if not isinstance(raw, dict):
        return ["INVALID_INPUT: plan must be a JSON object"]
    for key in ("plan_id", "scenario_id", "decisions"):
        if key not in raw or raw[key] in (None, ""):
            errs.append(f"INVALID_INPUT: missing required field '{key}'")
    d = raw.get("decisions")
    if not isinstance(d, dict):
        errs.append("INVALID_INPUT: 'decisions' must be an object")
        return errs
    for key in ("supply_orders", "capacity_reservations", "investments", "inventory_policy"):
        if key not in d:
            errs.append(f"INVALID_INPUT: decisions.{key} is missing")
    for n, r in enumerate(d.get("capacity_reservations") or []):
        if isinstance(r, dict) and "reserved_t_per_year" not in r and "reserved_capacity_t" in r:
            r["reserved_t_per_year"] = r["reserved_capacity_t"]   # organiser example field name (examples/)
        if not isinstance(r, dict) or "source_id" not in r or "year" not in r or "reserved_t_per_year" not in r:
            errs.append(f"INVALID_INPUT: capacity_reservations[{n}] needs source_id, year, reserved_t_per_year")
            continue
        try:
            v = float(r["reserved_t_per_year"])
        except (TypeError, ValueError):
            errs.append(f"INVALID_INPUT: capacity_reservations[{n}].reserved_t_per_year is not a number")
            continue
        if v < 0:
            errs.append(f"NEGATIVE_VALUE: capacity_reservations[{n}] source={r['source_id']} year={r['year']} reserved={v} minimum=0")
        for dk in ("start", "end"):
            if r.get(dk) is not None:
                try:
                    cal.parse_date(r[dk])
                except cal.DateError as exc:
                    errs.append(f"INVALID_INPUT: capacity_reservations[{n}].{dk}: {exc}")
    for n, o in enumerate(d.get("supply_orders") or []):
        if not isinstance(o, dict) or "source_id" not in o or "volume_t" not in o:
            errs.append(f"INVALID_INPUT: supply_orders[{n}] needs source_id and volume_t")
            continue
        try:
            v = float(o["volume_t"])
        except (TypeError, ValueError):
            errs.append(f"INVALID_INPUT: supply_orders[{n}].volume_t is not a number")
            continue
        if v < 0:
            errs.append(f"NEGATIVE_VALUE: supply_orders[{n}] source={o['source_id']} volume={v} minimum=0")
        if o.get("year") is None and (o.get("start") is None or o.get("end") is None):
            errs.append(f"INVALID_INPUT: supply_orders[{n}] needs year or start+end")
        for dk in ("start", "end", "decided_on"):
            if o.get(dk) is not None:
                try:
                    cal.parse_date(o[dk])
                except cal.DateError as exc:
                    errs.append(f"INVALID_INPUT: supply_orders[{n}].{dk}: {exc}")
        if o.get("start") and o.get("end"):
            try:
                if cal.to_index(o["end"]) < cal.to_index(o["start"]):
                    errs.append(f"INVALID_INPUT: supply_orders[{n}] end before start")
            except cal.DateError:
                pass
    for n, i in enumerate(d.get("investments") or []):
        if not isinstance(i, dict) or "investment_id" not in i:
            errs.append(f"INVALID_INPUT: investments[{n}] needs investment_id")
            continue
        for dk in ("option_fee_date", "exercise_date", "decision_date", "financing_date", "commissioning_date"):
            if i.get(dk) is not None:
                try:
                    cal.parse_date(i[dk])
                except cal.DateError as exc:
                    errs.append(f"INVALID_INPUT: investments[{n}].{dk}: {exc}")
        if i.get("lead_months") is not None:
            try:
                if float(i["lead_months"]) < 0:
                    errs.append(f"NEGATIVE_VALUE: investments[{n}].lead_months")
            except (TypeError, ValueError):
                errs.append(f"INVALID_INPUT: investments[{n}].lead_months is not a number")
    return errs
