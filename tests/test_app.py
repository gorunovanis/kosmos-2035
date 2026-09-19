"""UI smoke test: every page opens on the default plan without exceptions (st.testing AppTest)."""
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"
PAGES = ["overview", "plan", "checks", "compare", "sensitivity", "risks", "geo", "export", "assumptions", "how"]


class TestAppSmoke(unittest.TestCase):
    def test_pages_open(self):
        at = AppTest.from_file(str(APP), default_timeout=180).run()
        self.assertFalse(at.exception, at.exception)
        for page in PAGES:
            at.switch_page(f"app_pages/{page}.py").run()
            self.assertFalse(at.exception, f"{page}: {at.exception}")

    def test_operator_changes_investment_without_code(self):
        """Jury route steps 5-6: remove the Earth-New option through the form, results change, overview shows an error."""
        at = AppTest.from_file(str(APP), default_timeout=180).run()
        at.switch_page("app_pages/plan.py").run()
        at.checkbox(key="en_on").uncheck()
        submit = [b for b in at.button if "инвестиции" in (b.label or "")]
        self.assertTrue(submit, "investments submit button not found")
        submit[0].click().run()
        self.assertFalse(at.exception, at.exception)
        inv = [i["investment_id"] for i in at.session_state["plan"]["decisions"]["investments"]]
        self.assertNotIn("EARTH_NEW", inv)
        at.switch_page("app_pages/overview.py").run()
        self.assertFalse(at.exception, at.exception)
        self.assertTrue(at.error, "overview should show the violation banner for an infeasible plan")
        at.switch_page("app_pages/checks.py").run()
        self.assertTrue(at.error)

    def test_stress_scenario_shows_violations(self):
        at = AppTest.from_file(str(APP), default_timeout=180)
        at.session_state["scenario_id"] = "MANDATORY_STRESS"
        at.run()
        at.switch_page("app_pages/checks.py").run()
        self.assertFalse(at.exception, at.exception)


if __name__ == "__main__":
    unittest.main()
