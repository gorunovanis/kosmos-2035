import altair as alt
import pandas as pd
import streamlit as st

from common import (case, daily_df, fmt_mln, fmt_pct, fmt_t, status_line, supply_by_source_df, try_run, violations_df,
                    yearly_df, YEARLY_RU)

res = try_run()
if res is None:
    st.stop()
c = case()
status_line(res)
h = res.horizon

with st.container(horizontal=True):
    st.metric("Приведённые расходы 2035–2040", f"{fmt_mln(h['discounted_expense_mln'])} млн",
              help="PV при реальной ставке из допущений; без дисконта: " + fmt_mln(h["total_expense_mln"]) + " млн", border=True)
    st.metric("Стоимость тонны обслуженного спроса", f"{h['cost_per_served_t_mln']:.2f} млн/т" if h["cost_per_served_t_mln"] else "—", border=True)
    st.metric("Минимальный SL общий / критический", f"{fmt_pct(h['SL_total_min'])} / {fmt_pct(h['SL_critical_min'])}", border=True)
    st.metric("Дефицит за горизонт", f"{fmt_t(h['shortage_total_t'])} т",
              delta=None if h["shortage_total_t"] < 1e-9 else f"критический {fmt_t(h['shortage_critical_t'])} т", delta_color="inverse", border=True)
    st.metric("CAPEX накопленный", f"{fmt_mln(h['cumulative_capex_mln'])} млн", help="лимиты 1 800 до конца 2037 и 2 800 до 2040", border=True)

viol = violations_df(res)
if not viol.empty:
    hard = viol[viol["severity"] == "hard"]
    if not hard.empty:
        st.error(f"Нарушения: {len(hard)}. Первое: {hard.iloc[0]['rule_id']} в {hard.iloc[0]['period']}: факт {hard.iloc[0]['actual']:.3f} против {hard.iloc[0]['limit']:.3f} {hard.iloc[0]['unit']}. Подробности на странице «Проверки и нарушения».", icon=":material/error:")

ydf = yearly_df(res)
col1, col2 = st.columns(2)
with col1:
    with st.container(border=True):
        st.subheader("Поставки по каналам и спрос", icon=":material/stacked_bar_chart:")
        sup = supply_by_source_df(res, c)
        dem = pd.DataFrame({"Год": ydf["year"], "Спрос, т": ydf["demand_total_t"], "Выдано, т": ydf["served_total_t"]})
        bars = alt.Chart(sup).mark_bar().encode(x=alt.X("Год:O", title="Год"), y=alt.Y("sum(Доставлено, т):Q", title="т"),
                                                color=alt.Color("Канал:N", title="Канал"), tooltip=["Год", "Канал", alt.Tooltip("Доставлено, т", format=".1f")])
        line = alt.Chart(dem).mark_line(point=True, color="#1c2833").encode(x="Год:O", y=alt.Y("Спрос, т:Q"), tooltip=[alt.Tooltip("Спрос, т", format=".1f")])
        st.altair_chart(bars + line)
        st.caption("Столбцы: фактически доставлено по каналам. Линия: спрос сценария. Потери в тоннах показаны в таблице ниже.")
with col2:
    with st.container(border=True):
        st.subheader("Запас в узле и резерв 45 дней", icon=":material/water_drop:")
        d = daily_df(res)
        d = d[d["year"] >= res.years[0]]
        base = alt.Chart(d).mark_line().encode(x=alt.X("date:T", title="Дата"), y=alt.Y("closing_t:Q", title="т"), tooltip=[alt.Tooltip("date:T"), alt.Tooltip("closing_t", format=".1f", title="запас")])
        capline = alt.Chart(d).mark_line(strokeDash=[4, 4], color="#b03a2e").encode(x="date:T", y="storage_capacity_t:Q")
        res_pts = pd.DataFrame({"date": [f"{r['year']}-01-01" for r in res.yearly], "Резерв 45 дн, т": [r["required_opening_reserve_t"] for r in res.yearly],
                                "Запас на 1 янв, т": [r["opening_inventory_t"] for r in res.yearly]})
        pts = alt.Chart(res_pts).mark_point(size=80, color="#1f5f8b", filled=True).encode(x="date:T", y="Резерв 45 дн, т:Q", tooltip=["date:T", alt.Tooltip("Резерв 45 дн, т", format=".1f"), alt.Tooltip("Запас на 1 янв, т", format=".1f")])
        st.altair_chart(base + capline + pts)
        st.caption("Линия: физический запас по дням. Пунктир: ёмкость хранилища (70 т, 120 т после ZBO). Точки: требуемый резерв на 1 января.")

with st.container(border=True):
    st.subheader("Баланс по годам", icon=":material/table_chart:")
    show = ydf[["year", "demand_total_t", "demand_critical_t", "opening_inventory_t", "required_opening_reserve_t", "delivered_t", "losses_t",
                "served_total_t", "served_critical_t", "shortage_total_t", "shortage_critical_t", "closing_inventory_t", "SL_total", "SL_critical",
                "total_expense_mln", "discounted_expense_mln", "cost_per_served_t_mln", "cumulative_capex_mln"]].rename(columns=YEARLY_RU)
    st.dataframe(show, hide_index=True,
                 column_config={"SL общий": st.column_config.NumberColumn(format="percent"),
                                "SL критический": st.column_config.NumberColumn(format="percent"),
                                "Год": st.column_config.NumberColumn(format="%d")})
    st.caption("Единицы: тонны и млн условных единиц в постоянных ценах 2035. Баланс каждого дня: запас на конец = запас на начало + поставка − потери − выдача; дефицит показан отдельно и никогда не уходит в отрицательный запас.")

with st.container(border=True):
    st.subheader("Разложение расходов", icon=":material/payments:")
    cost = ydf[["year", "procurement_mln", "reservation_mln", "holding_mln", "opex_zbo_mln", "opex_isru_mln", "capex_mln", "preparation_cost_mln"]].rename(columns=YEARLY_RU)
    long = cost.melt(id_vars="Год", var_name="Статья", value_name="млн")
    ch = alt.Chart(long).mark_bar().encode(x=alt.X("Год:O"), y=alt.Y("млн:Q"), color=alt.Color("Статья:N"), tooltip=["Год", "Статья", alt.Tooltip("млн", format=".1f")])
    st.altair_chart(ch)
    st.caption("Закупка включает take-or-pay внутри max(заказ, доля × резерв периода); резервирование пропорционально доле года; хранение по среднему дневному запасу; OPEX с даты ввода; CAPEX по датам платежей.")
