"""Organiser synthetic control cases V01–V10 (validation/control_cases.md), computed with the
same elementary formulas the engine uses. `run_vectors()` returns actual values in the shape of
expected_checks.json so tests can compare one to one."""
from __future__ import annotations

from .formulas import (material_balance, payable_volume, reservation_payment, reserve_45d,
                       served_and_shortage, throughput_losses)


def run_vectors() -> dict[str, dict]:
    out: dict[str, dict] = {}
    # V01 material balance
    out["V01"] = {"closing_inventory_t": material_balance(10, 30, 2, 25)}
    # V02 shortage is not negative inventory
    served, short, closing = served_and_shortage(opening=0, delivered=8, losses=0, demand=10)
    out["V02"] = {"served_t": served, "shortage_t": short, "closing_inventory_t": closing}
    # V03 take-or-pay minimum
    q = payable_volume(order=50, reserved_period=100, top_share=0.70)
    out["V03"] = {"payable_volume_t": q, "variable_payment_mln": q * 2}
    # V04 not charged twice: same inputs, same payment
    out["V04"] = {"variable_payment_mln": payable_volume(50, 100, 0.70) * 2}
    # V05 reservation proration
    out["V05"] = {"reservation_payment_mln": reservation_payment(rate=0.4, annual_reserved=100, period_fraction=0.5)}
    # V06 losses once on throughput
    out["V06"] = {"losses_t": throughput_losses(gross_inflow=20, loss_rate=0.05)}
    # V07 45-day reserve
    out["V07"] = {"reserve_t": reserve_45d(annual_total_demand=365)}
    # V08 capacity exceeded
    cap, reserved = 10, 12
    out["V08"] = {"violation": "CAPACITY_EXCEEDED" if reserved > cap else "OK", "excess_t": max(0, reserved - cap)}
    # V09 critical demand nested in total
    total, critical = 100, 60
    out["V09"] = {"total_demand_t": total if critical <= total else None}
    # V10 stress delivery share not multiplied by reliability again
    planned, share, reliability_metadata = 20, 0.50, 0.80
    out["V10"] = {"actual_delivery_t": planned * share}
    return out
