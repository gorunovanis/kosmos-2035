"""Elementary control formulas (CALCULATION_RULES §1–§7). Used by the engine and by the V01–V10 tests."""
from __future__ import annotations


def material_balance(opening: float, delivered: float, losses: float, served: float) -> float:
    """I_end = I_start + Q_delivered - Losses - Q_served."""
    return opening + delivered - losses - served


def served_and_shortage(opening: float, delivered: float, losses: float, demand: float) -> tuple[float, float, float]:
    """Physical stock never below zero; shortage reported separately."""
    available = opening + delivered - losses
    served = min(available, demand)
    shortage = max(0.0, demand - served)
    closing = available - served
    return served, shortage, closing


def payable_volume(order: float, reserved_period: float, top_share: float) -> float:
    """Q_pay = max(Q_order, take_or_pay_share * Q_reserved_period)."""
    return max(order, top_share * reserved_period)


def reservation_payment(rate: float, annual_reserved: float, period_fraction: float) -> float:
    return rate * annual_reserved * period_fraction


def throughput_losses(gross_inflow: float, loss_rate: float) -> float:
    return gross_inflow * loss_rate


def reserve_45d(annual_total_demand: float, days: float = 45.0) -> float:
    return annual_total_demand * days / 365.0


def service_level(served: float, demand: float) -> float:
    """Defined as 1.0 when demand is zero (boundary case made explicit)."""
    return served / demand if demand > 0 else 1.0


def present_value(cash_flow: float, rate: float, year: int, base_year: int) -> float:
    return cash_flow / (1.0 + rate) ** (year - base_year)
