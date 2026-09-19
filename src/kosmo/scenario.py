"""Scenarios: organiser BASE / MANDATORY_STRESS, derived LOW/HIGH demand checks,
team research scenarios (TEAM_*), and geopolitical event overlays.

A scenario changes the environment of a calculation. It never changes the plan.
Effective parameters are produced per year and per source by `effective()`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .case import Case, CaseError


def _per_year(spec, years: list[int], default: float = 1.0) -> dict[int, float]:
    """Expand a YAML mapping ({year: x} or {default: x} or scalar) into per-year values."""
    out = {y: default for y in years}
    if spec is None:
        return out
    if isinstance(spec, (int, float)):
        return {y: float(spec) for y in years}
    if isinstance(spec, dict):
        d = spec.get("default", default)
        out = {y: float(d) for y in years}
        for k, v in spec.items():
            if k == "default":
                continue
            try:
                yk = int(k)
            except (TypeError, ValueError):
                raise CaseError(f"scenario: year key {k!r} is not an integer")
            if yk in out:
                out[yk] = float(v)
        return out
    raise CaseError(f"scenario: cannot interpret {spec!r}")


@dataclass
class Scenario:
    scenario_id: str
    label: str = ""
    status: str = "TEAM_ASSUMPTION"
    demand_multiplier: dict = field(default_factory=dict)
    critical_demand_multiplier: Optional[dict] = None
    variable_price_multiplier: dict = field(default_factory=dict)     # {source name: {year: k}}
    reservation_rate_multiplier: dict = field(default_factory=dict)   # {source name: {year: k}}
    capacity_multiplier: dict = field(default_factory=dict)           # {source name: {year: k}}
    actual_delivery_share: dict = field(default_factory=dict)         # {source name: {year: share}}
    loss_ceiling: dict = field(default_factory=dict)
    demand_override: Optional[dict] = None    # {"total": {year: t}, "critical": {year: t}} for LOW/HIGH
    notes: list = field(default_factory=list)
    changes: list = field(default_factory=list)   # human readable list of what differs from BASE
    parent: Optional[str] = None

    @staticmethod
    def from_dict(raw: dict) -> "Scenario":
        if not isinstance(raw, dict) or not raw.get("scenario_id"):
            raise CaseError("INVALID_INPUT: scenario without scenario_id")
        return Scenario(
            scenario_id=str(raw["scenario_id"]),
            label=str(raw.get("label_ru", raw.get("label", ""))),
            status=str(raw.get("status", "TEAM_ASSUMPTION")),
            demand_multiplier=raw.get("demand_multiplier") or {},
            critical_demand_multiplier=raw.get("critical_demand_multiplier"),
            variable_price_multiplier=raw.get("variable_price_multiplier") or {},
            reservation_rate_multiplier=raw.get("reservation_rate_multiplier") or {},
            capacity_multiplier=raw.get("capacity_multiplier") or {},
            actual_delivery_share=raw.get("actual_delivery_share") or {},
            loss_ceiling=raw.get("loss_ceiling") or {},
            notes=list(raw.get("notes") or []),
            changes=list(raw.get("changes") or []),
            parent=raw.get("parent"),
        )


@dataclass
class Effective:
    """Per-year, per-source parameters after the scenario is applied."""
    scenario_id: str
    years: list[int]
    demand_total: dict[int, float]
    demand_critical: dict[int, float]
    price: dict[str, dict[int, float]]          # by source_id
    res_rate: dict[str, dict[int, float]]
    capacity: dict[str, dict[int, float]]
    delivery_share: dict[str, dict[int, float]]
    loss_ceiling_enabled: bool
    loss_ceiling_from_year: Optional[int]
    loss_ceiling_max: Optional[float]
    changes: list[str]


def builtin_scenarios(case: Case) -> dict[str, Scenario]:
    """BASE and MANDATORY_STRESS from the organiser YAML, plus LOW_DEMAND / HIGH_DEMAND
    derived from demand.csv (sensitivity checks, critical share preserved per year)."""
    out: dict[str, Scenario] = {}
    for sid, raw in case.scenarios.items():
        out[sid] = Scenario.from_dict(raw)
    years = case.years
    for tag, col in (("LOW_DEMAND", "low_total"), ("HIGH_DEMAND", "high_total")):
        total = {y: getattr(case.demand[y], col) for y in years}
        crit = {}
        for y in years:
            base = case.demand[y]
            ratio = (base.base_critical / base.base_total) if base.base_total > 0 else 0.0
            crit[y] = total[y] * ratio
        out[tag] = Scenario(
            scenario_id=tag,
            label="Низкий спрос" if tag == "LOW_DEMAND" else "Высокий спрос",
            status="CASE_INPUT",
            demand_override={"total": total, "critical": crit},
            notes=["Sensitivity check from demand.csv; critical share of the base year is preserved (Постановка с. 6–7)."],
            changes=[f"demand {tag.lower()} from demand.csv, critical share preserved"],
        )
    return out


def effective(case: Case, scen: Scenario, years: Optional[list[int]] = None) -> Effective:
    years = years or case.years
    dm = _per_year(scen.demand_multiplier, years)
    cm = _per_year(scen.critical_demand_multiplier, years) if scen.critical_demand_multiplier is not None else dm
    demand_total, demand_crit = {}, {}
    for y in years:
        row = case.demand.get(y)
        if scen.demand_override:
            demand_total[y] = float(scen.demand_override["total"][y])
            demand_crit[y] = float(scen.demand_override["critical"][y])
        elif row is None:
            raise CaseError(f"no demand row for year {y}")
        else:
            demand_total[y] = row.base_total * dm[y]
            demand_crit[y] = row.base_critical * cm[y]
        if demand_crit[y] > demand_total[y] + 1e-9:
            raise CaseError(f"scenario {scen.scenario_id}: critical demand exceeds total in {y}")

    def by_source(spec: dict, default: float) -> dict[str, dict[int, float]]:
        res = {sid: {y: default for y in years} for sid in case.sources}
        for key, val in (spec or {}).items():
            if key == "default":
                for sid in res:
                    res[sid] = _per_year(val, years, default)
                continue
            src = case.source_by_name(str(key))
            res[src.source_id] = _per_year(val, years, default)
        return res

    price_mult = by_source(scen.variable_price_multiplier, 1.0)
    res_mult = by_source(scen.reservation_rate_multiplier, 1.0)
    cap_mult = by_source(scen.capacity_multiplier, 1.0)
    share = by_source(scen.actual_delivery_share, 1.0)

    price = {sid: {y: case.sources[sid].var_cost * price_mult[sid][y] for y in years} for sid in case.sources}
    res_rate = {sid: {y: case.sources[sid].res_rate * res_mult[sid][y] for y in years} for sid in case.sources}
    capacity = {sid: {y: case.sources[sid].capacity * cap_mult[sid][y] for y in years} for sid in case.sources}

    lc = scen.loss_ceiling or {}
    enabled = bool(lc.get("enabled", False))
    changes = list(scen.changes)
    if not changes:
        for y in years:
            if abs(dm[y] - 1.0) > 1e-12:
                changes.append(f"{y}: demand x{dm[y]:g}")
        for sid in case.sources:
            for y in years:
                if abs(price_mult[sid][y] - 1.0) > 1e-12:
                    changes.append(f"{y}: {case.sources[sid].name} price x{price_mult[sid][y]:g}")
                if abs(share[sid][y] - 1.0) > 1e-12:
                    changes.append(f"{y}: {case.sources[sid].name} actual delivery {share[sid][y]:g} of plan")
        if enabled:
            changes.append(f"loss ceiling {lc.get('max_losses_divided_by_throughput')} from {lc.get('from_year')}")
    return Effective(
        scenario_id=scen.scenario_id, years=years,
        demand_total=demand_total, demand_critical=demand_crit,
        price=price, res_rate=res_rate, capacity=capacity, delivery_share=share,
        loss_ceiling_enabled=enabled,
        loss_ceiling_from_year=int(lc["from_year"]) if enabled and "from_year" in lc else None,
        loss_ceiling_max=float(lc["max_losses_divided_by_throughput"]) if enabled and "max_losses_divided_by_throughput" in lc else None,
        changes=changes,
    )


def apply_geo_event(base: Scenario, event: dict, case: Case) -> Scenario:
    """Overlay a geopolitical research event on a scenario (works on a copy).

    event = {event_label, affected_sources: [names], component: variable_price|reservation_rate|capacity,
             start_year, end_year, multiplier (or multiplier_low/high), basis}
    Combination rule (explicit): multipliers multiply the scenario's own multiplier for the
    same component; the same effect is never applied twice because every event is listed once.
    """
    import copy
    scen = copy.deepcopy(base)
    comp = event.get("component", "variable_price")
    key = {"variable_price": "variable_price_multiplier",
           "reservation_rate": "reservation_rate_multiplier",
           "capacity": "capacity_multiplier"}.get(comp)
    if key is None:
        raise CaseError(f"INVALID_INPUT: unknown price component {comp!r}")
    k = float(event.get("multiplier", 1.0))
    y0, y1 = int(event["start_year"]), int(event["end_year"])
    if y1 < y0:
        raise CaseError("INVALID_INPUT: end_year before start_year")
    if k < 0:
        raise CaseError("INVALID_INPUT: negative multiplier")
    table = getattr(scen, key)
    for name in event.get("affected_sources", []):
        src = case.source_by_name(str(name))
        per = _per_year(table.get(src.name), case.years)
        for y in range(y0, y1 + 1):
            if y in per:
                per[y] = per[y] * k
        table[src.name] = {y: per[y] for y in case.years}
    setattr(scen, key, table)
    scen.scenario_id = f"{base.scenario_id}+GEO:{event.get('event_label', 'event')}"
    scen.status = "TEAM_ASSUMPTION"
    scen.parent = base.scenario_id
    scen.changes = list(base.changes) + [
        f"GEO {event.get('event_label')}: {comp} x{k:g} for {', '.join(event.get('affected_sources', []))} in {y0}-{y1}; basis: {event.get('basis', 'TEAM_ASSUMPTION')}"
    ]
    return scen
