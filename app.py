import streamlit as st
import pandas as pd
from math_core import FuelSpaceContour

# --- НАСТРОЙКИ СТРАНИЦЫ И CSS (SpaceX Style) ---
st.set_page_config(layout="wide", page_title="КОСМОКОНТУР 2035")

st.markdown("""
    <style>
    /* Строгий монохромный минимализм */
    .stApp {
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    }
    h1, h2, h3, h4, h5, h6 {
        text-transform: uppercase !important;
        letter-spacing: 2px !important;
        font-weight: 600 !important;
    }
    /* Стилизация метрик */
    div[data-testid="stMetricValue"] {
        font-size: 2.5rem !important;
        font-weight: 300 !important;
        letter-spacing: -1px;
    }
    div[data-testid="stMetricLabel"] {
        font-size: 0.85rem !important;
        font-weight: 500 !important;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        color: #888888 !important;
    }
    /* Стилизация вкладок */
    button[data-baseweb="tab"] p {
        text-transform: uppercase;
        letter-spacing: 1px;
        font-weight: 600;
    }
    /* Скрытие стандартных элементов Streamlit */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

def get_baseline_strategy(inv_decisions, end_year=2040):
    rows = []
    for year in range(2035, end_year + 1):
        core_order = 190 if year >= 2037 else (140 if year == 2036 else 100)
        flex_order = 10 if year == 2037 else (70 if year == 2038 else (110 if year >= 2039 else 0))
        isru_order = 120 if (inv_decisions['Lunar-ISRU'] and year >= 2038) else 0
        enew_order = 130 if (inv_decisions['Earth-New'] and year >= 2037) else 0
        
        if isru_order > 0: flex_order = max(0, flex_order - 120)
        if enew_order > 0: 
            core_order = max(0, core_order - 130)
            flex_order = max(0, flex_order - 50)
            
        rows.extend([
            {"Год": year, "Канал": "EARTH-CORE", "Заказ (т)": float(core_order), "Резерв (т)": 190.0},
            {"Год": year, "Канал": "EARTH-FLEX", "Заказ (т)": float(flex_order), "Резерв (т)": 110.0}
        ])
        if isru_order > 0: rows.append({"Год": year, "Канал": "LUNAR-ISRU", "Заказ (т)": float(isru_order), "Резерв (т)": 0.0})
        if enew_order > 0: rows.append({"Год": year, "Канал": "EARTH-NEW", "Заказ (т)": float(enew_order), "Резерв (т)": 130.0})
    return pd.DataFrame(rows)

# --- ЗАГОЛОВОК ---
st.title("ЦИФРОВОЙ ДВОЙНИК: КОСМОКОНТУР 2035")
st.caption("ПАНЕЛЬ УПРАВЛЕНИЯ ИНВЕСТИЦИЯМИ И ЛОГИСТИКОЙ")
st.divider()

if 'inv_decisions' not in st.session_state:
    st.session_state.inv_decisions = {'ZBO': False, 'Lunar-ISRU': False, 'Earth-New': False}
if 'baseline_df' not in st.session_state:
    st.session_state.baseline_df = get_baseline_strategy(st.session_state.inv_decisions)

# --- БОКОВАЯ ПАНЕЛЬ ---
with st.sidebar:
    st.header("СИСТЕМНЫЕ НАСТРОЙКИ")
    
    st.subheader("ИМПОРТ ДАННЫХ")
    uploaded_file = st.file_uploader("ЗАГРУЗИТЬ ПЛАН (CSV)", type=['csv'])
    if uploaded_file is not None:
        try:
            df_uploaded = pd.read_csv(uploaded_file)
            if {'Год', 'Канал', 'Заказ (т)', 'Резерв (т)'}.issubset(df_uploaded.columns):
                st.session_state.baseline_df = df_uploaded
                st.success("ПЛАН ЗАГРУЖЕН")
            else:
                st.error("ОШИБКА ФОРМАТА")
        except Exception as e:
            st.error(f"ОШИБКА ЧТЕНИЯ: {e}")
            
    st.divider()
    scenario = st.radio("ВНЕШНЯЯ СРЕДА", ["STANDARD", "STRESS"], index=0)
    scenario_val = "standard" if scenario == "STANDARD" else "stress"
    
    horizon = st.slider("ГОРИЗОНТ ПЛАНИРОВАНИЯ", 2040, 2045, 2040)

# --- ОСНОВНОЙ ИНТЕРФЕЙС (ВКЛАДКИ) ---
tab1, tab2, tab3 = st.tabs(["ПЛАН И БАЛАНС", "АНАЛИЗ ЧУВСТВИТЕЛЬНОСТИ", "ОЦЕНКА СТЕЙКХОЛДЕРОВ"])

with tab1:
    col1, col2 = st.columns([1.2, 2.5], gap="large")
    
    with col1:
        with st.container(border=True):
            st.subheader("КАПИТАЛЬНЫЕ ИНВЕСТИЦИИ")
            zbo = st.toggle("ZBO-МОДЕРНИЗАЦИЯ", value=st.session_state.inv_decisions['ZBO'])
            isru = st.toggle("LUNAR-ISRU", value=st.session_state.inv_decisions['Lunar-ISRU'])
            enew = st.toggle("EARTH-NEW", value=st.session_state.inv_decisions['Earth-New'])
            st.session_state.inv_decisions = {'ZBO': zbo, 'Lunar-ISRU': isru, 'Earth-New': enew}
        
        with st.container(border=True):
            st.subheader("ГЕОПОЛИТИЧЕСКИЕ ФАКТОРЫ")
            geo_active = st.checkbox("АКТИВИРОВАТЬ ШОК ЦЕН")
            geo_mult = st.slider("МНОЖИТЕЛЬ (EARTH-CORE)", 1.0, 2.5, 1.4, disabled=not geo_active)
            geo_settings = {'active': geo_active, 'channel': 'Earth-Core', 'start_year': 2037, 'price_multiplier': geo_mult}
        
        st.subheader("КОНТРАКТНАЯ БАЗА")
        if st.session_state.baseline_df['Год'].max() != horizon and uploaded_file is None:
            st.session_state.baseline_df = get_baseline_strategy(st.session_state.inv_decisions, horizon)
        
        edited_df = st.data_editor(
            st.session_state.baseline_df, 
            hide_index=True, 
            num_rows="dynamic",
            use_container_width=True
        )
        st.download_button("ЭКСПОРТ ПЛАНА (CSV)", data=edited_df.to_csv(index=False).encode('utf-8'), file_name="space_plan.csv", mime="text/csv", use_container_width=True)

    with col2:
        st.subheader("РЕЗУЛЬТАТЫ СИМУЛЯЦИИ")
        
        custom_strategy = {}
        for _, row in edited_df.iterrows():
            yr = int(row["Год"])
            if yr not in custom_strategy: custom_strategy[yr] = {}
            # Приводим названия каналов к формату ядра
            channel_name = str(row["Канал"]).title().replace("Isru", "ISRU")
            custom_strategy[yr][channel_name] = {'ordered': float(row["Заказ (т)"]), 'reserved': float(row["Резерв (т)"])}
        
        system = FuelSpaceContour(scenario=scenario_val)
        df_res, t_capex, capex_37, npv = system.run_simulation(custom_strategy, st.session_state.inv_decisions, geo_settings, horizon)
        
        met1, met2, met3 = st.columns(3)
        with met1:
            st.metric("CAPEX ДО 2037", f"{capex_37:,.0f}", delta="ПРЕВЫШЕНИЕ" if capex_37 > 1800 else "В НОРМЕ", delta_color="inverse")
        with met2:
            st.metric("TOTAL CAPEX", f"{t_capex:,.0f}", delta="ПРЕВЫШЕНИЕ" if t_capex > 2800 else "В НОРМЕ", delta_color="inverse")
        with met3:
            st.metric("NPV ЗАТРАТ", f"{npv:,.0f}")
            
        st.divider()
        
        # Строгая монохромная таблица без matplotlib
        styled_res = df_res.style\
            .format({
                "Затраты (млн)": "{:.2f}",
                "NPV нарастающим": "{:.2f}",
                "Остаток": "{:.1f}",
                "Норма (45дн)": "{:.1f}"
            })\
            .map(lambda x: "background-color: #2b0000; color: #ff4d4d;" if x is False else "color: #a0a0a0;", subset=['План валиден'])
            
        st.dataframe(styled_res, height=320, use_container_width=True)
        st.download_button("ЭКСПОРТ РЕЗУЛЬТАТОВ (CSV)", data=df_res.to_csv(index=False).encode('utf-8'), file_name="simulation_results.csv", mime="text/csv")

with tab2:
    st.subheader("АНАЛИЗ ЧУВСТВИТЕЛЬНОСТИ")
    st.caption("СИМУЛЯЦИЯ ПОГРЕШНОСТИ ПРОГНОЗА СПРОСА (±20%)")
    
    if st.button("ЗАПУСТИТЬ РАСЧЕТ", type="primary"):
        with st.spinner('ВЫЧИСЛЕНИЕ...'):
            sens_results = []
            for d_mult in [0.8, 0.9, 1.0, 1.1, 1.2]:
                s_res, _, _, _ = system.run_simulation(custom_strategy, st.session_state.inv_decisions, geo_settings, horizon, demand_mult=d_mult)
                is_valid = s_res['План валиден'].all()
                total_cost = s_res['Затраты (млн)'].sum()
                
                sens_results.append({
                    "СПРОС": f"{int(d_mult*100)}%", 
                    "TOTAL ЗАТРАТЫ": round(total_cost, 2), 
                    "СТАТУС": "НОРМА" if is_valid else "КРИТИЧЕСКИЙ ОТКАЗ"
                })
            
            st.dataframe(pd.DataFrame(sens_results).style.map(
                lambda x: "color: #ff4d4d; font-weight: bold;" if "ОТКАЗ" in x else "color: #ffffff;", subset=['СТАТУС']
            ), use_container_width=True)

with tab3:
    st.subheader("МНОГОКРИТЕРИАЛЬНАЯ ОЦЕНКА (MCDA)")
    st.caption("БАЛАНС СТОИМОСТИ (ИНВЕСТОР) И НАДЕЖНОСТИ (ОПЕРАТОР)")
    
    weight_cost = st.slider("ВЕС: СТОИМОСТЬ", 0.0, 1.0, 0.5, 0.05)
    weight_service = 1.0 - weight_cost
    st.caption(f"ВЕС: НАДЕЖНОСТЬ = {weight_service:.2f}")
    
    score_cost = max(0, 100 - (npv / 150)) 
    score_service = df_res['Крит. сервис (%)'].mean()
    final_score = (score_cost * weight_cost) + (score_service * weight_service)
    
    st.divider()
    st.metric("ИНДЕКС ЭФФЕКТИВНОСТИ", f"{final_score:.1f} / 100")
    st.progress(final_score / 100)