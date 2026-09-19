"""Boundary values, invalid input and determinism (Критерий 5)."""
import copy
import json
import unittest
from pathlib import Path

from kosmo.api import CASE_DIR, CONFIG_DIR, PROJECT_ROOT, get_scenario, load_assumptions
from kosmo.case import CaseError, load_case
from kosmo.engine import run
from kosmo.export import canonical_hash
from kosmo.formulas import service_level
from kosmo.plan import Plan, PlanError
from kosmo.scenario import Scenario

EXAMPLES = PROJECT_ROOT / "data" / "examples" / "invalid_plan_examples"


def base_plan() -> dict:
    return json.loads((CONFIG_DIR / "plans" / "S1_new18.json").read_text(encoding="utf-8"))


def run_dict(raw: dict, scenario="BASE", case_dir=CASE_DIR):
    case = load_case(case_dir)
    params, _ = load_assumptions()
    plan = Plan.from_dict(raw)
    return run(case, plan, get_scenario(case, scenario), params, keep_daily=False)


def rules(res):
    return {v.rule_id for v in res.violations}


class TestInvalidInput(unittest.TestCase):
    def test_negative_reservation_example(self):
        raw = json.loads((EXAMPLES / "negative_reservation.json").read_text(encoding="utf-8"))
        with self.assertRaises(PlanError) as ctx:
            Plan.from_dict(raw)
        self.assertIn("NEGATIVE_VALUE", str(ctx.exception))

    def test_malformed_scenario_example(self):
        raw = json.loads((EXAMPLES / "malformed_scenario.json").read_text(encoding="utf-8"))
        with self.assertRaises(CaseError) as ctx:
            Scenario.from_dict(raw)
        self.assertIn("scenario_id", str(ctx.exception))

    def test_over_capacity_example_on_source_x_copy(self):
        raw = json.loads((EXAMPLES / "over_capacity.json").read_text(encoding="utf-8"))
        raw["decisions"]["capacity_reservations"][0]["source_id"] = "X"
        res = run_dict(raw, case_dir=PROJECT_ROOT / "data" / "copies" / "source_x")
        v = [v for v in res.violations if v.rule_id == "CAPACITY_EXCEEDED"]
        self.assertTrue(v)
        self.assertAlmostEqual(float(v[0].excess), 2.0)

    def test_unknown_source_and_missing_fields(self):
        raw = base_plan()
        raw["decisions"]["supply_orders"].append({"source_id": "Z", "year": 2036, "volume_t": 5})
        self.assertIn("UNKNOWN_SOURCE", rules(run_dict(raw)))
        with self.assertRaises(PlanError):
            Plan.from_dict({"plan_id": "x"})
        with self.assertRaises(PlanError):
            Plan.from_dict({"plan_id": "x", "scenario_id": "BASE", "decisions": {"supply_orders": [{"source_id": "A", "year": 2035, "volume_t": "abc"}],
                                                                                 "capacity_reservations": [], "investments": [], "inventory_policy": {}}})

    def test_bad_date(self):
        raw = base_plan()
        raw["decisions"]["investments"][1]["decision_date"] = "2036-02-29"
        with self.assertRaises(PlanError) as ctx:
            Plan.from_dict(raw)
        self.assertIn("29 February", str(ctx.exception))


class TestBoundary(unittest.TestCase):
    def test_zero_demand_service_level_defined(self):
        self.assertEqual(service_level(0.0, 0.0), 1.0)
        raw = base_plan()
        case = load_case(CASE_DIR)
        params, _ = load_assumptions()
        scen = Scenario(scenario_id="TEAM_ZERO_2035", demand_multiplier={2035: 0.0, "default": 1.0})
        res = run(case, Plan.from_dict(raw), scen, params, keep_daily=False)
        r35 = [r for r in res.yearly if r["year"] == 2035][0]
        self.assertEqual(r35["SL_total"], 1.0)
        self.assertEqual(r35["cost_per_served_t_mln"], None)

    def test_order_above_capacity_and_reservation(self):
        raw = base_plan()
        for o in raw["decisions"]["supply_orders"]:
            if o["source_id"] == "A" and o.get("year") == 2035:
                o["volume_t"] = 200.0
        res = run_dict(raw)
        self.assertIn("CAPACITY_EXCEEDED", rules(res))
        self.assertIn("ORDER_EXCEEDS_RESERVATION", rules(res))
        self.assertFalse(res.feasible)

    def test_reservation_above_capacity(self):
        raw = base_plan()
        raw["decisions"]["capacity_reservations"].append({"source_id": "B", "year": 2036, "reserved_t_per_year": 500})
        self.assertIn("CAPACITY_EXCEEDED", rules(run_dict(raw)))

    def test_storage_overflow_is_flagged_not_hidden(self):
        raw = base_plan()
        for o in raw["decisions"]["supply_orders"]:
            if o["source_id"] == "A" and o.get("year") == 2035:
                o["volume_t"] = 190.0   # 190*0.955 - 100 + 12.4 = 93.9 t > 70 t base storage
        res = run_dict(raw)
        self.assertIn("STORAGE_OVERFLOW", rules(res))
        r35 = [r for r in res.yearly if r["year"] == 2035][0]
        self.assertLessEqual(r35["closing_inventory_t"], 70.0 + 1e-9)

    def test_lead_time_violation(self):
        raw = base_plan()
        raw["decisions"]["supply_orders"].append({"source_id": "A", "year": 2036, "volume_t": 1.0, "decided_on": "2035-06-01"})
        self.assertIn("LEAD_TIME_VIOLATION", rules(run_dict(raw)))

    def test_emergency_streak(self):
        raw = base_plan()
        for y in (2036, 2037, 2038):
            raw["decisions"]["supply_orders"].append({"source_id": "E", "year": y, "volume_t": 20.0, "role": "planned"})
        self.assertIn("EMERGENCY_BASE_STREAK", rules(run_dict(raw)))

    def test_no_zbo_breaks_stress_loss_ceiling(self):
        raw = base_plan()
        raw["decisions"]["investments"] = [i for i in raw["decisions"]["investments"] if i["investment_id"] != "ZBO"]
        res = run_dict(raw, scenario="MANDATORY_STRESS")
        v = [v for v in res.violations if v.rule_id == "STRESS_LOSS_LIMIT"]
        self.assertTrue(v)
        self.assertAlmostEqual(float(v[0].actual), 0.045, places=9)
        self.assertNotIn("STRESS_LOSS_LIMIT", rules(run_dict(raw, scenario="BASE")))

    def test_isru_stress_share_and_payment_for_ordered(self):
        raw = base_plan()
        raw["decisions"]["investments"].append({"investment_id": "LUNAR_ISRU", "financing_date": "2037-06-01"})
        raw["decisions"]["supply_orders"].append({"source_id": "D", "year": 2038, "volume_t": 100.0})
        res = run_dict(raw, scenario="MANDATORY_STRESS")
        row = [r for r in res.source_year if r["year"] == 2038 and r["source_id"] == "D"][0]
        self.assertAlmostEqual(row["scheduled_t"], 100.0)
        self.assertAlmostEqual(row["delivered_t"], 55.0, places=6)
        self.assertAlmostEqual(row["procurement_mln"], 300.0)
        row39 = [r for r in res.yearly if r["year"] == 2038][0]
        self.assertAlmostEqual(row39["opex_isru_mln"], 70.0)
        self.assertAlmostEqual(row39["cumulative_capex_mln"], 540.0 + 1250.0)

    def test_isru_financed_late(self):
        raw = base_plan()
        raw["decisions"]["investments"].append({"investment_id": "LUNAR_ISRU", "financing_date": "2038-03-01"})
        raw["decisions"]["supply_orders"].append({"source_id": "D", "year": 2038, "volume_t": 100.0})
        res = run_dict(raw)
        self.assertIn("INVESTMENT_NOT_FINANCED", rules(res))
        self.assertIn("SOURCE_NOT_AVAILABLE", rules(res))

    def test_zbo_before_2036(self):
        raw = base_plan()
        raw["decisions"]["investments"][1]["decision_date"] = "2035-06-01"
        self.assertIn("INVESTMENT_NOT_AVAILABLE", rules(run_dict(raw)))

    def test_capex_limit(self):
        raw = base_plan()
        raw["decisions"]["investments"].append({"investment_id": "LUNAR_ISRU", "financing_date": "2037-06-01"})
        res = run_dict(raw)
        self.assertNotIn("CAPEX_2037", rules(res))
        chk = [c for c in res.checks if c["rule_id"] == "CAPEX_2037"][0]
        self.assertAlmostEqual(chk["actual"], 1790.0)


class TestDeterminism(unittest.TestCase):
    def test_same_hash_twice_and_roundtrip(self):
        raw = base_plan()
        h1 = canonical_hash(run_dict(raw))
        h2 = canonical_hash(run_dict(copy.deepcopy(raw)))
        self.assertEqual(h1, h2)
        plan = Plan.from_dict(raw)
        again = Plan.from_dict(plan.to_dict())
        self.assertEqual(canonical_hash(run_dict(again.to_dict())), h1)

    def test_low_high_demand_keep_critical_share(self):
        raw = base_plan()
        res = run_dict(raw, scenario="HIGH_DEMAND")
        r38 = [r for r in res.yearly if r["year"] == 2038][0]
        self.assertAlmostEqual(r38["demand_total_t"], 312.5)
        self.assertAlmostEqual(r38["demand_critical_t"], 312.5 * 170 / 250)


if __name__ == "__main__":
    unittest.main()
