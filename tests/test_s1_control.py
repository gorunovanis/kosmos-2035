"""Independent control: the engine must reproduce the reference calculation of the S1 plan made
without access to this code (Astra, s1_reference.py, 2026-09-19, CPython 3.13, daily 365-day model).
Reference numbers are copied from results/yearly.csv and verification_run.log of that package."""
import unittest

from kosmo.api import CASE_DIR, CONFIG_DIR, load_assumptions, get_scenario
from kosmo.case import load_case
from kosmo.engine import run
from kosmo.plan import Plan

REF_BASE_2037 = dict(opening_inventory_t=30.818999999997803, delivered_t=198.0, losses_t=2.3760000000000097,
                     served_total_t=190.0, served_critical_t=135.0, shortage_total_t=0.0, closing_inventory_t=36.44299999999862,
                     mean_inventory_t=33.898978082190006, procurement_mln=1286.1, reservation_mln=169.0,
                     holding_mln=24.407264219176803, opex_zbo_mln=12.0, capex_mln=0.0, total_expense_mln=1491.5072642191767,
                     discounted_expense_mln=1302.7402080698548, cost_per_served_t_mln=7.850038232732509,
                     required_opening_reserve_t=23.424657534246574)
REF_BASE_2035 = dict(opening_inventory_t=12.4, delivered_t=133.0, losses_t=5.985, closing_inventory_t=39.415,
                     mean_inventory_t=26.081493150685194, procurement_mln=824.6, reservation_mln=130.0,
                     holding_mln=18.77867506849334, capex_mln=360.0, preparation_cost_mln=118.09960668435775,
                     total_expense_mln=1451.4782817528512)
REF_STRESS_2039 = dict(demand_total_t=368.0, demand_critical_t=241.5, required_opening_reserve_t=45.36986301369863,
                       opening_inventory_t=1.952054794519808, delivered_t=332.62159613998296, losses_t=3.9914591536797865,
                       served_total_t=330.5821917808218, served_critical_t=241.5, shortage_total_t=37.4178082191782,
                       shortage_critical_t=0.0, closing_inventory_t=0.0, SL_total=0.8983211733174505, SL_critical=1.0,
                       mean_inventory_t=0.4985851260998514, procurement_mln=2535.9152570572896, reservation_mln=169.0,
                       holding_mln=0.358981290791893, total_expense_mln=2717.2742383480813,
                       discounted_expense_mln=2072.9955062558365, first_shortage_date="2039-01-19", shortage_days=347)
REF_HORIZON = {
    ("S1_new18", "BASE"): dict(total_expense_mln=11379.084024727646, discounted_expense_mln=9341.559333587507,
                               served_total_t=1390.0, shortage_total_t=0.0, cumulative_capex_mln=540.0),
    ("S1_new18", "MANDATORY_STRESS"): dict(total_expense_mln=11916.570422226296, discounted_expense_mln=9768.339091287113,
                                           served_total_t=1438.0821917808248, shortage_total_t=95.91780821917519),
    ("S1_new18_stress_prepared", "MANDATORY_STRESS"): dict(total_expense_mln=13472.73098669619,
                                                           discounted_expense_mln=10954.94836602093,
                                                           served_total_t=1534.0, shortage_total_t=0.0,
                                                           closing_inventory_t=55.294520547945226),
    # 24-month branch (Astra runs BASE_NEW24 and STRESS_PREPARED_NEW24): the chosen plan of the team
    ("S1_new24", "BASE"): dict(total_expense_mln=11326.028539935425, discounted_expense_mln=9293.025759907772,
                               served_total_t=1390.0, shortage_total_t=0.0, cumulative_capex_mln=540.0),
    ("S1_new24_stress_prepared", "MANDATORY_STRESS"): dict(total_expense_mln=13418.792772160752,
                                                           discounted_expense_mln=10907.44738767115,
                                                           served_total_t=1534.0, shortage_total_t=0.0),
}
REF_NEW24_2037 = dict(delivered_t=192.3106455548787, losses_t=2.307727746658528, closing_inventory_t=30.821917808216526,
                      procurement_mln=1221.816413399146, reservation_mln=149.66027397260274, holding_mln=16.59872100281296,
                      total_expense_mln=1400.0754083745617)


def _run(plan_name, scenario):
    case = load_case(CASE_DIR)
    plan = Plan.load(CONFIG_DIR / "plans" / f"{plan_name}.json")
    params, _ = load_assumptions()
    return run(case, plan, get_scenario(case, scenario), params)


class TestS1Control(unittest.TestCase):
    def assert_row(self, row, ref, tol=1e-6):
        for k, v in ref.items():
            got = row[k]
            if isinstance(v, str) or v is None:
                self.assertEqual(got, v, msg=k)
            else:
                self.assertAlmostEqual(float(got), float(v), delta=tol * max(1.0, abs(float(v))), msg=f"{k}: got {got} expected {v}")

    def test_base_2035_and_2037(self):
        res = _run("S1_new18", "BASE")
        rows = {r["year"]: r for r in res.yearly}
        self.assert_row(rows[2035], REF_BASE_2035)
        self.assert_row(rows[2037], REF_BASE_2037)
        self.assertTrue(res.feasible, [v.as_dict() for v in res.violations])

    def test_stress_fixed_2039(self):
        res = _run("S1_new18", "MANDATORY_STRESS")
        rows = {r["year"]: r for r in res.yearly}
        self.assert_row(rows[2039], REF_STRESS_2039)
        ids = {(v.rule_id, v.period) for v in res.violations}
        self.assertIn(("RESERVE_45D", "2039-01-01"), ids)
        self.assertIn(("RESERVE_45D", "2040-01-01"), ids)
        self.assertIn(("TOTAL_SERVICE_REFERENCE", "2039"), ids)
        # price shock resets in 2040
        src = {(r["year"], r["source_id"]): r for r in res.source_year}
        self.assertAlmostEqual(src[(2039, "A")]["unit_price_mln_per_t"], 7.75)
        self.assertAlmostEqual(src[(2040, "A")]["unit_price_mln_per_t"], 6.2)

    def test_horizons(self):
        for (plan, scen), ref in REF_HORIZON.items():
            res = _run(plan, scen)
            for k, v in ref.items():
                self.assertAlmostEqual(float(res.horizon[k]), float(v), delta=1e-6 * max(1.0, abs(v)), msg=f"{plan}/{scen}/{k}")

    def test_new24_partial_year_2037(self):
        """Earth-New commissioned 2037-07-01: 184 active days, prorated capacity, TOP and reservation."""
        res = _run("S1_new24", "BASE")
        rows = {r["year"]: r for r in res.yearly}
        self.assert_row(rows[2037], REF_NEW24_2037)
        src = {(r["year"], r["source_id"]): r for r in res.source_year}
        c37 = src[(2037, "C")]
        self.assertAlmostEqual(c37["contract_period_fraction"], 184 / 365, places=9)
        self.assertAlmostEqual(c37["top_minimum_t"], 0.5 * 130 * 184 / 365, places=6)
        self.assertAlmostEqual(c37["reservation_mln"], 0.30 * 130 * 184 / 365, places=6)

    def test_prepared_stress_is_feasible(self):
        res = _run("S1_new18_stress_prepared", "MANDATORY_STRESS")
        self.assertTrue(res.feasible, [v.as_dict() for v in res.violations])
        for r in res.yearly:
            if r["year"] >= 2038:
                self.assertLessEqual(r["loss_ratio"], 0.02 + 1e-12)


if __name__ == "__main__":
    unittest.main()
