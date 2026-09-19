import pandas as pd
import streamlit as st

from common import RULE_HINTS, checks_df, status_line, try_run, violations_df

res = try_run()
if res is None:
    st.stop()
status_line(res)

viol = violations_df(res)
hard = viol[viol["severity"] == "hard"] if not viol.empty else viol
if hard.empty:
    st.success("Жёстких нарушений нет. План исполним в выбранном сценарии.", icon=":material/check_circle:")
else:
    st.error(f"Состояние «нет решения»: {len(hard)} жёстких нарушений. Система не меняет план сама: ниже причина, период, величина и рычаг для каждого правила.", icon=":material/error:")
    for _, v in hard.iterrows():
        try:
            a, l, e = float(v["actual"]), float(v["limit"]), float(v["excess"])
            nums = f"факт {a:,.3f}, порог {l:,.3f}, превышение {e:,.3f} {v['unit']}".replace(",", " ")
        except (TypeError, ValueError):
            nums = f"факт {v['actual']}, порог {v['limit']} {v['unit']}"
        with st.container(border=True):
            st.markdown(f"**{v['rule_id']}** · период {v['period']} · {nums}")
            st.caption(f"Причина: {v['cause']}")
            st.caption(f"Что можно сделать: {v['hint']}")
ref = viol[viol["severity"] == "reference"] if not viol.empty else viol
if not ref.empty:
    st.warning(f"В стрессе сервис ниже ориентира 97 % / 99 % в {len(ref)} случаях. Это ориентир устойчивости, а не жёсткое ограничение: дефицит показан численно, бюджет и мощности не увеличиваются.", icon=":material/warning:")

with st.container(border=True):
    st.subheader("Все проверки: ограничение, факт, порог, запас, статус", icon=":material/fact_check:")
    df = checks_df(res)
    if not df.empty:
        show = df[["rule_id", "period", "status_ru", "actual", "operator", "limit", "margin", "unit", "severity", "cause"]].rename(columns={
            "rule_id": "Правило", "period": "Период", "status_ru": "Статус", "actual": "Факт", "operator": "Знак", "limit": "Порог",
            "margin": "Запас до порога", "unit": "Ед.", "severity": "Тяжесть", "cause": "Смысл"})
        st.dataframe(show, hide_index=True, column_config={
            "Факт": st.column_config.NumberColumn(format="%.4f"), "Порог": st.column_config.NumberColumn(format="%.4f"),
            "Запас до порога": st.column_config.NumberColumn(format="%.4f")})
    st.caption("Статус написан словами, не только цветом. Тяжесть hard = план неисполним; reference = ориентир устойчивости в стрессе.")

with st.expander("Формулы проверок", icon=":material/function:"):
    st.markdown("""
- **Сервис**: SL_total = выдано / спрос, SL_critical = выдано критическим / критический спрос, ежегодно; в BASE минимумы 0,97 и 0,99 (constraints.csv), в стрессе те же уровни как ориентиры.
- **Резерв**: R_y = D_y × 45 / 365 от общего спроса текущего сценария; сравнивается с физическим запасом на 1 января до поступлений дня.
- **CAPEX**: накопленные платежи по датам ≤ 1 800 до конца 2037 и ≤ 2 800 до 2040.
- **Потери в стрессе**: годовые потери / валовое поступление ≤ 0,02 с 2038.
- **Emergency**: не более двух лет подряд как базовый канал (плановые поставки или доля выше порога из допущений).
- **Мощность и резерв**: дневной поток ≤ мощность/365; отбор года ≤ зарезервированная мощность периода; резерв ≤ мощность.
- **Хранилище**: запас плюс поступление дня ≤ ёмкость действующего режима; излишек показан как нарушение.
- **Сроки**: дата решения + lead time ≤ начало поставки; поставки только в окне доступности канала; ISRU финансируется до 2038, ZBO не ранее 2036.
""")
