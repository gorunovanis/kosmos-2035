"""Rule-based schedule builder (TEAM_DECISION helper). It fills annual offtake volumes for a
strategy so that the physical stock reaches explicit end-of-year targets. Every plan it produces
is re-simulated by the engine; the engine is the truth, the planner is only a convenience.

Rule (disclosed in docs/architecture.md):
  1. targets: end-of-year stock = max(next-year 45-day reserve of the planning scenario,
     next-year demand + next-year target - next-year net capacity), capped by storage capacity
     (backward pass), terminal target = 45-day reserve of the last year;
  2. forward pass: order the paid take-or-pay minimums of reserved channels first, then fill the
     remaining net need from the priority list (cheapest marginal tonne first), respecting
     reserved/available capacity; surplus from minimums is carried as stock;
  3. deliveries are spread uniformly over the days of the contract year; losses use the storage
     regime active in that year; scenario delivery shares (e.g. ISRU 55 %) are taken into account
     because the scenario is known from the start of the case.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import calendar as cal
from .case import Case
from .engine import DEFAULT_ASSUMPTIONS, availability, resolve_investments
from .plan import Investment, Order, Plan, Reservation
from .scenario import Scenario, effective


@dataclass
class StrategySpec:
    strategy_id: str
    label: str
    reservations: dict[str, dict[int, float]]          # sid -> {year: reserved t/year}
    investments: list[dict]                             # dicts as in plan JSON
    fill_priority: list[str]                            # sids, cheapest marginal tonne first
    planned_emergency_years: list[int] = field(default_factory=list)
    opening_net_t: float = 12.4                         # physical stock on 1 January of the first year
    prep_source: str = "B"
    prep_start: str = "2034-11-18"
    prep_end: str = "2034-12-31"
    terminal_reserve: bool = True
    description: str = ""
    reaction_from: Optional[str] = None                 # date when the operator observes the stress (reactive plans)
    reactive_sources: list[str] = field(default_factory=list)   # sources that may be re-ordered after observation
    reserve_margin_share: float = 0.0                   # extra stock above the 45-day reserve as a share of it (safety margin)


def spec_from_plan(case: Case, plan: Plan, strategy_id: str = "custom", **overrides) -> StrategySpec:
    """Derive a StrategySpec from an existing plan (same contracts and investments, orders re-derived)."""
    reservations: dict[str, dict[int, float]] = {}
    for r in plan.reservations:
        if r.start or r.end:
            continue
        reservations.setdefault(r.source_id, {})[int(r.year)] = float(r.reserved)
    inv = []
    for i in plan.investments:
        d = {k: v for k, v in i.__dict__.items() if v is not None}
        inv.append(d)
    isru = case.source_by_name("Lunar-ISRU").source_id
    e = case.source_by_name("Emergency").source_id
    active = [sid for sid in case.sources if reservations.get(sid) or (sid == isru and any(i["investment_id"] == "LUNAR_ISRU" for i in inv))]
    priority = sorted([sid for sid in active if sid != e], key=lambda sid: case.sources[sid].var_cost)
    epol = plan.emergency_policy or {}
    planned_e = list(epol.get("planned_years", [])) if epol.get("role") == "planned_base" else []
    opening = 0.0
    prep = next((o for o in plan.orders if o.role == "preparatory"), None)
    if prep is not None:
        opening = prep.volume * (1 - case.storages["BASE"].loss_rate)
    spec = StrategySpec(strategy_id=strategy_id, label=plan.description or strategy_id, reservations=reservations, investments=inv,
                        fill_priority=priority, planned_emergency_years=planned_e, opening_net_t=round(opening, 6) if prep else 0.0,
                        prep_source=prep.source_id if prep else "B", prep_start=prep.start if prep else "2034-11-18",
                        prep_end=prep.end if prep else "2034-12-31")
    for k, v in overrides.items():
        setattr(spec, k, v)
    return spec


@dataclass
class PlannerReport:
    targets: dict[int, float]
    net_capacity: dict[int, float]
    warnings: list[str]
    closing: dict[int, float]


def build_plan(case: Case, scen: Scenario, spec: StrategySpec, plan_id: str, assumptions: Optional[dict] = None,
               fixed_orders: Optional[dict[tuple[str, int], float]] = None) -> tuple[Plan, PlannerReport]:
    """fixed_orders: {(source_id, year): volume} committed before the reaction date (reactive plans only)."""
    A = dict(DEFAULT_ASSUMPTIONS)
    A.update(assumptions or {})
    years = case.years
    first, last = years[0], years[-1]
    prep_year = first - 1
    sim_start, sim_end = cal.year_start(prep_year), cal.year_end(last)
    eff = effective(case, scen, years)
    reserve_days = float(A["reserve_days"])
    react_idx = cal.to_index(spec.reaction_from) if spec.reaction_from else None
    fixed_orders = fixed_orders or {}

    plan = Plan(plan_id=plan_id, scenario_id=scen.scenario_id, description=spec.description or spec.label)
    for inv in spec.investments:
        plan.investments.append(Investment(**inv))
    infra = resolve_investments(case, plan, first, last, scen.scenario_id)
    avail = availability(case, infra, sim_start, sim_end, A)
    base_st, zbo_st = case.storages["BASE"], case.storages["ZBO"]

    def window(sid: str, y: int) -> Optional[tuple[int, int]]:
        """Delivery window of a source inside year y: availability, and for reactive sources the
        earliest arrival after the observation date plus the source lead time."""
        win = avail.get(sid)
        if win is None:
            return None
        st, en = max(cal.year_start(y), win[0]), min(cal.year_end(y), win[1])
        if react_idx is not None and sid in spec.reactive_sources and y >= cal.year_of(react_idx):
            lead = cal.lead_days(case.sources[sid].lead_max, case.sources[sid].lead_unit)
            st = max(st, react_idx + lead)
        if en < st:
            return None
        return st, en

    def frac_active(sid: str, y: int) -> float:
        w = window(sid, y)
        return 0.0 if w is None else (w[1] - w[0] + 1) / cal.DAYS_IN_YEAR

    def loss_rate(y: int) -> float:
        ys, ye = cal.year_start(y), cal.year_end(y)
        if infra.zbo_commission is None or infra.zbo_commission > ye:
            return base_st.loss_rate
        zbo_days = ye - max(ys, infra.zbo_commission) + 1
        return (zbo_days * zbo_st.loss_rate + (cal.DAYS_IN_YEAR - zbo_days) * base_st.loss_rate) / cal.DAYS_IN_YEAR

    def storage_cap_end(y: int) -> float:
        if infra.zbo_commission is not None and infra.zbo_commission <= cal.year_end(y):
            return zbo_st.capacity
        return base_st.capacity

    def cap_of(sid: str, y: int) -> float:
        s = case.sources[sid]
        reserved = spec.reservations.get(sid, {}).get(y, 0.0)
        limit = reserved if (s.res_rate > 0 or s.top_share > 0) else eff.capacity[sid][y]
        limit = min(limit, eff.capacity[sid][y])
        if sid == case.source_by_name("Emergency").source_id and y not in spec.planned_emergency_years:
            reactive_ok = react_idx is not None and sid in spec.reactive_sources and y >= cal.year_of(react_idx)
            if not reactive_ok:
                return 0.0
        return limit * frac_active(sid, y)

    # ---- backward targets
    reserve = {y: eff.demand_total[y] * reserve_days / cal.DAYS_IN_YEAR * (1.0 + spec.reserve_margin_share) for y in years}
    net_cap = {}
    for y in years:
        net_cap[y] = sum(cap_of(sid, y) * eff.delivery_share[sid][y] for sid in case.sources) * (1 - loss_rate(y))
    targets: dict[int, float] = {}
    warnings: list[str] = []
    nxt = reserve[last] if spec.terminal_reserve else 0.0
    targets[last] = min(nxt, storage_cap_end(last))
    for y in reversed(years[:-1]):
        y1 = y + 1
        need = max(reserve[y1], eff.demand_total[y1] + targets[y1] - net_cap[y1])
        cap = storage_cap_end(y)
        if need > cap + 1e-9:
            warnings.append(f"{y}: required end stock {need:.2f} t exceeds storage {cap:.0f} t; year {y1} cannot be fully covered")
        targets[y] = min(need, cap)

    # ---- forward allocation
    orders: list[Order] = []
    closing: dict[int, float] = {}
    opening = spec.opening_net_t
    e_sid = case.source_by_name("Emergency").source_id
    for y in years:
        lr = loss_rate(y)
        required_net = max(0.0, eff.demand_total[y] + targets[y] - opening)
        ordered: dict[str, float] = {sid: 0.0 for sid in case.sources}
        net_in = 0.0
        reacting = react_idx is not None and y >= cal.year_of(react_idx)
        # committed volumes (reactive plans): sources decided before the observation keep their volumes
        for sid in case.sources:
            if reacting and sid not in spec.reactive_sources:
                v = fixed_orders.get((sid, y), 0.0)
                ordered[sid] = v
                net_in += v * eff.delivery_share[sid][y] * (1 - lr)
        # paid minimums first
        for sid, s in case.sources.items():
            if reacting and sid not in spec.reactive_sources:
                continue
            reserved = spec.reservations.get(sid, {}).get(y, 0.0)
            if reserved <= 0 or s.top_share <= 0:
                continue
            min_order = s.top_share * reserved * frac_active(sid, y)
            ordered[sid] = min_order
            net_in += min_order * eff.delivery_share[sid][y] * (1 - lr)
        need = required_net - net_in
        for sid in spec.fill_priority:
            if need <= 1e-9:
                break
            if reacting and sid not in spec.reactive_sources:
                continue
            room = cap_of(sid, y) - ordered[sid]
            if room <= 1e-12:
                continue
            per_gross = eff.delivery_share[sid][y] * (1 - lr)
            if per_gross <= 0:
                continue
            take = min(room, need / per_gross)
            ordered[sid] += take
            net_in += take * per_gross
            need -= take * per_gross
        if need > 1e-6:
            warnings.append(f"{y}: net need {need:.3f} t cannot be covered by allowed sources; shortage expected")
        served = min(eff.demand_total[y], opening + net_in)
        close = opening + net_in - served
        cap = storage_cap_end(y)
        if close > cap + 1e-6:
            warnings.append(f"{y}: closing stock {close:.2f} t above storage {cap:.0f} t (paid minimums exceed need)")
        closing[y] = close
        for sid, v in ordered.items():
            if v > 1e-9:
                w = window(sid, y)
                if w is None:
                    warnings.append(f"{y}: {sid} volume {v:.3f} t has no delivery window")
                    continue
                full_year = (w[0] == cal.year_start(y) and w[1] == cal.year_end(y))
                if reacting and sid in spec.reactive_sources:
                    orders.append(Order(source_id=sid, volume=v, start=cal.to_date(w[0]), end=cal.to_date(w[1]),
                                        role="reactive", decided_on=cal.to_date(react_idx),
                                        cause=f"reaction to observed conditions on {spec.reaction_from}; arrival after lead time"))
                elif full_year:
                    orders.append(Order(source_id=sid, volume=v, year=y, role="planned"))
                else:
                    orders.append(Order(source_id=sid, volume=v, start=cal.to_date(w[0]), end=cal.to_date(w[1]), role="planned",
                                        cause="partial year: delivery window limited by source availability"))
        opening = close

    # ---- preparatory deliveries for the opening stock
    if spec.opening_net_t > 0:
        gross = spec.opening_net_t / (1 - base_st.loss_rate)
        lead = cal.lead_days(case.sources[spec.prep_source].lead_max, case.sources[spec.prep_source].lead_unit)
        decided = cal.to_date(cal.to_index(spec.prep_start) - lead)
        orders.insert(0, Order(source_id=spec.prep_source, volume=gross, start=spec.prep_start, end=spec.prep_end,
                               role="preparatory", decided_on=decided,
                               cause=f"opening stock {spec.opening_net_t:g} t net for {first}-01-01; gross = net / (1 - {base_st.loss_rate:g})"))
        plan.reservations.append(Reservation(source_id=spec.prep_source, year=prep_year,
                                             reserved=case.sources[spec.prep_source].capacity,
                                             start=spec.prep_start, end=spec.prep_end))
    for sid, by_year in spec.reservations.items():
        for y, v in sorted(by_year.items()):
            if v > 0:
                plan.reservations.append(Reservation(source_id=sid, year=y, reserved=v))
    plan.orders = orders
    plan.inventory_policy = {"reserve_days": reserve_days, "reserve_mode": "physical",
                             "end_year_targets_t": {str(y): round(t, 6) for y, t in targets.items()}}
    plan.emergency_policy = {"role": "planned_base" if spec.planned_emergency_years else "insurance",
                             "planned_years": list(spec.planned_emergency_years)}
    plan.meta = {"strategy": spec.strategy_id, "planning_scenario": scen.scenario_id, "builder": "kosmo.planner v1",
                 "targets_t": {str(y): round(t, 6) for y, t in targets.items()}, "warnings": warnings}
    return plan, PlannerReport(targets=targets, net_capacity=net_cap, warnings=warnings, closing=closing)
