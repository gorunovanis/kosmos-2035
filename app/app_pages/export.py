import json

import streamlit as st

from common import RESULTS_DIR, export_bundle_bytes, plan_files, save_to_results, set_plan, status_line, try_run
from kosmo.plan import Plan, PlanError

res = try_run()
plan = st.session_state.plan

col1, col2 = st.columns(2)
with col1:
    with st.container(border=True):
        st.subheader("Сохранить план", icon=":material/save:")
        st.caption("План хранится в JSON по схеме организатора (plan.schema.json): решения по резервам, отборам, инвестициям и политикам. Открывается снова через боковую панель или загрузку файла.")
        name = st.text_input("Имя плана", value=st.session_state.get("plan_name", "plan"), key="save_name")
        raw = dict(plan)
        raw["plan_id"] = name
        raw["scenario_id"] = st.session_state.scenario_id
        st.download_button("Скачать план (JSON)", data=json.dumps(raw, ensure_ascii=False, indent=2).encode("utf-8"),
                           file_name=f"{name}.json", mime="application/json", icon=":material/download:")
        if st.button("Сохранить в results/ вместе с выгрузкой", icon=":material/folder:"):
            if res is None:
                st.error("План не считается, сохранять нечего.", icon=":material/error:")
            else:
                st.session_state.plan = raw
                st.session_state.plan_name = name
                out = save_to_results(res, f"{name}_{st.session_state.scenario_id}")
                st.success(f"Сохранено: {out}", icon=":material/check_circle:")
with col2:
    with st.container(border=True):
        st.subheader("Открыть план", icon=":material/folder_open:")
        up = st.file_uploader("Файл плана JSON", type=["json"], key="plan_upload")
        if up is not None:
            try:
                data = json.loads(up.getvalue().decode("utf-8"))
                Plan.from_dict(data)   # structural validation with rule ids
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                st.error(f"INVALID_INPUT: файл не является корректным JSON ({exc})", icon=":material/error:")
            except PlanError as exc:
                st.error(f"План отклонён: {exc}", icon=":material/error:")
            else:
                if st.button("Открыть загруженный план", icon=":material/check:"):
                    set_plan(data, up.name.rsplit(".", 1)[0])
                    st.rerun()
        files = plan_files()
        st.caption("Сохранённые планы: " + ", ".join(files))

with st.container(border=True):
    st.subheader("Выгрузка результатов", icon=":material/table_view:")
    st.caption("Все файлы собираются из того же прогона, что и экран: баланс по годам, график по каналам, финансы, проверки, нарушения, дневной след, допущения, meta (сценарий, план, единицы, даты ввода, хэш чисел, версия кода), plan.json.")
    if res is None:
        st.stop()
    status_line(res)
    zip_bytes, xlsx_bytes, meta = export_bundle_bytes(res)
    with st.container(horizontal=True):
        st.download_button("Скачать XLSX (все листы)", data=xlsx_bytes, file_name=f"{res.plan_id}_{res.scenario_id}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", icon=":material/download:")
        st.download_button("Скачать CSV-набор (zip)", data=zip_bytes, file_name=f"{res.plan_id}_{res.scenario_id}_csv.zip",
                           mime="application/zip", icon=":material/download:")
    st.table({"Сценарий": meta["scenario_id"], "План": meta["plan_id"], "Исполним": "да" if meta["feasible"] else "нет",
              "Хэш чисел (SHA-256)": meta["canonical_hash"][:16] + "…", "Версия кода": meta["code_version"],
              "Отпечаток входных данных": meta["case_fingerprint"][:16] + "…",
              "Единицы": "т; млн у.е. в постоянных ценах 2035; т/год; 365-дневный год"}, border="horizontal")
    st.caption("Повторный запуск с теми же данными даёт тот же хэш: так проверяется воспроизводимость без сравнения файлов вручную.")
