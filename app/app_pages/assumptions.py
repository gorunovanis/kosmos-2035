import pandas as pd
import streamlit as st

from common import assumption_rows, assumptions, case, case_dir, scenario_label
from kosmo.api import all_scenarios
from kosmo.scenario import effective

c = case()
st.caption(f"Набор: {case_dir()}. Значения организатора (CASE_INPUT) показаны как есть и не редактируются. Копии набора для Source-X и 2041 выбираются в боковой панели.")

tabs = st.tabs(["Спрос", "Каналы", "Хранилище и инвестиции", "Ограничения", "Сценарии", "Допущения команды"])
with tabs[0]:
    st.dataframe(pd.DataFrame([{"Год": d.year, "Базовый общий, т": d.base_total, "Базовый критический, т": d.base_critical,
                                "Низкий общий, т": d.low_total, "Высокий общий, т": d.high_total} for d in c.demand.values()]), hide_index=True)
    st.caption("Критический спрос входит в общий. Для низкого и высокого спроса доля критического сохраняется от базового года.")
with tabs[1]:
    st.dataframe(pd.DataFrame([{"ID": s.source_id, "Канал": s.name, "Мощность, т/год": s.capacity, "Цена, млн/т": s.var_cost,
                                "Тариф резерва, млн за т/год": s.res_rate, "Take-or-pay": s.top_share,
                                "Lead time": f"{s.lead_min:g}–{s.lead_max:g} {s.lead_unit}" if s.lead_min != s.lead_max else f"{s.lead_min:g} {s.lead_unit}",
                                "Надёжность (метаданные)": s.reliability_profile, "Доступен с": s.available_from_year or "после ввода"} for s in c.sources.values()]), hide_index=True)
    st.caption("Надёжность в BASE и обязательном стрессе не применяется как множитель поставки (Постановка с. 6). Lead time хранится в исходных единицах: 6 недель, а не 1,5 месяца.")
with tabs[2]:
    st.dataframe(pd.DataFrame([{"Режим": s.name, "Ёмкость, т": s.capacity, "Потери от оборота": s.loss_rate, "Хранение, млн/т-год": s.holding_cost,
                                "CAPEX, млн": s.capex, "OPEX, млн/год": s.opex, "Доступен с": s.available_from_year} for s in c.storages.values()]), hide_index=True)
    st.dataframe(pd.DataFrame([{"Опция": i.name, "Право, млн": i.option_fee, "Реализация, млн": i.exercise_cost, "Итого CAPEX, млн": i.total_capex,
                                "OPEX, млн/год": i.opex, "Правило ввода": i.commissioning_rule} for i in c.investments.values()]), hide_index=True)
    st.caption("Earth-New: 90 + 270 = 360, третьего платежа нет. Коэффициент ZBO 1,2 % — учебный коэффициент кейса, не характеристика реальной технологии.")
with tabs[3]:
    st.dataframe(pd.DataFrame([{"Правило": k.constraint_id, "Метрика": k.metric, "Знак": k.operator, "Порог": k.value, "Ед.": k.unit,
                                "Период": k.period, "Сценарий": k.scenario, "Тяжесть": k.severity, "Описание": k.description} for k in c.constraints]), hide_index=True)
with tabs[4]:
    scen = all_scenarios(c)
    for sid, s in scen.items():
        with st.expander(f"{scenario_label(sid)} · статус {s.status}", icon=":material/tune:"):
            eff = effective(c, s)
            st.dataframe(pd.DataFrame([{"Год": y, "Спрос, т": eff.demand_total[y], "Крит. спрос, т": eff.demand_critical[y],
                                        **{f"Цена {c.sources[k].name}": eff.price[k][y] for k in c.sources},
                                        **{f"Доля поставки {c.sources[k].name}": eff.delivery_share[k][y] for k in c.sources if any(abs(eff.delivery_share[k][yy] - 1) > 1e-12 for yy in eff.years)}}
                                       for y in eff.years]), hide_index=True)
            if eff.changes:
                st.caption("Изменения относительно BASE: " + "; ".join(eff.changes))
            if eff.loss_ceiling_enabled:
                st.caption(f"Потолок потерь {eff.loss_ceiling_max:g} от оборота с {eff.loss_ceiling_from_year}.")
with tabs[5]:
    st.dataframe(pd.DataFrame(assumption_rows()), hide_index=True)
    st.caption("Каждое допущение имеет имя, значение, единицу, основание и область действия (CASE_RULES §3). Файл configs/assumptions.yaml.")
    with st.container(border=True):
        st.markdown("**Ставка дисконтирования для исследования**")
        cur = assumptions()["discount_rate"]
        rate = st.slider("Реальная ставка, %", 0.0, 12.0, float(100 * cur), 0.5, key="rate_slider")
        if abs(rate / 100 - cur) > 1e-12:
            st.session_state.discount_rate_override = rate / 100
            st.rerun()
        st.caption("Изменение ставки помечается как TEAM_ASSUMPTION и применяется одинаково ко всем альтернативам. Контрольное значение 7 %.")
        if st.session_state.get("discount_rate_override") is not None and st.button("Вернуть контрольную ставку"):
            st.session_state.discount_rate_override = None
            st.rerun()
