"""Calculation core: daily simulation of the fuel node, costs and constraint checks.

Control semantics (Постановка с. 6–8, CALCULATION_RULES):
  I_end = I_start + Q_delivered - Losses - Q_served           (per day, tonnes)
  Losses = gross inflow * loss_rate(active storage regime)   (once, on throughput)
  Shortage = max(0, Demand - Q_served)                        (never a negative stock)
  R_y = D_y * 45 / 365, checked on 1 January against physical stock
  VariablePayment = price * max(Q_order_period, TOP * Q_reserved_period)
  ReservationPayment = rate * reserved * period_fraction
  TotalCost = Procurement + Reservation + Holding + FixedOPEX + CAPEX
  PV_t = CF_t / (1 + r)^(t - t0)

Team conventions are read from configs/assumptions.yaml and listed in the run meta.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from . import calendar as cal
from .case import Case
from .plan import Investment, Order, Plan, Violation
from .scenario import Effective, Scenario, effective

EPS = 1e-9


@dataclass
class ResolvedOrder:
    source_id: str
    start: int
    end: int
    volume: float
    daily: float
    role: str
    decided_on: int
    lead_days: int
    cause: str = ""


@dataclass
class ResolvedReservation:
    source_id: str
    year: int
    reserved: float
    start: int
    end: int


@dataclass
class RunResult:
    plan_id: str
    scenario_id: str
    years: list[int]
    yearly: list[dict]
    source_year: list[dict]
    daily: list[dict]
    checks: list[dict]
    violations: list[Violation]
    horizon: dict
    meta: dict
    events: list[dict] = field(default_factory=list)

    @property
    def feasible(self) -> bool:
        return not any(v.severity == "hard" for v in self.violations)

    def violations_dicts(self) -> list[dict]:
        return [v.as_dict() for v in self.violations]


DEFAULT_ASSUMPTIONS = {
    "discount_rate": 0.07,
    "discount_base_year": 2035,
    "reserve_days": 45,
    "preparatory_year_enabled": True,
    "preparatory_costs_to_first_year": True,
    "earth_channels_available_in_preparatory_year": True,
    "order_lead_convention": "max",          # plan orders must be decided lead_max before delivery
    "emergency_base_share_threshold": 0.10,
    "storage_overflow_policy": "cap_and_flag",
    "critical_first": True,
    "isru_deliveries_from_commissioning": True,
}


def _lead(case: Case, sid: str, which: str = "max") -> int:
    s = case.sources[sid]
    v = s.lead_max if which == "max" else s.lead_min
    return cal.lead_days(v, s.lead_unit)


def _fmt(x: float) -> float:
    return float(x)


# ------------------------------------------------------------------ investments
@dataclass
class Infra:
    zbo_commission: Optional[int] = None
    new_commission: Optional[int] = None
    isru_commission: Optional[int] = None
    isru_financed_by: Optional[int] = None
    capex_events: list = field(default_factory=list)      # (day_index, amount, label)
    violations: list = field(default_factory=list)


def resolve_investments(case: Case, plan: Plan, first_year: int, last_year: int, scen_id: str) -> Infra:
    infra = Infra()
    for inv in plan.investments:
        iid = inv.investment_id
        if iid == "ZBO":
            st = case.storages["ZBO"]
            if not inv.decision_date:
                infra.violations.append(Violation("INVALID_INPUT", "ZBO", "", "", "", "", "ZBO needs decision_date", "hard", scen_id))
                continue
            d0 = cal.to_index(inv.decision_date)
            earliest = cal.year_start(st.available_from_year)
            if d0 < earliest:
                infra.violations.append(Violation("INVESTMENT_NOT_AVAILABLE", inv.decision_date, inv.decision_date,
                                                  cal.to_date(earliest), "", "date",
                                                  f"ZBO option is available from {st.available_from_year}", "hard", scen_id))
            lead = cal.lead_days(inv.lead_months or 0.0, "month")
            comm = d0 + lead
            if inv.commissioning_date:
                c2 = cal.to_index(inv.commissioning_date)
                if c2 < comm:
                    infra.violations.append(Violation("LEAD_TIME_VIOLATION", inv.commissioning_date, inv.commissioning_date,
                                                      cal.to_date(comm), comm - c2, "days",
                                                      "ZBO commissioning earlier than decision + lead time", "hard", scen_id))
                comm = max(comm, c2)
            infra.zbo_commission = comm
            infra.capex_events.append((d0, st.capex, "ZBO CAPEX"))
        elif iid == "EARTH_NEW":
            opt = case.investments["EARTH_NEW"]
            src = case.source_by_name("Earth-New")
            if not inv.option_fee_date or not inv.exercise_date:
                infra.violations.append(Violation("INVALID_INPUT", "EARTH_NEW", "", "", "", "",
                                                  "EARTH_NEW needs option_fee_date and exercise_date", "hard", scen_id))
                continue
            d_opt = cal.to_index(inv.option_fee_date)
            d_ex = cal.to_index(inv.exercise_date)
            if d_ex < d_opt:
                infra.violations.append(Violation("INVALID_INPUT", inv.exercise_date, inv.exercise_date, inv.option_fee_date,
                                                  "", "date", "Earth-New exercised before the option was bought", "hard", scen_id))
            lead_m = inv.lead_months if inv.lead_months is not None else src.lead_max
            if lead_m < src.lead_min - EPS or lead_m > src.lead_max + EPS:
                infra.violations.append(Violation("INVALID_INPUT", inv.exercise_date, lead_m,
                                                  f"{src.lead_min:g}-{src.lead_max:g}", "", "month",
                                                  "Earth-New lead time outside the case range 18-24 months", "hard", scen_id))
            comm = d_ex + cal.lead_days(lead_m, "month")
            if inv.commissioning_date:
                c2 = cal.to_index(inv.commissioning_date)
                if c2 < comm:
                    infra.violations.append(Violation("LEAD_TIME_VIOLATION", inv.commissioning_date, inv.commissioning_date,
                                                      cal.to_date(comm), comm - c2, "days",
                                                      "Earth-New commissioning earlier than exercise + lead time", "hard", scen_id))
                comm = max(comm, c2)
            infra.new_commission = comm
            infra.capex_events.append((d_opt, opt.option_fee, "Earth-New option fee"))
            infra.capex_events.append((d_ex, opt.exercise_cost, "Earth-New exercise"))
        elif iid == "LUNAR_ISRU":
            opt = case.investments["LUNAR_ISRU"]
            src = case.source_by_name("Lunar-ISRU")
            if not inv.financing_date:
                infra.violations.append(Violation("INVALID_INPUT", "LUNAR_ISRU", "", "", "", "",
                                                  "LUNAR_ISRU needs financing_date", "hard", scen_id))
                continue
            d_fin = cal.to_index(inv.financing_date)
            avail_year = src.available_from_year or 2038
            deadline = cal.year_end(avail_year - 1)
            infra.isru_financed_by = d_fin
            infra.capex_events.append((d_fin, opt.exercise_cost, "Lunar-ISRU CAPEX"))
            if d_fin > deadline:
                infra.violations.append(Violation("INVESTMENT_NOT_FINANCED", inv.financing_date, inv.financing_date,
                                                  cal.to_date(deadline), d_fin - deadline, "days",
                                                  "Lunar-ISRU CAPEX must be financed before 2038; commissioning slips by the delay",
                                                  "hard", scen_id))
                infra.isru_commission = d_fin + 1
            else:
                infra.isru_commission = cal.year_start(avail_year)
        else:
            infra.violations.append(Violation("INVALID_INPUT", iid, iid, "ZBO|EARTH_NEW|LUNAR_ISRU", "", "",
                                              f"unknown investment_id {iid!r}", "hard", scen_id))
    return infra


# ------------------------------------------------------------------ availability
def availability(case: Case, infra: Infra, sim_start: int, sim_end: int, assumptions: dict) -> dict[str, Optional[tuple[int, int]]]:
    out: dict[str, Optional[tuple[int, int]]] = {}
    prep_ok = bool(assumptions.get("earth_channels_available_in_preparatory_year", True))
    for sid, s in case.sources.items():
        if s.name == "Earth-New":
            out[sid] = (infra.new_commission, sim_end) if infra.new_commission is not None else None
        elif s.name == "Lunar-ISRU":
            out[sid] = (infra.isru_commission, sim_end) if infra.isru_commission is not None else None
        else:
            if s.available_from_year is None:
                out[sid] = None
            else:
                start = cal.year_start(s.available_from_year)
                if prep_ok:
                    start = min(start, sim_start)
                out[sid] = (start, sim_end)
    return out


# ------------------------------------------------------------------ main run
def run(case: Case, plan: Plan, scen: Scenario, assumptions: Optional[dict] = None,
        keep_daily: bool = True) -> RunResult:
    A = dict(DEFAULT_ASSUMPTIONS)
    A.update(assumptions or {})
    years = case.years
    first_year, last_year = years[0], years[-1]
    prep_year = first_year - 1
    sim_start = cal.year_start(prep_year) if A["preparatory_year_enabled"] else cal.year_start(first_year)
    sim_end = cal.year_end(last_year)
    n_days = sim_end - sim_start + 1
    sids = list(case.sources)
    eff: Effective = effective(case, scen, years)
    scen_id = scen.scenario_id
    violations: list[Violation] = []
    events: list[dict] = []

    infra = resolve_investments(case, plan, first_year, last_year, scen_id)
    violations.extend(infra.violations)
    avail = availability(case, infra, sim_start, sim_end, A)

    # ---- reservations resolved to day windows (clipped to availability and year)
    resv: list[ResolvedReservation] = []
    for r in plan.reservations:
        if r.source_id not in case.sources:
            violations.append(Violation("UNKNOWN_SOURCE", str(r.year), r.source_id, "|".join(sids), "", "",
                                        f"reservation refers to unknown source {r.source_id!r}", "hard", scen_id))
            continue
        y = r.year
        ys, ye = cal.year_start(y), cal.year_end(y)
        st = cal.to_index(r.start) if r.start else ys
        en = cal.to_index(r.end) if r.end else ye
        st, en = max(st, ys), min(en, ye)
        cap = eff.capacity[r.source_id].get(y, case.sources[r.source_id].capacity)
        if r.reserved > cap + EPS:
            violations.append(Violation("CAPACITY_EXCEEDED", str(y), r.reserved, cap, r.reserved - cap, "t/year",
                                        f"reserved capacity of {case.sources[r.source_id].name} exceeds source capacity", "hard", scen_id))
        win = avail.get(r.source_id)
        if win is None:
            if r.reserved > EPS:
                violations.append(Violation("SOURCE_NOT_AVAILABLE", str(y), r.reserved, 0, r.reserved, "t/year",
                                            f"{case.sources[r.source_id].name} is not available (investment missing or not commissioned)", "hard", scen_id))
            continue
        st2, en2 = max(st, win[0]), min(en, win[1])
        if en2 < st2:
            continue  # nothing active in that year (e.g. New before commissioning)
        resv.append(ResolvedReservation(r.source_id, y, r.reserved, st2, en2))

    # ---- orders resolved to daily flows
    orders: list[ResolvedOrder] = []
    for o in plan.orders:
        if o.source_id not in case.sources:
            violations.append(Violation("UNKNOWN_SOURCE", str(o.year or o.start), o.source_id, "|".join(sids), "", "",
                                        f"order refers to unknown source {o.source_id!r}", "hard", scen_id))
            continue
        if o.volume <= EPS:
            continue
        if o.start and o.end:
            st, en = cal.to_index(o.start), cal.to_index(o.end)
        else:
            st, en = cal.year_start(o.year), cal.year_end(o.year)
        win = avail.get(o.source_id)
        name = case.sources[o.source_id].name
        if win is None:
            violations.append(Violation("SOURCE_NOT_AVAILABLE", cal.to_date(st), o.volume, 0, o.volume, "t",
                                        f"{name}: order on a source that is not available (investment missing)", "hard", scen_id))
            continue
        if st < win[0] or en > win[1]:
            # portion outside availability is not delivered; report it
            inside = cal.overlap_days(st, en, win[0], win[1])
            total = en - st + 1
            lost = o.volume * (1 - inside / total)
            violations.append(Violation("SOURCE_NOT_AVAILABLE", cal.to_date(st), o.volume, o.volume - lost, lost, "t",
                                        f"{name}: {lost:.3f} t scheduled outside availability window {cal.to_date(win[0])}..{cal.to_date(win[1])}",
                                        "hard", scen_id))
            st, en = max(st, win[0]), min(en, win[1])
            if en < st:
                continue
            vol = o.volume - lost
        else:
            vol = o.volume
        lead = _lead(case, o.source_id, A["order_lead_convention"])
        if o.source_id == case.source_by_name("Earth-New").source_id:
            lead = 0  # supply schedule committed at exercise; preparation lag applied once via commissioning
        decided = cal.to_index(o.decided_on) if o.decided_on else st - lead
        if decided + lead > st:
            violations.append(Violation("LEAD_TIME_VIOLATION", cal.to_date(st), cal.to_date(decided), cal.to_date(st - lead),
                                        decided + lead - st, "days",
                                        f"{name}: order decided {cal.to_date(decided)} cannot arrive by {cal.to_date(st)} (lead {lead} days)",
                                        "hard", scen_id))
        if decided < sim_start:
            violations.append(Violation("LEAD_TIME_VIOLATION", cal.to_date(st), cal.to_date(decided), cal.to_date(sim_start),
                                        sim_start - decided, "days",
                                        f"{name}: order would have to be decided before the preparatory period starts", "hard", scen_id))
        days = en - st + 1
        orders.append(ResolvedOrder(o.source_id, st, en, vol, vol / days, o.role, decided, lead, o.cause))

    # ---- daily scheduled and actual flows
    sched = {sid: [0.0] * n_days for sid in sids}
    for ro in orders:
        arr = sched[ro.source_id]
        for d in range(ro.start, ro.end + 1):
            arr[d - sim_start] += ro.daily
    # capacity per day
    for sid in sids:
        name = case.sources[sid].name
        worst: dict[int, float] = {}
        for k in range(n_days):
            d = sim_start + k
            y = cal.year_of(d)
            cap = eff.capacity[sid].get(y, case.sources[sid].capacity) / cal.DAYS_IN_YEAR
            if sched[sid][k] > cap + 1e-9:
                worst[y] = max(worst.get(y, 0.0), (sched[sid][k] - cap) * cal.DAYS_IN_YEAR)
        for y, ex in sorted(worst.items()):
            cap_y = eff.capacity[sid].get(y, case.sources[sid].capacity)
            violations.append(Violation("CAPACITY_EXCEEDED", str(y), cap_y + ex, cap_y, ex, "t/year",
                                        f"{name}: scheduled daily flow exceeds capacity/365 (annual-equivalent excess)", "hard", scen_id))
    # actual flows (scenario delivery share)
    actual = {sid: [0.0] * n_days for sid in sids}
    for sid in sids:
        for k in range(n_days):
            y = cal.year_of(sim_start + k)
            share = eff.delivery_share[sid].get(y, 1.0)
            actual[sid][k] = sched[sid][k] * share

    # ---- storage regime per day
    base_st, zbo_st = case.storages["BASE"], case.storages["ZBO"]

    def regime(d: int):
        if infra.zbo_commission is not None and d >= infra.zbo_commission:
            return zbo_st
        return base_st

    # ---- demand per day
    dem_tot = {y: eff.demand_total[y] for y in years}
    dem_crit = {y: eff.demand_critical[y] for y in years}

    # ---- daily loop
    stock = 0.0
    daily: list[dict] = []
    per_year: dict[int, dict] = {}
    for y in ([prep_year] if A["preparatory_year_enabled"] else []) + years:
        per_year[y] = dict(year=y, demand_total=dem_tot.get(y, 0.0), demand_critical=dem_crit.get(y, 0.0),
                           opening=None, scheduled=0.0, delivered=0.0, losses=0.0, served_total=0.0, served_critical=0.0,
                           shortage_total=0.0, shortage_critical=0.0, closing=0.0, holding_mln=0.0, mean_stock_sum=0.0,
                           peak_before_losses=0.0, first_shortage=None, shortage_days=0, overflow_t=0.0,
                           zbo_days=0, isru_days=0, delivered_by={sid: 0.0 for sid in sids},
                           scheduled_by={sid: 0.0 for sid in sids})
    reserve_days = float(A["reserve_days"])
    for k in range(n_days):
        d = sim_start + k
        y = cal.year_of(d)
        py = per_year[y]
        if py["opening"] is None:
            py["opening"] = stock
            # reserve check on 1 January of horizon years (physical stock before the day's arrivals)
            if y in years:
                req = dem_tot[y] * reserve_days / cal.DAYS_IN_YEAR
                py["required_reserve"] = req
                if stock + 1e-9 < req:
                    violations.append(Violation("RESERVE_45D", cal.to_date(d), stock, req, req - stock, "t",
                                                "opening physical stock below 45-day reserve of the current scenario; contracted capacity is not stock",
                                                "hard", scen_id))
        reg = regime(d)
        gross = 0.0
        for sid in sids:
            a = actual[sid][k]
            if a:
                gross += a
                py["delivered_by"][sid] += a
            s_ = sched[sid][k]
            if s_:
                py["scheduled_by"][sid] += s_
                py["scheduled"] += s_
        losses = gross * reg.loss_rate
        peak = stock + gross
        py["peak_before_losses"] = max(py["peak_before_losses"], peak)
        stock_after = stock + gross - losses
        if peak > reg.capacity + 1e-9:
            over = peak - reg.capacity
            py["overflow_t"] += over
            if A["storage_overflow_policy"] == "cap_and_flag":
                stock_after = min(stock_after, reg.capacity)
            events.append({"date": cal.to_date(d), "event": "STORAGE_OVERFLOW", "excess_t": over, "capacity_t": reg.capacity})
        crit_d = dem_crit.get(y, 0.0) / cal.DAYS_IN_YEAR
        oth_d = (dem_tot.get(y, 0.0) - dem_crit.get(y, 0.0)) / cal.DAYS_IN_YEAR
        served_c = min(stock_after, crit_d)
        rem = stock_after - served_c
        served_o = min(rem, oth_d)
        stock_end = rem - served_o
        short_c = crit_d - served_c
        short_o = oth_d - served_o
        mean_day = (stock_after + stock_end) / 2.0
        hold = mean_day * reg.holding_cost / cal.DAYS_IN_YEAR
        py["delivered"] += gross
        py["losses"] += losses
        py["served_total"] += served_c + served_o
        py["served_critical"] += served_c
        py["shortage_total"] += short_c + short_o
        py["shortage_critical"] += short_c
        py["holding_mln"] += hold
        py["mean_stock_sum"] += mean_day
        if short_c + short_o > 1e-9:
            py["shortage_days"] += 1
            if py["first_shortage"] is None:
                py["first_shortage"] = cal.to_date(d)
        if reg is zbo_st:
            py["zbo_days"] += 1
        if infra.isru_commission is not None and d >= infra.isru_commission:
            py["isru_days"] += 1
        if keep_daily:
            daily.append({"date": cal.to_date(d), "year": y, "opening_t": stock, "inflow_scheduled_t": sum(sched[s][k] for s in sids),
                          "inflow_actual_t": gross, "losses_t": losses, "stock_after_inflow_t": stock_after,
                          "served_critical_t": served_c, "served_other_t": served_o, "shortage_t": short_c + short_o,
                          "closing_t": stock_end, "storage_capacity_t": reg.capacity, "regime": reg.storage_id})
        stock = stock_end
        py["closing"] = stock

    # ---- storage overflow violations (per year)
    for y, py in per_year.items():
        if py["overflow_t"] > 1e-9:
            violations.append(Violation("STORAGE_OVERFLOW", str(y), py["peak_before_losses"],
                                        (zbo_st if (infra.zbo_commission is not None and infra.zbo_commission <= cal.year_end(y)) else base_st).capacity,
                                        py["overflow_t"], "t",
                                        "physical stock plus arrivals exceeds active storage capacity; excess reported, not silently stored",
                                        "hard", scen_id))

    # ---- costs per year
    source_year: list[dict] = []
    cost_years = years
    # capex by year
    capex_by_year = {y: 0.0 for y in [prep_year] + years}
    capex_detail: list[dict] = []
    for d, amt, label in infra.capex_events:
        y = cal.year_of(d)
        if y in capex_by_year:
            capex_by_year[y] += amt
        elif y < prep_year:
            capex_by_year[prep_year] += amt
        capex_detail.append({"date": cal.to_date(d), "year": y, "amount_mln": amt, "label": label})
    # reservation / TOP / procurement per (source, year), including preparatory year
    fin_years = ([prep_year] if A["preparatory_year_enabled"] else []) + years
    resv_by = {(r.source_id, r.year): r for r in resv}
    proc_by_year = {y: 0.0 for y in fin_years}
    resv_by_year = {y: 0.0 for y in fin_years}
    for y in fin_years:
        for sid in sids:
            s = case.sources[sid]
            r = resv_by.get((sid, y))
            reserved = r.reserved if r else 0.0
            frac = ((r.end - r.start + 1) / cal.DAYS_IN_YEAR) if r else 0.0
            price = eff.price[sid].get(y, s.var_cost)
            rate = eff.res_rate[sid].get(y, s.res_rate)
            scheduled = per_year[y]["scheduled_by"][sid]
            delivered = per_year[y]["delivered_by"][sid]
            top_min = s.top_share * reserved * frac
            paid_qty = max(scheduled, top_min)
            procurement = price * paid_qty
            reservation = rate * reserved * frac
            # order beyond reservation (contractually available volume)
            if s.res_rate > 0 or s.top_share > 0:
                limit = reserved * frac
                if scheduled > limit + 1e-6:
                    violations.append(Violation("ORDER_EXCEEDS_RESERVATION", str(y), scheduled, limit, scheduled - limit, "t",
                                                f"{s.name}: scheduled offtake exceeds reserved capacity of the period", "hard", scen_id))
            proc_by_year[y] += procurement
            resv_by_year[y] += reservation
            if reserved > EPS or scheduled > EPS or delivered > EPS:
                source_year.append({"year": y, "source_id": sid, "source": s.name, "reserved_t_per_year": reserved,
                                    "contract_period_fraction": frac, "scheduled_t": scheduled, "delivered_t": delivered,
                                    "top_minimum_t": top_min, "paid_quantity_t": paid_qty, "paid_unused_t": max(0.0, paid_qty - scheduled),
                                    "unit_price_mln_per_t": price, "procurement_mln": procurement,
                                    "reservation_rate_mln_per_t_year": rate, "reservation_mln": reservation})
    r_disc = float(A["discount_rate"])
    t0 = int(A["discount_base_year"])
    yearly: list[dict] = []
    cum_capex = 0.0
    prep_cost = 0.0
    if A["preparatory_year_enabled"]:
        py = per_year[prep_year]
        prep_cost = proc_by_year[prep_year] + resv_by_year[prep_year] + py["holding_mln"] + capex_by_year[prep_year]
    horizon = dict(total_expense_mln=0.0, discounted_expense_mln=0.0, served_total_t=0.0, served_critical_t=0.0,
                   demand_total_t=0.0, shortage_total_t=0.0, shortage_critical_t=0.0, delivered_t=0.0, losses_t=0.0,
                   procurement_mln=0.0, reservation_mln=0.0, holding_mln=0.0, opex_mln=0.0, capex_mln=0.0)
    for y in years:
        py = per_year[y]
        opex_zbo = zbo_st.opex * py["zbo_days"] / cal.DAYS_IN_YEAR
        opex_isru = case.investments["LUNAR_ISRU"].opex * py["isru_days"] / cal.DAYS_IN_YEAR if "LUNAR_ISRU" in case.investments else 0.0
        capex = capex_by_year[y]
        cum_capex += capex
        prep = prep_cost if (y == first_year and A["preparatory_costs_to_first_year"]) else 0.0
        total = proc_by_year[y] + resv_by_year[y] + py["holding_mln"] + opex_zbo + opex_isru + capex + prep
        df = 1.0 / ((1.0 + r_disc) ** (y - t0))
        served = py["served_total"]
        sl_t = served / py["demand_total"] if py["demand_total"] > 0 else 1.0
        sl_c = py["served_critical"] / py["demand_critical"] if py["demand_critical"] > 0 else 1.0
        row = {
            "year": y, "scenario_id": scen_id, "plan_id": plan.plan_id,
            "demand_total_t": py["demand_total"], "demand_critical_t": py["demand_critical"],
            "required_opening_reserve_t": py.get("required_reserve", 0.0), "opening_inventory_t": py["opening"],
            "scheduled_t": py["scheduled"], "delivered_t": py["delivered"], "losses_t": py["losses"],
            "loss_ratio": (py["losses"] / py["delivered"]) if py["delivered"] > 0 else 0.0,
            "served_total_t": served, "served_critical_t": py["served_critical"],
            "shortage_total_t": py["shortage_total"], "shortage_critical_t": py["shortage_critical"],
            "closing_inventory_t": py["closing"], "SL_total": sl_t, "SL_critical": sl_c,
            "mean_inventory_t": py["mean_stock_sum"] / cal.DAYS_IN_YEAR, "peak_before_losses_t": py["peak_before_losses"],
            "first_shortage_date": py["first_shortage"], "shortage_days": py["shortage_days"],
            "procurement_mln": proc_by_year[y], "reservation_mln": resv_by_year[y], "holding_mln": py["holding_mln"],
            "opex_zbo_mln": opex_zbo, "opex_isru_mln": opex_isru, "capex_mln": capex, "cumulative_capex_mln": cum_capex,
            "preparation_cost_mln": prep, "total_expense_mln": total, "discount_factor": df,
            "discounted_expense_mln": total * df,
            "cost_per_served_t_mln": (total / served) if served > 0 else None,
            "pv_per_served_t_mln": (total * df / served) if served > 0 else None,
            "delivered_by_source": dict(py["delivered_by"]),
        }
        yearly.append(row)
        horizon["total_expense_mln"] += total
        horizon["discounted_expense_mln"] += total * df
        horizon["served_total_t"] += served
        horizon["served_critical_t"] += py["served_critical"]
        horizon["demand_total_t"] += py["demand_total"]
        horizon["shortage_total_t"] += py["shortage_total"]
        horizon["shortage_critical_t"] += py["shortage_critical"]
        horizon["delivered_t"] += py["delivered"]
        horizon["losses_t"] += py["losses"]
        horizon["procurement_mln"] += proc_by_year[y]
        horizon["reservation_mln"] += resv_by_year[y]
        horizon["holding_mln"] += py["holding_mln"]
        horizon["opex_mln"] += opex_zbo + opex_isru
        horizon["capex_mln"] += capex
    horizon["preparation_cost_mln"] = prep_cost
    horizon["cumulative_capex_mln"] = cum_capex
    horizon["closing_inventory_t"] = per_year[years[-1]]["closing"]
    horizon["cost_per_served_t_mln"] = horizon["total_expense_mln"] / horizon["served_total_t"] if horizon["served_total_t"] > 0 else None
    horizon["pv_per_served_t_mln"] = horizon["discounted_expense_mln"] / horizon["served_total_t"] if horizon["served_total_t"] > 0 else None
    horizon["SL_total_min"] = min(r["SL_total"] for r in yearly)
    horizon["SL_critical_min"] = min(r["SL_critical"] for r in yearly)

    # ---- constraint checks (all rules, PASS and FAIL)
    checks: list[dict] = []
    is_base = scen_id == "BASE"
    sl_t_min = case.constraint_value("BASE_TOTAL_SERVICE")
    sl_c_min = case.constraint_value("BASE_CRITICAL_SERVICE")
    capex_2037 = case.constraint_value("CAPEX_2037")
    capex_2040 = case.constraint_value("CAPEX_2040")
    streak_max = int(case.constraint_value("EMERGENCY_BASE_STREAK"))

    def add_check(rule, period, actual, limit, op, unit, severity, cause, margin=None):
        ok = (actual >= limit - 1e-9) if op == ">=" else (actual <= limit + 1e-9)
        if margin is None:
            margin = (actual - limit) if op == ">=" else (limit - actual)
        checks.append({"rule_id": rule, "scenario": scen_id, "period": str(period), "actual": actual, "operator": op,
                       "limit": limit, "margin": margin, "unit": unit, "status": "PASS" if ok else "FAIL",
                       "severity": severity, "cause": cause})
        if not ok:
            violations.append(Violation(rule, str(period), actual, limit, abs(margin), unit, cause, severity, scen_id))

    for r in yearly:
        y = r["year"]
        sev = "hard" if is_base else "reference"
        add_check("BASE_TOTAL_SERVICE" if is_base else "TOTAL_SERVICE_REFERENCE", y, r["SL_total"], sl_t_min, ">=", "share", sev,
                  "annual total service below the case minimum" if is_base else "annual total service below the resilience reference; shortage shown, no automatic recourse")
        add_check("BASE_CRITICAL_SERVICE" if is_base else "CRITICAL_SERVICE_REFERENCE", y, r["SL_critical"], sl_c_min, ">=", "share", sev,
                  "annual critical service below the case minimum" if is_base else "annual critical service below the resilience reference")
        req = r["required_opening_reserve_t"]
        checks.append({"rule_id": "RESERVE_45D", "scenario": scen_id, "period": f"{y}-01-01", "actual": r["opening_inventory_t"],
                       "operator": ">=", "limit": req, "margin": r["opening_inventory_t"] - req, "unit": "t",
                       "status": "PASS" if r["opening_inventory_t"] + 1e-9 >= req else "FAIL", "severity": "hard",
                       "cause": "physical stock on 1 January vs 45 days of current-scenario demand"})
        if eff.loss_ceiling_enabled and eff.loss_ceiling_from_year is not None and y >= eff.loss_ceiling_from_year:
            add_check("STRESS_LOSS_LIMIT", y, r["loss_ratio"], eff.loss_ceiling_max, "<=", "share", "hard",
                      "annual losses / throughput above the stress ceiling; storage regime too lossy")
    cum = 0.0
    for r in yearly:
        cum += r["capex_mln"]
        if r["year"] == 2037:
            add_check("CAPEX_2037", "through_2037", cum, capex_2037, "<=", "mln", "hard", "cumulative CAPEX through end-2037 above limit")
        if r["year"] == 2040:
            add_check("CAPEX_2040", "through_2040", cum, capex_2040, "<=", "mln", "hard", "cumulative CAPEX through 2040 above limit")
    if 2037 not in [r["year"] for r in yearly]:
        add_check("CAPEX_2037", "through_2037", cum_capex, capex_2037, "<=", "mln", "hard", "cumulative CAPEX through end-2037 above limit")
    # Emergency base-channel streak (TEAM_ASSUMPTION A3)
    e_sid = case.source_by_name("Emergency").source_id
    thr = float(A["emergency_base_share_threshold"])
    planned_e_years = {cal.year_of(ro.start) for ro in orders if ro.source_id == e_sid and ro.role in ("planned", "preparatory")}
    base_years = []
    for r in yearly:
        y = r["year"]
        share_e = (r["delivered_by_source"].get(e_sid, 0.0) / r["delivered_t"]) if r["delivered_t"] > 0 else 0.0
        is_base_year = (y in planned_e_years and r["delivered_by_source"].get(e_sid, 0.0) > EPS) or share_e > thr
        base_years.append((y, is_base_year, share_e))
    streak = 0
    worst = 0
    for y, b, _ in base_years:
        streak = streak + 1 if b else 0
        worst = max(worst, streak)
    add_check("EMERGENCY_BASE_STREAK", f"{years[0]}_{years[-1]}", worst, streak_max, "<=", "years", "hard",
              "Emergency used as a base channel for more than two consecutive years (planned offtake or share above threshold)")

    meta = {
        "plan_id": plan.plan_id, "scenario_id": scen_id, "scenario_status": scen.status, "scenario_changes": eff.changes,
        "years": years, "preparatory_year": prep_year if A["preparatory_year_enabled"] else None,
        "assumptions": A, "capex_events": capex_detail,
        "zbo_commissioning": cal.to_date(infra.zbo_commission) if infra.zbo_commission is not None else None,
        "earth_new_commissioning": cal.to_date(infra.new_commission) if infra.new_commission is not None else None,
        "isru_commissioning": cal.to_date(infra.isru_commission) if infra.isru_commission is not None else None,
        "emergency_base_years": [{"year": y, "base_use": b, "share": s} for y, b, s in base_years],
        "units": {"fuel": "t", "money": "mln conditional units, constant 2035 prices", "capacity": "t/year",
                  "rates": "mln per (t/year) per year", "time": "365-day model years"},
    }
    return RunResult(plan_id=plan.plan_id, scenario_id=scen_id, years=years, yearly=yearly, source_year=source_year,
                     daily=daily, checks=checks, violations=violations, horizon=horizon, meta=meta, events=events)
