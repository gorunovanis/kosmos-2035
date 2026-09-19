"""Loading of the organiser control inputs (CASE_INPUT) from data/case.

Nothing here decides a strategy. The files are read as published in the starter kit;
the loader only validates structure and records a SHA-256 of every input file.
"""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


class CaseError(ValueError):
    pass


@dataclass
class Source:
    source_id: str
    name: str
    capacity: float          # t/year
    var_cost: float          # mln per t
    res_rate: float          # mln per (t/year) reserved capacity, per year
    top_share: float         # take-or-pay share of reserved period volume
    lead_min: float
    lead_max: float
    lead_unit: str
    reliability_profile: str
    available_from_year: Optional[int]
    notes: str = ""


@dataclass
class Storage:
    storage_id: str
    name: str
    capacity: float
    loss_rate: float
    holding_cost: float      # mln per t-year of mean stock
    capex: float
    opex: float
    available_from_year: int


@dataclass
class InvestmentOption:
    investment_id: str
    name: str
    option_fee: float
    exercise_cost: float
    total_capex: float
    commissioning_rule: str
    opex: float


@dataclass
class DemandRow:
    year: int
    base_total: float
    base_critical: float
    low_total: float
    high_total: float


@dataclass
class ConstraintRow:
    constraint_id: str
    metric: str
    operator: str
    value: float
    unit: str
    period: str
    scenario: str
    severity: str
    description: str


@dataclass
class Case:
    root: Path
    sources: dict[str, Source]
    storages: dict[str, Storage]
    investments: dict[str, InvestmentOption]
    demand: dict[int, DemandRow]
    constraints: list[ConstraintRow]
    scenarios: dict[str, dict]
    file_hashes: dict[str, str] = field(default_factory=dict)

    @property
    def years(self) -> list[int]:
        return sorted(self.demand)

    def source_by_name(self, name: str) -> Source:
        for s in self.sources.values():
            if s.name == name or s.source_id == name:
                return s
        raise CaseError(f"unknown source {name!r}")

    def constraint_value(self, constraint_id: str) -> float:
        for c in self.constraints:
            if c.constraint_id == constraint_id:
                return c.value
        raise CaseError(f"constraint {constraint_id} not found in constraints.csv")


def _num(row: dict, key: str, path: str) -> float:
    raw = row.get(key, "")
    if raw is None or str(raw).strip() == "":
        raise CaseError(f"{path}: missing value for {key}")
    try:
        return float(raw)
    except ValueError as exc:
        raise CaseError(f"{path}: {key}={raw!r} is not a number") from exc


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise CaseError(f"{path}: empty CSV")
    return rows


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_case(root: str | Path) -> Case:
    root = Path(root)
    if not root.is_dir():
        raise CaseError(f"case directory not found: {root}")
    hashes: dict[str, str] = {}

    p = root / "supply_sources.csv"
    sources: dict[str, Source] = {}
    for r in _read_csv(p):
        sid = r["source_id"].strip()
        afy = r.get("available_from_year", "")
        sources[sid] = Source(
            source_id=sid,
            name=r["name"].strip(),
            capacity=_num(r, "capacity_t_per_year", p.name),
            var_cost=_num(r, "variable_cost_mln_per_t", p.name),
            res_rate=_num(r, "reservation_rate_mln_per_t_year_capacity", p.name),
            top_share=_num(r, "take_or_pay_share", p.name),
            lead_min=_num(r, "lead_time_min_value", p.name),
            lead_max=_num(r, "lead_time_max_value", p.name),
            lead_unit=r["lead_time_unit"].strip(),
            reliability_profile=r.get("reliability_profile", "").strip(),
            available_from_year=int(float(afy)) if str(afy).strip() else None,
            notes=r.get("notes", ""),
        )
        if sources[sid].lead_max < sources[sid].lead_min:
            raise CaseError(f"{p.name}: source {sid} lead_max < lead_min")
    hashes[p.name] = _sha(p)

    p = root / "storage_options.csv"
    storages: dict[str, Storage] = {}
    for r in _read_csv(p):
        storages[r["storage_id"].strip()] = Storage(
            storage_id=r["storage_id"].strip(),
            name=r["name"].strip(),
            capacity=_num(r, "capacity_t", p.name),
            loss_rate=_num(r, "loss_rate_on_throughput", p.name),
            holding_cost=_num(r, "holding_cost_mln_per_t_year", p.name),
            capex=_num(r, "capex_mln", p.name),
            opex=_num(r, "fixed_opex_mln_per_year", p.name),
            available_from_year=int(_num(r, "available_from_year", p.name)),
        )
    hashes[p.name] = _sha(p)
    if "BASE" not in storages or "ZBO" not in storages:
        raise CaseError("storage_options.csv must contain BASE and ZBO rows")

    p = root / "investment_options.csv"
    investments: dict[str, InvestmentOption] = {}
    for r in _read_csv(p):
        investments[r["investment_id"].strip()] = InvestmentOption(
            investment_id=r["investment_id"].strip(),
            name=r["name"].strip(),
            option_fee=_num(r, "option_fee_mln", p.name),
            exercise_cost=_num(r, "exercise_cost_mln", p.name),
            total_capex=_num(r, "total_capex_mln", p.name),
            commissioning_rule=r.get("commissioning_rule", ""),
            opex=_num(r, "fixed_opex_mln_per_year", p.name),
        )
    hashes[p.name] = _sha(p)

    p = root / "demand.csv"
    demand: dict[int, DemandRow] = {}
    for r in _read_csv(p):
        y = int(_num(r, "year", p.name))
        row = DemandRow(
            year=y,
            base_total=_num(r, "base_total_t", p.name),
            base_critical=_num(r, "base_critical_t", p.name),
            low_total=_num(r, "low_total_t", p.name),
            high_total=_num(r, "high_total_t", p.name),
        )
        if row.base_critical > row.base_total + 1e-12:
            raise CaseError(f"demand.csv: critical demand exceeds total in {y}")
        demand[y] = row
    hashes[p.name] = _sha(p)
    ys = sorted(demand)
    if ys != list(range(ys[0], ys[-1] + 1)):
        raise CaseError("demand.csv: years must be contiguous")

    p = root / "constraints.csv"
    constraints: list[ConstraintRow] = []
    for r in _read_csv(p):
        constraints.append(ConstraintRow(
            constraint_id=r["constraint_id"].strip(),
            metric=r["metric"].strip(),
            operator=r["operator"].strip(),
            value=_num(r, "value", p.name),
            unit=r.get("unit", ""),
            period=r.get("period", ""),
            scenario=r.get("scenario", ""),
            severity=r.get("severity", "hard"),
            description=r.get("description", ""),
        ))
    hashes[p.name] = _sha(p)

    scenarios: dict[str, dict] = {}
    for yp in sorted(root.glob("*.yaml")):
        raw = yaml.safe_load(yp.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or "scenario_id" not in raw:
            raise CaseError(f"{yp.name}: scenario file without scenario_id")
        scenarios[raw["scenario_id"]] = raw
        hashes[yp.name] = _sha(yp)

    return Case(root=root, sources=sources, storages=storages, investments=investments,
                demand=demand, constraints=constraints, scenarios=scenarios, file_hashes=hashes)


def case_fingerprint(case: Case) -> str:
    """Single hash over all input files (provenance for exports)."""
    h = hashlib.sha256()
    for name in sorted(case.file_hashes):
        h.update(name.encode("utf-8"))
        h.update(case.file_hashes[name].encode("ascii"))
    return h.hexdigest()


def load_expected_checks(root: str | Path) -> list[dict]:
    p = Path(root) / "expected_checks.json"
    return json.loads(p.read_text(encoding="utf-8"))
