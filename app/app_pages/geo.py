import json

import pandas as pd
import streamlit as st

from common import CONFIG_DIR, case, fmt_mln, fmt_pct, fmt_t, scenario_label, status_line, try_run
from kosmo.compare import summarize

c = case()
st.caption("Исследовательский блок (бонус). Событие меняет составляющую агрегированной цены канала на период. Работает на копии сценария: контрольные сценарии BASE и MANDATORY_STRESS не меняются, кнопка «Вернуть контрольные цены» снимает событие. Это условные сценарии, не прогноз событий; вероятности не назначаются.")

try:
    presets = json.loads((CONFIG_DIR / "geo_events.json").read_text(encoding="utf-8"))
except FileNotFoundError:
    presets = []

with st.container(border=True):
    st.subheader("Событие", icon=":material/public:")
    names = ["— своё событие —"] + [p["event_label"] for p in presets]
    pick = st.selectbox("Готовые исследовательские сценарии", names, key="geo_preset")
    preset = next((p for p in presets if p["event_label"] == pick), None)
    cur = st.session_state.get("geo_event") or {}
    with st.form("geo_form"):
        label = st.text_input("Название события", value=(preset or cur).get("event_label", "Ограничение доступа к запусковым услугам"))
        srcs = st.multiselect("Затронутые каналы", [s.name for s in c.sources.values()], default=(preset or cur).get("affected_sources", ["Earth-New"]))
        comp = st.selectbox("Составляющая цены", ["variable_price", "reservation_rate", "capacity"], index=["variable_price", "reservation_rate", "capacity"].index((preset or cur).get("component", "variable_price")),
                            format_func=lambda x: {"variable_price": "переменная цена (запуск и доставка)", "reservation_rate": "тариф резервирования", "capacity": "мощность канала"}[x])
        y0 = st.number_input("С года", min_value=c.years[0], max_value=c.years[-1], value=int((preset or cur).get("start_year", 2038)))
        y1 = st.number_input("По год", min_value=c.years[0], max_value=c.years[-1], value=int((preset or cur).get("end_year", 2039)))
        share = st.slider("Доля составляющей в агрегированной цене (допущение)", 0.0, 1.0, float((preset or cur).get("component_share", 0.55)), 0.05)
        kc = st.slider("Изменение составляющей, ×", 0.5, 3.0, float((preset or cur).get("component_multiplier", 1.4)), 0.05)
        basis = st.text_area("Основание диапазона (источник или TEAM_ASSUMPTION)", value=(preset or cur).get("basis", "TEAM_ASSUMPTION"), height=80)
        k = 1 + share * (kc - 1)
        st.caption(f"Множитель к агрегированной цене канала: k = 1 + {share:g} × ({kc:g} − 1) = **{k:.3f}**. Формула раскрыта в допущении A12.")
        applied = st.form_submit_button("Применить событие", icon=":material/bolt:")
        if applied:
            if y1 < y0:
                st.error("INVALID_INPUT: год окончания раньше начала", icon=":material/error:")
            elif not srcs:
                st.error("INVALID_INPUT: выберите хотя бы один канал", icon=":material/error:")
            else:
                st.session_state.geo_event = {"event_label": label, "affected_sources": srcs, "component": comp, "start_year": int(y0), "end_year": int(y1),
                                              "multiplier": round(k, 6), "component_share": share, "component_multiplier": kc, "basis": basis}
                st.rerun()
    if st.session_state.get("geo_event") and st.button("Вернуть контрольные цены", icon=":material/restart_alt:"):
        st.session_state.geo_event = None
        st.rerun()

before = try_run(with_geo=False)
after = try_run(with_geo=True) if st.session_state.get("geo_event") else None
if before is None:
    st.stop()
with st.container(border=True):
    st.subheader("До и после", icon=":material/compare:")
    if after is None:
        st.info("Событие не применено: показан контрольный расчёт. Примените событие, чтобы увидеть сравнение.", icon=":material/info:")
        status_line(before)
    else:
        sb, sa = summarize(before, c), summarize(after, c)
        with st.container(horizontal=True):
            st.metric("PV расходов, млн", fmt_mln(sa["discounted_expense_mln"]), delta=f"{sa['discounted_expense_mln'] - sb['discounted_expense_mln']:+,.0f}".replace(",", " "), delta_color="inverse", border=True)
            st.metric("Расходы без дисконта, млн", fmt_mln(sa["total_expense_mln"]), delta=f"{sa['total_expense_mln'] - sb['total_expense_mln']:+,.0f}".replace(",", " "), delta_color="inverse", border=True)
            st.metric("Дефицит, т", fmt_t(sa["shortage_total_t"]), delta=f"{sa['shortage_total_t'] - sb['shortage_total_t']:+.1f}", delta_color="inverse", border=True)
            st.metric("Стоимость тонны, млн/т", f"{sa['cost_per_served_t_mln']:.3f}", delta=f"{sa['cost_per_served_t_mln'] - sb['cost_per_served_t_mln']:+.3f}", delta_color="inverse", border=True)
        rows = []
        for rb, ra in zip(before.yearly, after.yearly):
            rows.append({"Год": rb["year"], "Закупка до, млн": rb["procurement_mln"], "Закупка после, млн": ra["procurement_mln"],
                         "Резерв до, млн": rb["reservation_mln"], "Резерв после, млн": ra["reservation_mln"],
                         "Расходы до, млн": rb["total_expense_mln"], "Расходы после, млн": ra["total_expense_mln"],
                         "Δ, млн": ra["total_expense_mln"] - rb["total_expense_mln"], "Дефицит после, т": ra["shortage_total_t"]})
        st.dataframe(pd.DataFrame(rows), hide_index=True, column_config={k: st.column_config.NumberColumn(format="%.1f") for k in rows[0] if k != "Год"})
        ev = st.session_state.geo_event
        st.caption(f"Причинная цепочка: событие «{ev['event_label']}» → {ev['component']} каналов {', '.join(ev['affected_sources'])} × {ev['multiplier']:.3f} в {ev['start_year']}–{ev['end_year']} → платежи по годам → решения оператора (дозаказ у незатронутых каналов, пересмотр резервов на будущие годы). Параметры события попадают в meta выгрузки.")
        st.download_button("Скачать параметры события (JSON)", data=json.dumps(ev, ensure_ascii=False, indent=2).encode("utf-8"), file_name="geo_event.json", mime="application/json", icon=":material/download:")
