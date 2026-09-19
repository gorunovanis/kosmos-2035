"""Shared helpers of the operator UI. All numbers come from kosmo.engine; the UI only edits the plan
and displays results."""
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from kosmo import calendar as cal  # noqa: E402
from kosmo.api import CASE_DIR, CONFIG_DIR, PROJECT_ROOT, RESULTS_DIR, all_scenarios, code_version, load_assumptions  # noqa: E402
from kosmo.case import Case, CaseError, case_fingerprint, load_case  # noqa: E402
from kosmo.engine import RunResult, run  # noqa: E402
from kosmo.export import CHECK_COLUMNS, SOURCE_COLUMNS, VIOL_COLUMNS, YEARLY_COLUMNS, canonical_hash, export_run  # noqa: E402
from kosmo.plan import Plan, PlanError  # noqa: E402
from kosmo.scenario import apply_geo_event  # noqa: E402

CASE_DIRS = {
    "Контрольный набор организатора": CASE_DIR,
    "Копия: Source-X (шестой источник)": PROJECT_ROOT / "data" / "copies" / "source_x",
    "Копия: горизонт 2041": PROJECT_ROOT / "data" / "copies" / "horizon_2041",
}
SCENARIO_LABELS = {
    "BASE": "BASE: стандартный",
    "MANDATORY_STRESS": "MANDATORY_STRESS: обязательный стресс",
    "LOW_DEMAND": "LOW_DEMAND: низкий спрос",
    "HIGH_DEMAND": "HIGH_DEMAND: высокий спрос",
}
DEFAULT_PLAN = "S1_new24"

RULE_HINTS = {
    "BASE_TOTAL_SERVICE": "увеличить отбор у доступного канала в этом году или запас на начало года; проверить резерв мощности",
    "BASE_CRITICAL_SERVICE": "критический спрос не обеспечен: нужен запас на начало года или дозаказ",
    "TOTAL_SERVICE_REFERENCE": "в стрессе: подготовить отбор Flex/Earth-New заранее или показать стоимость дефицита; бюджет и мощности не растут",
    "CRITICAL_SERVICE_REFERENCE": "критический спрос в стрессе: запас на 1 января и дозаказ с учётом lead time",
    "RESERVE_45D": "поднять запас на конец предыдущего года (больше отбора в году до), или подготовленный план под сценарий",
    "CAPEX_2037": "перенести часть инвестиций после 2037 (Earth-New 270, ZBO 180) или отказаться от одной опции",
    "CAPEX_2040": "суммарные вложения выше 2 800: убрать инвестицию",
    "STRESS_LOSS_LIMIT": "ввести ZBO до 2038 (потери 1,2 % вместо 4,5 %)",
    "EMERGENCY_BASE_STREAK": "Emergency не может быть базой более двух лет подряд: заменить на Flex/Earth-New/ISRU",
    "CAPACITY_EXCEEDED": "снизить резерв или отбор до мощности канала",
    "ORDER_EXCEEDS_RESERVATION": "увеличить резерв мощности на год или снизить отбор",
    "STORAGE_OVERFLOW": "уменьшить отбор в году или отложить поставку; ёмкость 70 т (120 т после ZBO)",
    "LEAD_TIME_VIOLATION": "дата решения слишком поздняя для срока поставки канала",
    "SOURCE_NOT_AVAILABLE": "канал ещё не введён: проверить даты инвестиций и окно поставки",
    "INVESTMENT_NOT_FINANCED": "Lunar-ISRU финансируется до 31.12.2037",
    "INVESTMENT_NOT_AVAILABLE": "опция ZBO доступна с 2036, реализация Earth-New после покупки права",
    "UNKNOWN_SOURCE": "неизвестный канал в плане",
    "INVALID_INPUT": "исправить поле плана",
    "NEGATIVE_VALUE": "отрицательные значения недопустимы",
}


@st.cache_resource(show_spinner=False)
def get_case(case_dir: str) -> Case:
    return load_case(case_dir)


def case_key() -> str:
    return st.session_state.get("case_key", list(CASE_DIRS)[0])


def case_dir() -> Path:
    return CASE_DIRS[case_key()]


def case() -> Case:
    return get_case(str(case_dir()))


def assumptions() -> dict:
    params, _ = load_assumptions()
    rate = st.session_state.get("discount_rate_override")
    if rate is not None:
        params["discount_rate"] = float(rate)
    return params


def assumption_rows() -> list[dict]:
    return load_assumptions()[1]


def load_plan_file(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def plan_files() -> dict[str, Path]:
    """Plans from configs/plans plus plans saved by the operator into results/ (generated runs of the
    same config plans are skipped to keep the list short)."""
    out = {}
    known = set()
    for p in sorted((CONFIG_DIR / "plans").glob("*.json")):
        out[p.stem] = p
        known.add(p.stem)
    for p in sorted(RESULTS_DIR.glob("*/plan.json")):
        name = p.parent.name
        base = name.split("__")[0]
        if base in known or name.startswith(("extension_", "invalid_demo")):
            continue
        out[f"results/{name}"] = p
    return out


def init_state() -> None:
    st.session_state.setdefault("case_key", list(CASE_DIRS)[0])
    st.session_state.setdefault("scenario_id", "BASE")
    st.session_state.setdefault("geo_event", None)
    st.session_state.setdefault("discount_rate_override", None)
    if "plan" not in st.session_state:
        files = plan_files()
        name = DEFAULT_PLAN if DEFAULT_PLAN in files else next(iter(files))
        st.session_state.plan = load_plan_file(files[name])
        st.session_state.plan_name = name


def plan_json() -> str:
    return json.dumps(st.session_state.plan, ensure_ascii=False, sort_keys=True)


@st.cache_data(show_spinner=False, max_entries=256)
def _run_cached(plan_json_s: str, scenario_id: str, case_dir_s: str, params_json: str, geo_json: str) -> RunResult:
    c = get_case(case_dir_s)
    plan = Plan.from_dict(json.loads(plan_json_s))
    scen = all_scenarios(c)[scenario_id]
    if geo_json:
        scen = apply_geo_event(scen, json.loads(geo_json), c)
    return run(c, plan, scen, json.loads(params_json), keep_daily=True)


def run_current(scenario_id: str | None = None, with_geo: bool = True) -> RunResult:
    sid = scenario_id or st.session_state.scenario_id
    geo = st.session_state.get("geo_event") if with_geo else None
    return _run_cached(plan_json(), sid, str(case_dir()), json.dumps(assumptions(), sort_keys=True),
                       json.dumps(geo, sort_keys=True) if geo else "")


def try_run(scenario_id: str | None = None, with_geo: bool = True) -> RunResult | None:
    """Runs the current plan; shows a readable error and returns None on invalid input."""
    try:
        return run_current(scenario_id, with_geo)
    except PlanError as exc:
        st.error(f"План не прошёл проверку ввода: {exc}", icon=":material/error:")
    except CaseError as exc:
        st.error(f"Ошибка данных: {exc}", icon=":material/error:")
    except KeyError as exc:
        st.error(f"Сценарий не найден: {exc}", icon=":material/error:")
    return None


def scenario_options() -> list[str]:
    scen = all_scenarios(case())
    order = [s for s in SCENARIO_LABELS if s in scen] + sorted(s for s in scen if s not in SCENARIO_LABELS)
    return order


def scenario_label(sid: str) -> str:
    return SCENARIO_LABELS.get(sid, sid)


# ------------------------------------------------------------------ dataframes
YEARLY_RU = {
    "year": "Год", "demand_total_t": "Спрос, т", "demand_critical_t": "Крит. спрос, т",
    "required_opening_reserve_t": "Резерв 45 дн, т", "opening_inventory_t": "Запас на 1 янв, т",
    "scheduled_t": "Заказано, т", "delivered_t": "Доставлено, т", "losses_t": "Потери, т", "loss_ratio": "Потери/оборот",
    "served_total_t": "Выдано, т", "served_critical_t": "Выдано крит., т", "shortage_total_t": "Дефицит, т",
    "shortage_critical_t": "Дефицит крит., т", "closing_inventory_t": "Запас на конец, т", "SL_total": "SL общий",
    "SL_critical": "SL критический", "mean_inventory_t": "Средний запас, т", "peak_before_losses_t": "Пик запаса, т",
    "first_shortage_date": "Первый дефицит", "shortage_days": "Дней с дефицитом",
    "procurement_mln": "Закупка, млн", "reservation_mln": "Резервирование, млн", "holding_mln": "Хранение, млн",
    "opex_zbo_mln": "OPEX ZBO, млн", "opex_isru_mln": "OPEX ISRU, млн", "capex_mln": "CAPEX, млн",
    "cumulative_capex_mln": "CAPEX накопл., млн", "preparation_cost_mln": "Подготовка 2034, млн",
    "total_expense_mln": "Расходы, млн", "discount_factor": "Коэф. дисконта", "discounted_expense_mln": "PV расходов, млн",
    "cost_per_served_t_mln": "Стоимость тонны, млн/т", "pv_per_served_t_mln": "PV на тонну, млн/т",
}


def yearly_df(res: RunResult) -> pd.DataFrame:
    return pd.DataFrame([{c: r.get(c) for c in YEARLY_COLUMNS if c not in ("scenario_id", "plan_id")} for r in res.yearly])


def source_df(res: RunResult) -> pd.DataFrame:
    return pd.DataFrame([{c: r.get(c) for c in SOURCE_COLUMNS} for r in res.source_year])


def checks_df(res: RunResult) -> pd.DataFrame:
    df = pd.DataFrame([{c: r.get(c) for c in CHECK_COLUMNS} for r in res.checks])
    if not df.empty:
        df["status_ru"] = df["status"].map({"PASS": "✓ выполнено", "FAIL": "✗ нарушение"})
    return df


def violations_df(res: RunResult) -> pd.DataFrame:
    rows = []
    for v in res.violations:
        d = v.as_dict()
        d["hint"] = RULE_HINTS.get(v.rule_id, "")
        rows.append(d)
    return pd.DataFrame(rows, columns=VIOL_COLUMNS + ["hint"])


def daily_df(res: RunResult) -> pd.DataFrame:
    return pd.DataFrame(res.daily)


def supply_by_source_df(res: RunResult, c: Case) -> pd.DataFrame:
    rows = []
    for r in res.yearly:
        for sid, v in r["delivered_by_source"].items():
            if v > 1e-9:
                rows.append({"Год": r["year"], "Канал": c.sources[sid].name, "Доставлено, т": v})
    return pd.DataFrame(rows)


def fmt_mln(x: float | None) -> str:
    return "—" if x is None else f"{x:,.0f}".replace(",", " ")


def fmt_t(x: float | None) -> str:
    return "—" if x is None else f"{x:,.1f}".replace(",", " ")


def fmt_pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.1f} %"


def status_line(res: RunResult) -> None:
    hard = [v for v in res.violations if v.severity == "hard"]
    ref = [v for v in res.violations if v.severity == "reference"]
    with st.container(horizontal=True):
        if not hard:
            st.badge("План исполним", icon=":material/check_circle:", color="green")
        else:
            st.badge(f"План неисполним: {len(hard)} жёстких нарушений", icon=":material/error:", color="red")
        if ref:
            st.badge(f"Ниже ориентира сервиса в стрессе: {len(ref)}", icon=":material/warning:", color="orange")
        st.badge(f"Сценарий {res.scenario_id}", icon=":material/tune:", color="blue")
        st.badge(f"План {res.plan_id}", icon=":material/description:", color="gray")


def export_bundle_bytes(res: RunResult) -> tuple[bytes, bytes, dict]:
    """Returns (zip of CSVs + meta + plan, xlsx bytes, meta)."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "export"
        meta = export_run(res, out, assumptions_rows=assumption_rows(), code_version=code_version(),
                          case_fingerprint=case_fingerprint(case()))
        (out / "plan.json").write_text(json.dumps(st.session_state.plan, ensure_ascii=False, indent=2), encoding="utf-8")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(out.iterdir()):
                z.write(p, arcname=p.name)
        xlsx = (out / "export.xlsx").read_bytes() if (out / "export.xlsx").exists() else b""
    return buf.getvalue(), xlsx, meta


def save_to_results(res: RunResult, name: str) -> Path:
    out = RESULTS_DIR / name
    export_run(res, out, assumptions_rows=assumption_rows(), code_version=code_version(), case_fingerprint=case_fingerprint(case()))
    (out / "plan.json").write_text(json.dumps(st.session_state.plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def set_plan(raw: dict, name: str) -> None:
    st.session_state.plan = raw
    st.session_state.plan_name = name
