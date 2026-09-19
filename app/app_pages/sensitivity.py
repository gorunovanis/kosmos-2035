import json

import altair as alt
import pandas as pd
import streamlit as st

from common import assumptions, case, case_dir, plan_json, scenario_label, status_line, try_run
from kosmo.api import all_scenarios
from kosmo.plan import Plan
from kosmo.sensitivity import reverse_stress, standard_variations, tornado

c = case()
res = try_run(with_geo=False)
if res is None:
    st.stop()
status_line(res)
st.caption("Параметры варьируются в раскрытых диапазонах при неизменном плане. Каждая точка — отдельный прогон ядра как TEAM-сценарий. Диапазоны: спрос ±20 % как в low/high и +25 %; цены до ×1,35 (стресс задаёт ×1,25); доля поставки ISRU до 0,5; ставка 0–12 %.")


@st.cache_data(show_spinner="Считаю чувствительность…", max_entries=32)
def _tornado(plan_s: str, sid: str, cdir: str, params_s: str):
    from kosmo.case import load_case
    cc = load_case(cdir)
    plan = Plan.from_dict(json.loads(plan_s))
    return tornado(cc, plan, all_scenarios(cc)[sid], json.loads(params_s))


rows = _tornado(plan_json(), st.session_state.scenario_id, str(case_dir()), json.dumps(assumptions(), sort_keys=True))
df = pd.DataFrame(rows)
with st.container(border=True):
    st.subheader("Торнадо: приведённые расходы", icon=":material/align_horizontal_center:")
    long = pd.concat([
        pd.DataFrame({"Параметр": df["parameter"], "Край": [f"низ ({x:g})" for x in df["low_x"]], "Δ PV, млн": df["low_delta"], "Дефицит, т": df["low_shortage_t"], "Исполним": df["low_feasible"]}),
        pd.DataFrame({"Параметр": df["parameter"], "Край": [f"верх ({x:g})" for x in df["high_x"]], "Δ PV, млн": df["high_delta"], "Дефицит, т": df["high_shortage_t"], "Исполним": df["high_feasible"]}),
    ])
    ch = alt.Chart(long).mark_bar().encode(y=alt.Y("Параметр:N", sort=list(df["parameter"]), title=None), x=alt.X("Δ PV, млн:Q", title="Изменение PV расходов, млн"),
                                          color=alt.Color("Край:N", legend=None), tooltip=["Параметр", "Край", alt.Tooltip("Δ PV, млн", format=".0f"), alt.Tooltip("Дефицит, т", format=".1f"), "Исполним"])
    st.altair_chart(ch)
    show = df[["parameter", "basis", "low_x", "low_delta", "low_shortage_t", "low_feasible", "high_x", "high_delta", "high_shortage_t", "high_feasible"]].rename(columns={
        "parameter": "Параметр", "basis": "Основание диапазона", "low_x": "Низ", "low_delta": "Δ PV низ, млн", "low_shortage_t": "Дефицит низ, т", "low_feasible": "Исполним низ",
        "high_x": "Верх", "high_delta": "Δ PV верх, млн", "high_shortage_t": "Дефицит верх, т", "high_feasible": "Исполним верх"})
    st.dataframe(show, hide_index=True, column_config={"Δ PV низ, млн": st.column_config.NumberColumn(format="%.0f"), "Δ PV верх, млн": st.column_config.NumberColumn(format="%.0f")})
    st.caption(f"База: PV {df['base_metric'].iloc[0]:,.0f} млн в сценарии {scenario_label(st.session_state.scenario_id)}. Отрицательная дельта — экономия. Столбец «Исполним» показывает, сохраняется ли исполнимость на краю диапазона.".replace(",", " "))

with st.container(border=True):
    st.subheader("Обратный стресс: порог, после которого план ломается", icon=":material/crisis_alert:")
    st.caption("Сетка, затем бинарный поиск внутри первого интервала, где план перестаёт быть исполнимым (жёсткие нарушения) или теряет полное обслуживание. Монотонность не предполагается: сетка показана целиком.")
    vars_ = standard_variations(all_scenarios(c)[st.session_state.scenario_id])
    pick = st.selectbox("Параметр", [v.name for v in vars_], key="rs_param")
    crit = st.selectbox("Критерий разрушения", ["план неисполним (жёсткое нарушение)", "дефицит общего спроса > 0", "SL общий ниже 0,97"], key="rs_crit")
    v = next(x for x in vars_ if x.name == pick)
    lo = st.number_input("От", value=float(v.low), key="rs_lo")
    hi = st.number_input("До", value=float(v.high * 1.4 if v.param != "rate" else v.high), key="rs_hi")
    if st.button("Найти порог", icon=":material/search:"):
        pred = {"план неисполним (жёсткое нарушение)": lambda r: r.feasible,
                "дефицит общего спроса > 0": lambda r: r.horizon["shortage_total_t"] < 1e-6,
                "SL общий ниже 0,97": lambda r: r.horizon["SL_total_min"] >= 0.97 - 1e-9}[crit]
        out = reverse_stress(c, Plan.from_dict(st.session_state.plan), all_scenarios(c)[st.session_state.scenario_id], assumptions(), v, pred, lo, hi)
        g = pd.DataFrame(out["grid"])
        if out["threshold"] is not None:
            st.success(f"Порог: {v.name} = {out['threshold']:.4g} {v.unit}. До него план выполняет выбранный критерий, после — нет.", icon=":material/flag:")
        elif out["all_ok"]:
            st.info("В заданном диапазоне план не ломается.", icon=":material/check_circle:")
        elif out["none_ok"]:
            st.warning("План не проходит критерий уже на нижней границе диапазона.", icon=":material/warning:")
        else:
            st.warning("Немонотонная картина: смотрите сетку.", icon=":material/warning:")
        st.dataframe(g.rename(columns={"x": v.name, "ok": "Проходит", "shortage_t": "Дефицит, т", "pv_mln": "PV, млн", "SL_min": "SL min", "hard_violations": "Жёстких нарушений"}),
                     hide_index=True, column_config={"SL min": st.column_config.NumberColumn(format="percent"), "PV, млн": st.column_config.NumberColumn(format="%.0f")})
