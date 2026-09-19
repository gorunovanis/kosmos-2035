"""Operator workstation of the fuel node: entry point. Run with `streamlit run app/streamlit_app.py`."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CASE_DIRS, init_state, plan_files, load_plan_file, scenario_label, scenario_options, set_plan  # noqa: E402

st.set_page_config(page_title="Космоконтур 2035", page_icon=":material/rocket_launch:", layout="wide")
init_state()

pages = {
    "": [
        st.Page("app_pages/overview.py", title="Обзор", icon=":material/dashboard:", default=True),
        st.Page("app_pages/plan.py", title="План и контракты", icon=":material/edit_calendar:"),
        st.Page("app_pages/checks.py", title="Проверки и нарушения", icon=":material/rule:"),
        st.Page("app_pages/compare.py", title="Сценарии и сравнение", icon=":material/compare_arrows:"),
    ],
    "Анализ": [
        st.Page("app_pages/sensitivity.py", title="Чувствительность", icon=":material/query_stats:"),
        st.Page("app_pages/risks.py", title="Риски и стороны", icon=":material/warning:"),
        st.Page("app_pages/geo.py", title="Геополитика", icon=":material/public:"),
    ],
    "Данные": [
        st.Page("app_pages/export.py", title="Сохранение и выгрузка", icon=":material/save:"),
        st.Page("app_pages/assumptions.py", title="Данные и допущения", icon=":material/database:"),
        st.Page("app_pages/how.py", title="Как проверить", icon=":material/help:"),
    ],
}
page = st.navigation(pages)

with st.sidebar:
    st.markdown("**Рабочее место оператора**")
    st.caption("Топливный космоконтур 2035 · один расчётный контур для экрана, CLI и выгрузок")
    keys = list(CASE_DIRS)
    st.session_state.case_key = st.selectbox("Набор данных", keys, index=keys.index(st.session_state.case_key), key="case_select")
    opts = scenario_options()
    if st.session_state.scenario_id not in opts:
        st.session_state.scenario_id = opts[0]
    st.session_state.scenario_id = st.selectbox("Сценарий расчёта", opts, index=opts.index(st.session_state.scenario_id),
                                                format_func=scenario_label, key="scenario_select")
    files = plan_files()
    names = list(files)
    current = st.session_state.get("plan_name", names[0])
    picked = st.selectbox("Открыть сохранённый план", names, index=names.index(current) if current in names else 0, key="plan_select")
    if st.button("Загрузить выбранный план", icon=":material/folder_open:", width="stretch"):
        set_plan(load_plan_file(files[picked]), picked)
        st.toast(f"Открыт план {picked}")
        st.rerun()
    st.caption(f"Текущий план: **{st.session_state.get('plan_name', '—')}**")
    if st.session_state.get("geo_event"):
        st.badge("Гео-событие активно", icon=":material/public:", color="orange")

st.title(page.title, icon=page.icon)
page.run()
