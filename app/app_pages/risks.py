import json

import pandas as pd
import streamlit as st

from common import CONFIG_DIR, assumptions, case, case_dir, fmt_mln, fmt_t, plan_json, status_line, try_run
from kosmo.plan import Plan
from kosmo.risks import evaluate_risks, load_risks, stakeholder_table, mcda_profiles

c = case()
res = try_run(with_geo=False)
if res is None:
    st.stop()
status_line(res)

st.caption("Реестр рисков нашего плана: каждый риск — исполняемый сценарий на копии данных. Последствия считаются ядром в тоннах, млн, сервисе и днях; мера — второй прогон с изменённым решением; остаточный риск — разница. Обязательный стресс не оценивается здесь повторно.")


@st.cache_data(show_spinner="Считаю риски…", max_entries=16)
def _risks(plan_s: str, sid: str, cdir: str, params_s: str):
    from kosmo.case import load_case
    from kosmo.api import all_scenarios
    cc = load_case(cdir)
    plan = Plan.from_dict(json.loads(plan_s))
    return evaluate_risks(cc, plan, all_scenarios(cc)[sid], json.loads(params_s), load_risks(CONFIG_DIR / "risks"))


rows = _risks(plan_json(), st.session_state.scenario_id, str(case_dir()), json.dumps(assumptions(), sort_keys=True))
if rows:
    df = pd.DataFrame(rows)
    with st.container(border=True):
        st.subheader("Реестр рисков с рассчитанными последствиями", icon=":material/warning:")
        show = df[["risk_id", "event", "cause", "affected_parameter", "period", "probability_basis", "owner",
                   "delta_shortage_t", "delta_pv_mln", "SL_total_min", "feasible", "mitigation", "mitigation_cost_pv_mln", "residual_shortage_t", "residual_pv_mln", "dependencies"]].rename(columns={
            "risk_id": "ID", "event": "Событие", "cause": "Причина", "affected_parameter": "Параметр", "period": "Период", "probability_basis": "Основание диапазона",
            "owner": "Владелец", "delta_shortage_t": "Δ дефицит, т", "delta_pv_mln": "Δ PV, млн", "SL_total_min": "SL min", "feasible": "Исполним",
            "mitigation": "Мера", "mitigation_cost_pv_mln": "Стоимость меры, млн PV", "residual_shortage_t": "Остаточный дефицит, т", "residual_pv_mln": "Остаточный Δ PV, млн", "dependencies": "Зависимости"})
        st.dataframe(show, hide_index=True, column_config={"SL min": st.column_config.NumberColumn(format="percent"),
                                                           "Δ PV, млн": st.column_config.NumberColumn(format="%.0f"), "Стоимость меры, млн PV": st.column_config.NumberColumn(format="%.0f"),
                                                           "Остаточный Δ PV, млн": st.column_config.NumberColumn(format="%.0f")})
        st.caption("Δ считается относительно текущего плана в текущем сценарии. Мера применяется к плану (например, дозаказ Flex с лагом 122 дня) и пересчитывается тем же ядром; её стоимость — разница PV. Произведение баллов не используется.")
        st.download_button("Скачать реестр (CSV)", data=df.to_csv(index=False).encode("utf-8"), file_name="risk_register.csv", mime="text/csv", icon=":material/download:")
else:
    st.info("Файлы рисков в configs/risks не найдены.", icon=":material/info:")

with st.container(border=True):
    st.subheader("Стороны: интересы, показатели, кто платит", icon=":material/groups:")
    st.dataframe(pd.DataFrame(stakeholder_table(res, c)), hide_index=True)
    st.caption("Показатели берутся из текущего прогона: критические потребители смотрят на SL критический и резерв, коммерческие — на SL общий и стоимость тонны, поставщики — на зарезервированный и оплаченный объём, финансирующая сторона — на CAPEX и приведённые расходы, оператор — на исполнимость и гибкость.")

with st.container(border=True):
    st.subheader("Чувствительность ранжирования к весам сторон", icon=":material/balance:")
    st.caption("Профили весов не выбирают план: выбор задан правилом до расчёта. Здесь показано, меняется ли порядок стратегий при разных обоснованных приоритетах. Нормализация min-max по каждому критерию, ограничение критического сервиса не взвешивается: планы с дефицитом критического спроса исключаются заранее.")
    prof = mcda_profiles(str(case_dir()), json.dumps(assumptions(), sort_keys=True))
    if prof:
        st.dataframe(pd.DataFrame(prof), hide_index=True)
