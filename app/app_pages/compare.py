import json

import altair as alt
import pandas as pd
import streamlit as st

from common import CONFIG_DIR, assumptions, case, case_dir, fmt_mln, fmt_pct, fmt_t, scenario_label, scenario_options, try_run
from kosmo.api import all_scenarios
from kosmo.compare import price_of_protection, summarize
from kosmo.engine import run
from kosmo.plan import Plan

c = case()

st.subheader("Текущий план во всех сценариях", icon=":material/compare_arrows:")
st.caption("Один и тот же план, одна база данных, одна ставка. Так видно, что именно меняет сценарий: спрос, цены, фактические поставки, потолок потерь.")
rows = []
for sid in scenario_options():
    r = try_run(sid, with_geo=False)
    if r is None:
        continue
    s = summarize(r, c)
    rows.append({"Сценарий": scenario_label(sid), "Исполним": "да" if s["feasible"] else "нет", "Жёстких нарушений": s["hard_violations"],
                 "PV расходов, млн": s["discounted_expense_mln"], "Расходы, млн": s["total_expense_mln"],
                 "Дефицит, т": s["shortage_total_t"], "Дефицит крит., т": s["shortage_critical_t"], "SL общий min": s["SL_total_min"],
                 "SL крит. min": s["SL_critical_min"], "Стоимость тонны, млн/т": s["cost_per_served_t_mln"],
                 "Запас на конец, т": s["closing_inventory_t"], "Нарушения": s["violations"]})
st.dataframe(pd.DataFrame(rows), hide_index=True, column_config={
    "SL общий min": st.column_config.NumberColumn(format="percent"), "SL крит. min": st.column_config.NumberColumn(format="percent"),
    "PV расходов, млн": st.column_config.NumberColumn(format="%.1f"), "Расходы, млн": st.column_config.NumberColumn(format="%.1f"),
    "Стоимость тонны, млн/т": st.column_config.NumberColumn(format="%.3f")})


@st.cache_data(show_spinner="Считаю стратегии…", max_entries=8)
def strategies_table(case_dir_s: str, params_json: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    from kosmo.case import load_case
    cc = load_case(case_dir_s)
    scen = all_scenarios(cc)
    params = json.loads(params_json)
    rows = []
    for p in sorted((CONFIG_DIR / "plans").glob("*.json")):
        plan = Plan.load(p)
        for sid in ("BASE", "MANDATORY_STRESS"):
            r = run(cc, plan, scen[sid], params, keep_daily=False)
            s = summarize(r, cc)
            s["strategy"] = plan.meta.get("strategy") or p.stem.split("_stress")[0]
            rows.append(s)
    df = pd.DataFrame(rows)
    pop = pd.DataFrame(price_of_protection(rows))
    return df, pop


st.subheader("Стратегии S0–S3 на одной базе", icon=":material/account_tree:")
st.caption("Планы из configs/plans: S0 (Core + Flex + ZBO, Emergency как база в 2039–2040), S0min (то же без терминального резерва), S1 (Earth-New 18 или 24 мес), S2 (Lunar-ISRU), S3 (Earth-New + ISRU). Для каждой: план под BASE, план, подготовленный под стресс заранее, и реакция после наблюдения стресса 01.01.2038 (Flex +122 дня, Emergency +42 дня).")
df, pop = strategies_table(str(case_dir()), json.dumps(assumptions(), sort_keys=True))
show = df[["plan_id", "scenario_id", "feasible", "hard_violations", "discounted_expense_mln", "total_expense_mln", "shortage_total_t",
           "SL_total_min", "cost_per_served_t_mln", "cumulative_capex_mln", "capex_headroom_2037_mln", "closing_inventory_t", "unused_flex_t", "violations"]].rename(columns={
    "plan_id": "План", "scenario_id": "Сценарий", "feasible": "Исполним", "hard_violations": "Нарушений", "discounted_expense_mln": "PV, млн",
    "total_expense_mln": "Расходы, млн", "shortage_total_t": "Дефицит, т", "SL_total_min": "SL общий min", "cost_per_served_t_mln": "Тонна, млн/т",
    "cumulative_capex_mln": "CAPEX, млн", "capex_headroom_2037_mln": "Запас CAPEX-2037, млн", "closing_inventory_t": "Запас на конец, т",
    "unused_flex_t": "Свободный Flex, т", "violations": "Нарушения"})
st.dataframe(show, hide_index=True, column_config={"SL общий min": st.column_config.NumberColumn(format="percent"),
                                                   "PV, млн": st.column_config.NumberColumn(format="%.0f"), "Расходы, млн": st.column_config.NumberColumn(format="%.0f"),
                                                   "Тонна, млн/т": st.column_config.NumberColumn(format="%.2f")})

st.subheader("Цена защиты от стресса", icon=":material/shield:")
st.caption("PV плана под BASE; что происходит с этим же планом в стрессе без адаптации; PV плана, подготовленного под стресс заранее; PV реакции с лагами. Цена защиты = подготовленный стресс минус база. Цена запоздалой реакции = реакция минус подготовленный.")
if not pop.empty:
    pshow = pop.rename(columns={"strategy": "Стратегия", "base_pv_mln": "PV в BASE, млн", "base_feasible": "BASE исполним", "capex_mln": "CAPEX, млн",
                                "stress_fixed_shortage_t": "Дефицит без адаптации, т", "stress_fixed_SL_total_min": "SL min без адаптации",
                                "stress_prepared_pv_mln": "PV подготовленного стресса, млн", "stress_prepared_feasible": "Подготовленный исполним",
                                "stress_reactive_pv_mln": "PV реакции, млн", "stress_reactive_feasible": "Реакция исполнима",
                                "price_of_protection_pv_mln": "Цена защиты, млн", "cost_of_late_reaction_pv_mln": "Цена запоздалой реакции, млн"})
    st.dataframe(pshow, hide_index=True, column_config={"SL min без адаптации": st.column_config.NumberColumn(format="percent")})
    chart_df = pop.dropna(subset=["stress_prepared_pv_mln"])
    if not chart_df.empty:
        ch = alt.Chart(chart_df).mark_point(size=160, filled=True).encode(
            x=alt.X("base_pv_mln:Q", title="PV расходов в BASE, млн", scale=alt.Scale(zero=False)),
            y=alt.Y("stress_prepared_pv_mln:Q", title="PV подготовленного стресс-плана, млн", scale=alt.Scale(zero=False)),
            color=alt.Color("strategy:N", title="Стратегия"), tooltip=["strategy", alt.Tooltip("base_pv_mln", format=".0f"), alt.Tooltip("stress_prepared_pv_mln", format=".0f"), "capex_mln"])
        text = ch.mark_text(dy=-14).encode(text="strategy:N")
        st.altair_chart(ch + text)
        st.caption("Ближе к левому нижнему углу — дешевле и в базе, и в стрессе. CAPEX и риски ввода показаны в таблице и в реестре рисков.")

with st.expander("Правило выбора плана (зафиксировано до расчёта)", icon=":material/gavel:"):
    st.markdown("""
1. План исполним в BASE по всем жёстким ограничениям.
2. Существует подготовленный вариант того же набора контрактов, исполнимый в обязательном стрессе: дефицит критического спроса ноль, SL общий не ниже 0,97.
3. Среди оставшихся — минимум приведённых расходов в BASE при раскрытой цене защиты; при разнице менее 3 % предпочтение отдаётся плану с меньшей CAPEX-экспозицией и большей свободной мощностью гибких каналов.
4. Профили весов сторон не участвуют в выборе; они показывают чувствительность ранжирования (страница «Риски и стороны»).
""")
