import json

import pandas as pd
import streamlit as st

from common import (CONFIG_DIR, cal, case, scenario_label, set_plan, status_line, try_run)
from kosmo.plan import Plan, PlanError, structural_errors
from kosmo.planner import build_plan, spec_from_plan
from kosmo.api import all_scenarios, load_assumptions

c = case()
years = c.years
plan = st.session_state.plan
dec = plan["decisions"]
sources = list(c.sources.values())
res = try_run()
if res is not None:
    status_line(res)

st.caption("Условия организатора не редактируются здесь. Всё на этой странице — решения команды (TEAM_DECISION). Расчёт обновляется после каждого изменения.")

# ------------------------------------------------------------------ reservations pivot
resv_sources = [s for s in sources if s.res_rate > 0 or s.top_share > 0]
resv = pd.DataFrame(0.0, index=[s.name for s in resv_sources], columns=[str(y) for y in years])
for r in dec.get("capacity_reservations", []):
    if r.get("start") or r.get("end") or int(r["year"]) not in years:
        continue
    name = c.sources[r["source_id"]].name if r["source_id"] in c.sources else r["source_id"]
    if name in resv.index:
        resv.loc[name, str(r["year"])] = float(r["reserved_t_per_year"])
resv.index.name = "Канал"

orders = pd.DataFrame(0.0, index=[s.name for s in sources], columns=[str(y) for y in years])
for o in dec.get("supply_orders", []):
    if o.get("year") is None or o.get("start") or int(o["year"]) not in years:
        continue
    name = c.sources[o["source_id"]].name if o["source_id"] in c.sources else o["source_id"]
    if name in orders.index:
        orders.loc[name, str(o["year"])] += float(o["volume_t"])
orders.index.name = "Канал"

name_to_id = {s.name: s.source_id for s in sources}

col1, col2 = st.columns(2)
with col1:
    with st.container(border=True):
        st.subheader("Резерв мощности, т/год", icon=":material/lock:")
        st.caption("Право на поставку. Платится тариф за т/год пропорционально доле года; take-or-pay считается от резерва периода. Мощности: " +
                   ", ".join(f"{s.name} {s.capacity:g}" for s in resv_sources))
        resv_new = st.data_editor(resv, key="resv_editor", column_config={str(y): st.column_config.NumberColumn(str(y), min_value=0.0, format="%.1f") for y in years})
with col2:
    with st.container(border=True):
        st.subheader("Отбор (заказ) по годам, т", icon=":material/local_shipping:")
        st.caption("Заказанный объём поставки года, распределяется равномерно по дням. Решение принимается за lead time до начала поставки (Core 12 мес, Flex 4 мес, Emergency 6 нед).")
        orders_new = st.data_editor(orders, key="orders_editor", column_config={str(y): st.column_config.NumberColumn(str(y), min_value=0.0, format="%.2f") for y in years})

# apply pivot edits to the plan
changed = False
if not resv_new.equals(resv):
    keep = [r for r in dec.get("capacity_reservations", []) if r.get("start") or r.get("end") or int(r["year"]) not in years]
    for name, row in resv_new.iterrows():
        for y in years:
            v = float(row[str(y)] or 0.0)
            if v > 0:
                keep.append({"source_id": name_to_id[name], "year": y, "reserved_t_per_year": v})
    dec["capacity_reservations"] = keep
    changed = True
if not orders_new.equals(orders):
    keep = [o for o in dec.get("supply_orders", []) if o.get("year") is None or o.get("start") or int(o["year"]) not in years]
    for name, row in orders_new.iterrows():
        for y in years:
            v = float(row[str(y)] or 0.0)
            if v > 0:
                keep.append({"source_id": name_to_id[name], "year": y, "volume_t": v, "role": "planned"})
    dec["supply_orders"] = keep
    changed = True
if changed:
    plan["meta"] = dict(plan.get("meta") or {}, edited=True)
    st.session_state.plan = plan
    st.rerun()

# ------------------------------------------------------------------ special orders (windows, preparatory, reactive)
with st.container(border=True):
    st.subheader("Особые заказы: подготовительный период, частичный год, реакция", icon=":material/event:")
    st.caption("Заказы с окном поставки. Подготовительный заказ 2034 формирует запас на 01.01.2035. Роль reactive — решение после наблюдения (дата решения обязательна).")
    special = [o for o in dec.get("supply_orders", []) if o.get("start") or o.get("end") or o.get("year") is None or int(o["year"]) not in years]
    sdf = pd.DataFrame([{"Канал": c.sources[o["source_id"]].name if o["source_id"] in c.sources else o["source_id"], "Начало": o.get("start", ""),
                         "Конец": o.get("end", ""), "Объём, т": float(o["volume_t"]), "Роль": o.get("role", "planned"),
                         "Дата решения": o.get("decided_on", "") or "", "Причина": o.get("cause", "") or ""} for o in special],
                       columns=["Канал", "Начало", "Конец", "Объём, т", "Роль", "Дата решения", "Причина"])
    with st.form("special_orders_form"):
        sdf_new = st.data_editor(sdf, num_rows="dynamic", key="special_editor", hide_index=True, column_config={
            "Канал": st.column_config.SelectboxColumn(options=[s.name for s in sources], required=True),
            "Роль": st.column_config.SelectboxColumn(options=["planned", "reactive", "preparatory", "insurance"], required=True),
            "Объём, т": st.column_config.NumberColumn(min_value=0.0, format="%.3f")})
        if st.form_submit_button("Применить особые заказы", icon=":material/check:"):
            keep = [o for o in dec.get("supply_orders", []) if o.get("year") is not None and not o.get("start") and int(o["year"]) in years]
            errs = []
            for _, r in sdf_new.iterrows():
                if not r["Канал"] or pd.isna(r["Объём, т"]):
                    continue
                entry = {"source_id": name_to_id.get(r["Канал"], r["Канал"]), "volume_t": float(r["Объём, т"]), "role": r["Роль"] or "planned"}
                for k, col in (("start", "Начало"), ("end", "Конец"), ("decided_on", "Дата решения")):
                    v = str(r[col]).strip() if not pd.isna(r[col]) else ""
                    if v:
                        try:
                            cal.parse_date(v)
                        except cal.DateError as exc:
                            errs.append(f"{r['Канал']}: {exc}")
                        entry[k] = v
                if str(r["Причина"]).strip() and not pd.isna(r["Причина"]):
                    entry["cause"] = str(r["Причина"]).strip()
                if "start" not in entry or "end" not in entry:
                    errs.append(f"{r['Канал']}: нужны даты начала и конца окна")
                keep.append(entry)
            if errs:
                st.error("Не применено: " + "; ".join(errs), icon=":material/error:")
            else:
                dec["supply_orders"] = keep
                st.session_state.plan = plan
                st.rerun()

# ------------------------------------------------------------------ investments
with st.container(border=True):
    st.subheader("Инвестиции и ввод мощностей", icon=":material/construction:")
    inv_by = {i["investment_id"]: i for i in dec.get("investments", [])}
    with st.form("investments_form"):
        cols = st.columns(3)
        with cols[0]:
            st.markdown("**Earth-New: опцион 90 + реализация 270 = 360**")
            en_on = st.checkbox("Покупаем опцион Earth-New", value="EARTH_NEW" in inv_by, key="en_on")
            en = inv_by.get("EARTH_NEW", {})
            en_fee = st.text_input("Дата покупки права (90 млн)", value=en.get("option_fee_date", "2035-01-15"), key="en_fee")
            en_ex = st.text_input("Дата реализации (270 млн)", value=en.get("exercise_date", "2035-07-01"), key="en_ex")
            en_lead = st.number_input("Срок подготовки, мес (18–24)", min_value=18.0, max_value=24.0, value=float(en.get("lead_months", 24)), step=1.0, key="en_lead")
            en_comm = st.text_input("Дата ввода (пусто = реализация + срок)", value=en.get("commissioning_date", "") or "", key="en_comm")
        with cols[1]:
            st.markdown("**ZBO-модернизация: 180 млн, +12 млн/год**")
            zbo_on = st.checkbox("Делаем ZBO", value="ZBO" in inv_by, key="zbo_on")
            zbo = inv_by.get("ZBO", {})
            zbo_date = st.text_input("Дата решения (не ранее 2036-01-01)", value=zbo.get("decision_date", "2036-01-01"), key="zbo_date")
            zbo_lead = st.number_input("Срок ввода ZBO, мес (допущение)", min_value=0.0, max_value=36.0, value=float(zbo.get("lead_months", 0)), step=1.0, key="zbo_lead")
        with cols[2]:
            st.markdown("**Lunar-ISRU: 1 250 млн до 2038, +70 млн/год**")
            isru_on = st.checkbox("Финансируем Lunar-ISRU", value="LUNAR_ISRU" in inv_by, key="isru_on")
            isru = inv_by.get("LUNAR_ISRU", {})
            isru_date = st.text_input("Дата финансирования (до 2037-12-31)", value=isru.get("financing_date", "2037-06-01"), key="isru_date")
        if st.form_submit_button("Применить инвестиции", icon=":material/check:"):
            new_inv = []
            errs = []
            for label, val in (("Earth-New право", en_fee if en_on else None), ("Earth-New реализация", en_ex if en_on else None),
                               ("Earth-New ввод", en_comm if (en_on and en_comm.strip()) else None), ("ZBO", zbo_date if zbo_on else None),
                               ("ISRU", isru_date if isru_on else None)):
                if val:
                    try:
                        cal.parse_date(val.strip())
                    except cal.DateError as exc:
                        errs.append(f"{label}: {exc}")
            if errs:
                st.error("Не применено: " + "; ".join(errs), icon=":material/error:")
            else:
                if en_on:
                    e = {"investment_id": "EARTH_NEW", "option_fee_date": en_fee.strip(), "exercise_date": en_ex.strip(), "lead_months": float(en_lead)}
                    if en_comm.strip():
                        e["commissioning_date"] = en_comm.strip()
                    new_inv.append(e)
                if zbo_on:
                    new_inv.append({"investment_id": "ZBO", "decision_date": zbo_date.strip(), "lead_months": float(zbo_lead)})
                if isru_on:
                    new_inv.append({"investment_id": "LUNAR_ISRU", "financing_date": isru_date.strip()})
                dec["investments"] = new_inv
                st.session_state.plan = plan
                st.rerun()
    if res is not None:
        m = res.meta
        st.caption(f"Даты ввода по текущему плану: ZBO {m.get('zbo_commissioning') or '—'}, Earth-New {m.get('earth_new_commissioning') or '—'}, Lunar-ISRU {m.get('isru_commissioning') or '—'}. "
                   f"CAPEX по датам: " + "; ".join(f"{e['date']} {e['label']} {e['amount_mln']:g}" for e in m.get("capex_events", [])))

# ------------------------------------------------------------------ policies and auto-fill
with st.container(border=True):
    st.subheader("Политика запаса и автозаполнение объёмов", icon=":material/tune:")
    pol = dec.get("inventory_policy") or {}
    epol = dec.get("emergency_policy") or {}
    cols = st.columns([1, 1, 2])
    with cols[0]:
        st.number_input("Резерв, дней спроса (условие кейса)", value=float(pol.get("reserve_days", 45)), disabled=True)
        st.caption("Физический запас на 1 января. Emergency за 6 недель не покрывает 45 дней, поэтому вариант с контрактом не используется.")
    with cols[1]:
        role = st.selectbox("Роль Emergency", ["insurance", "planned_base"], index=0 if epol.get("role", "insurance") == "insurance" else 1,
                            format_func=lambda x: "страховка (только резерв мощности)" if x == "insurance" else "плановая база (не более 2 лет подряд)")
        planned_years = st.multiselect("Годы плановой базы Emergency", years, default=[y for y in epol.get("planned_years", []) if y in years])
        if role != epol.get("role") or sorted(planned_years) != sorted(epol.get("planned_years", [])):
            dec["emergency_policy"] = {"role": role, "planned_years": sorted(planned_years)}
            st.session_state.plan = plan
    with cols[2]:
        st.markdown("**Заполнить отбор автоматически** по правилу: сначала оплачиваемые минимумы take-or-pay, затем самая дешёвая тонна; целевой запас на конец года = резерв следующего года (и больше, если мощностей следующего года не хватит).")
        target_scen = st.selectbox("Планировать под сценарий", ["BASE", "MANDATORY_STRESS"], format_func=scenario_label, key="autofill_scen")
        if st.button("Заполнить объёмы", icon=":material/auto_fix_high:"):
            params, _ = load_assumptions()
            try:
                spec = spec_from_plan(c, Plan.from_dict(plan), strategy_id=st.session_state.get("plan_name", "custom"))
                new_plan, rep = build_plan(c, all_scenarios(c)[target_scen], spec, f"{st.session_state.get('plan_name', 'plan')}_auto", params)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Автозаполнение не удалось: {exc}", icon=":material/error:")
            else:
                raw = new_plan.to_dict()
                raw["scenario_id"] = plan.get("scenario_id", "BASE")
                set_plan(raw, f"{st.session_state.get('plan_name', 'plan')}_auto")
                if rep.warnings:
                    st.warning("Планировщик: " + " | ".join(rep.warnings), icon=":material/warning:")
                st.rerun()

# ------------------------------------------------------------------ contract cards
with st.container(border=True):
    st.subheader("Карточки договоров", icon=":material/handshake:")
    st.caption("Контрагент, объём, сроки и lead time, резервирование, take-or-pay, оплата, ответственность, правила пересмотра. Условия из данных кейса; ответственность и пересмотр — решения команды.")
    try:
        contracts = json.loads((CONFIG_DIR / "contracts.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        contracts = {}
    for s in sources:
        with st.expander(f"{s.name} ({s.source_id})", icon=":material/description:"):
            yrs = sorted({int(r["year"]) for r in dec.get("capacity_reservations", []) if r["source_id"] == s.source_id})
            vol = {int(o["year"]): float(o["volume_t"]) for o in dec.get("supply_orders", []) if o["source_id"] == s.source_id and o.get("year") is not None}
            card = {
                "Контрагент": s.name + " · " + (s.notes or ""),
                "Мощность": f"{s.capacity:g} т/год",
                "Резерв по годам": ", ".join(f"{y}: {next((r['reserved_t_per_year'] for r in dec['capacity_reservations'] if r['source_id']==s.source_id and int(r['year'])==y), 0):g}" for y in yrs) or "нет",
                "Отбор по годам": ", ".join(f"{y}: {v:.1f} т" for y, v in sorted(vol.items())) or "нет",
                "Lead time": f"{s.lead_min:g}–{s.lead_max:g} {s.lead_unit}" if s.lead_min != s.lead_max else f"{s.lead_min:g} {s.lead_unit}",
                "Тариф резервирования": f"{s.res_rate:g} млн за т/год",
                "Take-or-pay": f"{100 * s.top_share:.0f} % от резерва периода",
                "Цена": f"{s.var_cost:g} млн/т (с доставкой в узел)",
                "Оплата": "цена × max(заказ, TOP × резерв периода); резерв пропорционально доле года",
                "Ответственность": contracts.get(s.source_id, {}).get("responsibility", "TEAM_DECISION: не задано"),
                "Правила пересмотра": contracts.get(s.source_id, {}).get("revision", "TEAM_DECISION: не задано"),
                "Надёжность (метаданные риска)": s.reliability_profile,
            }
            st.table(card, border="horizontal")
