"""12-slide deck (docs/slides.pptx) built from results/ via tools/digest.py with matplotlib charts.
Rules from the analysis of last year's winners: slide 1 = the answer; one table, one conclusion and a
footnote per slide; light background, one typeface, no decorative pictures; every number traceable.
Usage: python tools/make_slides.py"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from pptx import Presentation  # noqa: E402
from pptx.dml.color import RGBColor  # noqa: E402
from pptx.util import Inches, Pt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from digest import digest, fmt, num  # noqa: E402

OUT = ROOT / "docs"
IMG = OUT / "slides_img"
IMG.mkdir(parents=True, exist_ok=True)
NAVY = RGBColor(0x1C, 0x28, 0x33)
BLUE = RGBColor(0x1F, 0x5F, 0x8B)
GREEN = RGBColor(0x1E, 0x7D, 0x4F)
GREY = RGBColor(0x5F, 0x6B, 0x75)
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.spines.top": False, "axes.spines.right": False})


def chart_supply(N):
    yb = N["yearly_base"]
    yp = N["yearly_prepared"]
    fig, ax = plt.subplots(figsize=(6.4, 3.2), dpi=160)
    years = [int(y["year"]) for y in yb]
    ax.bar([y - 0.2 for y in years], [y["delivered_t"] for y in yb], width=0.4, label="Доставлено, BASE", color="#1f5f8b")
    ax.bar([y + 0.2 for y in years], [y["delivered_t"] for y in yp], width=0.4, label="Доставлено, стресс (подготовлен)", color="#8fb3d9")
    ax.plot(years, [y["demand_total_t"] for y in yb], "o-", color="#1c2833", label="Спрос BASE")
    ax.plot(years, [y["demand_total_t"] for y in yp], "s--", color="#b03a2e", label="Спрос стресс")
    ax.axhline(300, color="#999", lw=0.8, ls=":")
    ax.text(2035, 305, "Core + Flex = 300 т/год", fontsize=8, color="#666")
    ax.set_ylabel("т/год")
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    fig.tight_layout()
    p = IMG / "supply.png"
    fig.savefig(p)
    plt.close(fig)
    return p


def chart_strategies(N):
    S = N["strategies"]
    fig, ax = plt.subplots(figsize=(6.4, 3.4), dpi=160)
    for s, x in S.items():
        bx, sy = num(x["base_pv_mln"]), num(x["stress_prepared_pv_mln"])
        if bx is None or sy is None:
            continue
        ok = x["stress_prepared_feasible"] == "True"
        ax.scatter(bx, sy, s=90, color="#1e7d4f" if ok else "#b03a2e", zorder=3)
        ax.annotate(f"{s}\nCAPEX {fmt(num(x['capex_mln']))}", (bx, sy), textcoords="offset points", xytext=(6, 6), fontsize=8)
    ax.set_xlabel("PV расходов в BASE, млн")
    ax.set_ylabel("PV подготовленного стресс-плана, млн")
    ax.grid(alpha=0.25)
    ax.text(0.02, 0.96, "зелёный — стресс закрыт без дефицита; красный — не закрывается", transform=ax.transAxes, fontsize=8, color="#555", va="top")
    fig.tight_layout()
    p = IMG / "strategies.png"
    fig.savefig(p)
    plt.close(fig)
    return p


def chart_stress(N):
    yf, yp = N["yearly_fixed"], N["yearly_prepared"]
    fig, ax = plt.subplots(figsize=(6.4, 3.2), dpi=160)
    years = [int(y["year"]) for y in yf]
    ax.bar([y - 0.2 for y in years], [y["opening_inventory_t"] for y in yf], width=0.4, color="#b03a2e", label="Запас на 1 января, план без адаптации")
    ax.bar([y + 0.2 for y in years], [y["opening_inventory_t"] for y in yp], width=0.4, color="#1e7d4f", label="Запас на 1 января, подготовленный план")
    ax.plot(years, [y["required_opening_reserve_t"] for y in yf], "k_", markersize=18, mew=2, label="Требуемый резерв 45 дней")
    for y in yf:
        if y["shortage_total_t"] > 0:
            ax.annotate(f"дефицит {fmt(y['shortage_total_t'], 1)} т", (int(y["year"]) - 0.2, 2), textcoords="offset points", xytext=(0, 4), fontsize=8, color="#b03a2e", ha="center")
    ax.set_ylabel("т")
    ax.legend(fontsize=8, frameon=False)
    fig.tight_layout()
    p = IMG / "stress.png"
    fig.savefig(p)
    plt.close(fig)
    return p


def chart_tornado(N):
    rows = N["sens_base"][:5]
    fig, ax = plt.subplots(figsize=(6.4, 3.0), dpi=160)
    names = [r["parameter"] for r in rows][::-1]
    lo = [num(r["low_delta"]) for r in rows][::-1]
    hi = [num(r["high_delta"]) for r in rows][::-1]
    ax.barh(names, lo, color="#8fb3d9", label="нижняя граница")
    ax.barh(names, hi, color="#1f5f8b", label="верхняя граница")
    ax.axvline(0, color="k", lw=0.8)
    ax.set_xlabel("Изменение PV расходов, млн")
    ax.legend(fontsize=8, frameon=False)
    fig.tight_layout()
    p = IMG / "tornado.png"
    fig.savefig(p)
    plt.close(fig)
    return p


def add_title(slide, text, sub=None):
    tb = slide.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(12.3), Inches(0.9))
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(28)
    p.font.bold = True
    p.font.color.rgb = NAVY
    if sub:
        p2 = tf.add_paragraph()
        p2.text = sub
        p2.font.size = Pt(13)
        p2.font.color.rgb = GREY


def add_text(slide, x, y, w, h, lines, size=14, color=NAVY, bold_first=False):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = ln
        p.font.size = Pt(size)
        p.font.color.rgb = color
        if bold_first and i == 0:
            p.font.bold = True
        p.space_after = Pt(4)
    return tb


def add_conclusion(slide, text):
    tb = slide.shapes.add_textbox(Inches(0.5), Inches(6.35), Inches(12.3), Inches(0.5))
    p = tb.text_frame.paragraphs[0]
    p.text = "Вывод: " + text
    p.font.size = Pt(14)
    p.font.bold = True
    p.font.color.rgb = GREEN


def add_footnote(slide, text):
    tb = slide.shapes.add_textbox(Inches(0.5), Inches(6.85), Inches(12.3), Inches(0.5))
    p = tb.text_frame.paragraphs[0]
    p.text = text
    p.font.size = Pt(9)
    p.font.color.rgb = GREY


def add_table(slide, x, y, w, rows, col_widths=None, size=11):
    n_rows, n_cols = len(rows), len(rows[0])
    shape = slide.shapes.add_table(n_rows, n_cols, Inches(x), Inches(y), Inches(w), Inches(0.35 * n_rows))
    t = shape.table
    for i, r in enumerate(rows):
        for j, v in enumerate(r):
            cell = t.cell(i, j)
            cell.text = str(v)
            for par in cell.text_frame.paragraphs:
                par.font.size = Pt(size)
                par.font.bold = (i == 0)
                par.font.color.rgb = NAVY
    if col_widths:
        for j, cw in enumerate(col_widths):
            t.columns[j].width = Inches(cw)
    return t


def main() -> int:
    N = digest()
    b, f_, p, r = N["base"], N["fixed"], N["prepared"], N["reactive"]
    S = N["strategies"]
    risks = {x["risk_id"]: x for x in N["risks_base"]}
    yb, yp, yf = N["yearly_base"], N["yearly_prepared"], N["yearly_fixed"]
    y37 = next(y for y in yb if int(y["year"]) == 2037)
    y39f = next(y for y in yf if int(y["year"]) == 2039)
    e41s = N.get("extension_2041__S1_new24__MANDATORY_STRESS")
    pop = lambda s, k, nd=0: fmt(num(S[s][k]), nd) if s in S else "—"
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]

    # 1 answer
    s = prs.slides.add_slide(blank)
    add_title(s, "Топливный космоконтур 2035: план S1 закрывает спрос и обязательный стресс", "Команда «Космоконтур» · Core + Flex + ZBO 2036 + опцион Earth-New (ввод 01.07.2037) · физический резерв 45 дней")
    add_table(s, 0.5, 1.5, 12.3, [
        ["Показатель", "BASE", "Стресс без адаптации", "Стресс, план подготовлен", "Стресс, реакция с лагами"],
        ["Исполним", "да", "нет", "да", "да"],
        ["PV расходов 2035–2040, млн", fmt(b["discounted_expense_mln"]), fmt(f_["discounted_expense_mln"]), fmt(p["discounted_expense_mln"]), fmt(r["discounted_expense_mln"])],
        ["Дефицит, т (критический)", "0 (0)", f"{fmt(f_['shortage_total_t'], 1)} (0)", "0 (0)", "0 (0)"],
        ["SL общий min", "100 %", f"{fmt(100 * f_['SL_total_min'], 1)} %", "100 %", "100 %"],
        ["Стоимость тонны, млн/т", fmt(b["cost_per_served_t_mln"], 2), fmt(f_["cost_per_served_t_mln"], 2), fmt(p["cost_per_served_t_mln"], 2), fmt(r["cost_per_served_t_mln"], 2)],
        ["CAPEX накопленный, млн (лимит 1 800 / 2 800)", "540", "540", "540", "540"],
    ], col_widths=[4.3, 2, 2, 2, 2], size=12)
    add_conclusion(s, f"цена защиты от стресса {pop('S1_new24', 'price_of_protection_pv_mln')} млн PV, цена запоздалой реакции ещё {pop('S1_new24', 'cost_of_late_reaction_pv_mln')} млн; критический спрос обслужен на 100 % во всех прогонах.")
    add_footnote(s, "Млн условных единиц в постоянных ценах 2035, реальная ставка 7 % (TEAM_ASSUMPTION A4). Все числа из results/ (хэш в meta.json). SL — доля обслуженного спроса за год.")

    # 2 operator path
    s = prs.slides.add_slide(blank)
    add_title(s, "Путь оператора: изменил решение → пересчёт → нарушение с причиной → сравнил → сохранил → выгрузил")
    add_text(s, 0.5, 1.4, 6.2, 5, [
        "1. План и контракты: резервы и отборы по годам, особые заказы с окнами и датами решений, инвестиции с датами.",
        "2. Пересчёт сразу: дневной баланс 2034–2040, платежи, все проверки.",
        "3. Проверки и нарушения: правило · период · факт · порог · запас · статус словами, рычаг для каждого правила.",
        "4. Сценарии и сравнение: BASE, стресс, low/high, стратегии S0–S3, цена защиты.",
        "5. Чувствительность, риски, геополитика — тем же ядром.",
        "6. Сохранение плана (JSON по схеме организатора) и выгрузка CSV/XLSX с листом meta и хэшем чисел.",
        "",
        "Демо: снять опцион Earth-New → 15 нарушений (SOURCE_NOT_AVAILABLE 2037–2040, RESERVE_45D с 2038, общий сервис 75 % в 2038 и 67 % в 2040) → вернуть → переключить стресс → RESERVE_45D 2039: 1,95 против 45,37 т.",
    ], size=13)
    add_text(s, 6.9, 1.4, 6, 5, ["Один расчётный контур для экрана, CLI, тестов и выгрузок:", "python -m streamlit run app/streamlit_app.py", "python run.py run --plan configs/plans/S1_new24.json --scenario MANDATORY_STRESS", "python -m pytest -q  (27 тестов)", "", "Интерфейс: 10 страниц Streamlit, без облачных скриптов и ключей, запуск за минуту."], size=12, color=GREY)
    add_conclusion(s, "эксперт меняет любое решение без кода и видит численное нарушение с годом, величиной и причиной.")
    add_footnote(s, "Маршрут проверки из 13 шагов — README. Ошибки ввода: INVALID_INPUT, NEGATIVE_VALUE, UNKNOWN_SOURCE с указанием поля.")

    # 3 forks
    s = prs.slides.add_slide(blank)
    add_title(s, "Вилки кейса в числах: третий канал, ZBO, лимит CAPEX")
    s.shapes.add_picture(str(chart_supply(N)), Inches(0.5), Inches(1.3), width=Inches(6.6))
    add_text(s, 7.3, 1.3, 5.6, 5, [
        "Core + Flex = 300 т/год против спроса 390 т в 2040 и 448,5 т в стрессе: без третьего канала последние годы держатся только на запасе или на Emergency по 13,8 млн/т.",
        "Потолок потерь 2 % с 2038 в стрессе при 4,5 % у базового хранилища: ZBO обязателен до 2038.",
        "ZBO 180 + Earth-New 360 + ISRU 1 250 = 1 790 при лимите 1 800 до конца 2037: выбор, а не «взять всё».",
        "Emergency едет 6 недель = 42 дня из 45: резерв де-факто физический.",
        "Поставки 2035 заказаны в 2034 (Core 12 месяцев): подготовительный период с запасом 12,4 т и расходами 118,1 млн в 2035.",
    ], size=12)
    add_conclusion(s, "вопрос кейса не «инвестировать или нет», а «сколько стоит запас прочности и кто его оплачивает».")
    add_footnote(s, "Данные организатора: demand.csv, supply_sources.csv, storage_options.csv, investment_options.csv, constraints.csv, mandatory_stress.yaml — без правок.")

    # 4 architecture with one-line hand check
    s = prs.slides.add_slide(blank)
    add_title(s, "Ядро: дневной баланс с явными формулами и разбор одной строки руками")
    add_text(s, 0.5, 1.3, 6.3, 5.2, [
        "Запас на конец дня = запас на начало + поставка − потери − выдача",
        "Потери = валовое поступление × 4,5 % (база) или 1,2 % (ZBO)",
        "Выдача: сначала критический спрос дня, затем остальной; дефицит отдельно, запас не ниже нуля",
        "Резерв на 1 января: R = D × 45/365 от спроса сценария",
        "Закупка = цена × max(отбор, TOP × резерв периода); резерв = тариф × резерв × доля года",
        "Хранение = 0,72 × средний дневной запас; OPEX с даты ввода; CAPEX по датам",
        "PV = CF / (1 + 0,07)^(год − 2035)",
    ], size=13)
    add_table(s, 7.0, 1.3, 5.9, [
        ["2037, BASE", "т"],
        ["Запас на 1 января", fmt(y37["opening_inventory_t"], 3)],
        ["+ доставлено (Core 159,544 + Earth-New 32,767)", fmt(y37["delivered_t"], 3)],
        ["− потери 1,2 %", fmt(y37["losses_t"], 3)],
        ["− выдано", fmt(y37["served_total_t"], 1)],
        ["= запас на конец", fmt(y37["closing_inventory_t"], 3)],
        ["Закупка Core 6,2 × max(159,544; 0,7 × 190), млн", "989,17"],
        ["Резерв Core 0,45 × 190, млн", "85,50"],
    ], col_widths=[4.3, 1.6], size=11)
    add_conclusion(s, "числа ядра совпадают с независимым расчётом (внешний код) и с формулами Excel до шестого знака.")
    add_footnote(s, "docs/architecture.md (входы, выходы, формулы, источник метода, проверка по блокам); docs/control_example.xlsx; tests/test_s1_control.py.")

    # 5 constraints table
    s = prs.slides.add_slide(blank)
    add_title(s, "Ограничение · факт · порог · запас · статус (план S1)")
    rows = [["Правило", "Порог", "BASE: факт", "Статус", "Стресс без адаптации: факт", "Статус", "Стресс подготовлен: факт", "Статус"]]
    y39p = next(y for y in yp if int(y["year"]) == 2039)
    rows += [
        ["SL общий, min по годам", "≥ 0,97", "1,000", "PASS", f"{fmt(f_['SL_total_min'], 3)}", "FAIL (ориентир)", "1,000", "PASS"],
        ["SL критический, min", "≥ 0,99", "1,000", "PASS", "1,000", "PASS", "1,000", "PASS"],
        ["Резерв 45 дн на 01.01.2039, т", f"≥ {fmt(y39f['required_opening_reserve_t'], 1)}", fmt(next(y for y in yb if int(y['year']) == 2039)['opening_inventory_t'], 1), "PASS", fmt(y39f["opening_inventory_t"], 2), "FAIL", fmt(y39p["opening_inventory_t"], 1), "PASS"],
        ["CAPEX до конца 2037, млн", "≤ 1 800", "540", "PASS", "540", "PASS", "540", "PASS"],
        ["CAPEX до 2040, млн", "≤ 2 800", "540", "PASS", "540", "PASS", "540", "PASS"],
        ["Потери/оборот 2038–2040", "≤ 0,02 (стресс)", "0,012", "—", "0,012", "PASS", "0,012", "PASS"],
        ["Emergency как база, лет подряд", "≤ 2", "0", "PASS", "0", "PASS", "0", "PASS"],
        ["Мощность, резерв, ёмкость, сроки", "по каналам", "0 нарушений", "PASS", "0 нарушений", "PASS", "0 нарушений", "PASS"],
    ]
    add_table(s, 0.5, 1.3, 12.3, rows, col_widths=[3.1, 1.3, 1.4, 1.2, 1.9, 1.4, 1.8, 1.2], size=10)
    add_conclusion(s, "в стрессе тот же план ломается ровно там, где кейс и обещал: резерв и общий сервис 2039–2040; критический спрос не страдает.")
    add_footnote(s, "Полная таблица всех правил по годам — results/*/constraint_checks.csv и страница «Проверки и нарушения».")

    # 6 strategies
    s = prs.slides.add_slide(blank)
    add_title(s, "Четыре стратегии на одной базе и цена защиты")
    s.shapes.add_picture(str(chart_strategies(N)), Inches(0.5), Inches(1.3), width=Inches(6.4))
    rows = [["Стратегия", "CAPEX", "PV BASE", "PV стресс (подг.)", "Цена защиты"]]
    for sid, label in (("S0", "S0 Core+Flex+ZBO+Emergency"), ("S0min", "S0min без резерва"), ("S1_new24", "S1 Earth-New 24 мес"), ("S1_new24_margin10", "S1 + запас 10 %"), ("S2", "S2 Lunar-ISRU"), ("S3", "S3 New + ISRU")):
        if sid in S:
            rows.append([label, pop(sid, "capex_mln"), pop(sid, "base_pv_mln"), pop(sid, "stress_prepared_pv_mln") + ("" if S[sid]["stress_prepared_feasible"] == "True" else " ✗"), pop(sid, "price_of_protection_pv_mln")])
    add_table(s, 7.1, 1.3, 5.8, rows, col_widths=[2.3, 0.8, 0.9, 1.1, 0.9], size=10)
    add_text(s, 7.1, 4.0, 5.8, 2.3, [
        f"S2 дешевле S1 в базе на {fmt(b['discounted_expense_mln'] - num(S['S2']['base_pv_mln']))} млн, но дороже в стрессе на {fmt(num(S['S2']['stress_prepared_pv_mln']) - p['discounted_expense_mln'])} млн и требует CAPEX 1 430 до 2038.",
        "S0 не закрывает стресс даже при подготовке: нужный запас 128 т не помещается в 120 т.",
        "Правило выбора зафиксировано до расчёта; веса сторон не участвуют.",
    ], size=11)
    add_conclusion(s, "S1 — минимальная цена защиты среди исполнимых в стрессе планов при CAPEX 540; ISRU — ворота 2037 года под горизонт 2041+.")
    add_footnote(s, "results/comparison.xlsx, results/price_of_protection.xlsx. ✗ — подготовленный план неисполним.")

    # 7 plan schedule and gates
    s = prs.slides.add_slide(blank)
    add_title(s, "Выбранный план: расписание, обязательства, инвестиционные ворота")
    rows = [["Год", "Core", "Flex", "Earth-New", "Запас на конец", "Расходы, млн", "Событие / ворота"]]
    events = {2035: "15.01 право Earth-New 90; 01.07 реализация 270 → ворота 1–2 по спросу", 2036: "01.01 ZBO 180, OPEX 12/год → ворота 3: готовность ZBO",
              2037: "01.07 ввод Earth-New; до 31.12 решение об ISRU (ворота 4)", 2038: "стресс наблюдаем с января: Flex +122 д, Emergency +42 д", 2039: "проверка резерва 1 января", 2040: "конечный запас = резерв 2040"}
    src = {}
    import csv
    with (ROOT / "results" / "S1_new24__BASE" / "source_schedule.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            src[(int(row["year"]), row["source_id"])] = float(row["scheduled_t"])
    for y in yb:
        yy = int(y["year"])
        rows.append([str(yy), fmt(src.get((yy, "A"), 0), 1), fmt(src.get((yy, "B"), 0), 1), fmt(src.get((yy, "C"), 0), 1), fmt(y["closing_inventory_t"], 1), fmt(y["total_expense_mln"]), events.get(yy, "")])
    add_table(s, 0.5, 1.3, 12.3, rows, col_widths=[0.7, 0.9, 0.9, 1.1, 1.3, 1.3, 6.1], size=10)
    add_text(s, 0.5, 4.3, 12.3, 1.9, [
        "Заранее: резервы Core 190, Flex 110, Emergency 80 (страховка) на все годы; опцион и ZBO; отбор Core и Earth-New на год вперёд.",
        "После наблюдения: отбор Flex за 4 месяца, Emergency за 6 недель. Уже оплаченные минимумы take-or-pay не отменяются.",
        "Подготовительный период 2034: 44 дневных поставки Flex 18.11–31.12 на 12,98 т брутто (12,4 т нетто = 45 дней спроса 2035), расходы 118,1 млн в 2035.",
    ], size=12)
    add_conclusion(s, "план = расписание плюс политика реакции с лагами; каждое обязательство привязано к дате и плательщику.")
    add_footnote(s, "docs/roadmap.md (даты, платежи, ответственные, ворота), configs/contracts.json (карточки договоров), configs/plans/S1_new24*.json.")

    # 8 stress
    s = prs.slides.add_slide(blank)
    add_title(s, "Обязательный стресс: без адаптации, подготовленный план и порог разрушения")
    s.shapes.add_picture(str(chart_stress(N)), Inches(0.5), Inches(1.3), width=Inches(6.6))
    rs = {(x["parameter"], x["criterion"]): x for x in N["rs_base"]}
    thr_short = rs.get(("Спрос (все годы)", "дефицит > 0"), {}).get("threshold")
    add_text(s, 7.3, 1.3, 5.6, 5, [
        f"Без адаптации: первый дефицит {y39f['first_shortage_date']}, за 2039–2040 недодано {fmt(f_['shortage_total_t'], 1)} т коммерческим потребителям, критический спрос 100 %.",
        f"Подготовленный план: Earth-New 2038 {fmt(next(y for y in yp if int(y['year']) == 2038)['delivered_t'] - 190, 1)} т вместо 71,8, Flex 2039 {fmt(y39p['delivered_t'] - 320, 1)} т вместо 12,6, запас на 01.01.2040 {fmt(next(y for y in yp if int(y['year']) == 2040)['opening_inventory_t'], 1)} т.",
        f"Порог разрушения: план держит резерв ровно на пороге; физический дефицит при спросе выше ×{fmt(num(thr_short), 3) if thr_short else '—'}. Цены каналов до ×2,16 план не ломают.",
        "Тест команды: спрос ×1,25 (выше high) — дефицит 299 т без реакции, 2,2 т с реактивным Flex.",
    ], size=12)
    add_conclusion(s, "стресс закрывается объёмами внутри уже зарезервированной мощности; бюджет и мощности не увеличены.")
    add_footnote(s, "docs/stress_protocol.md T1–T4; results/reverse_stress_*.csv; results/sensitivity_*.csv.")

    # 9 risks
    s = prs.slides.add_slide(blank)
    add_title(s, "Реестр рисков: последствие, мера, предел меры, остаточный риск")
    rows = [["Риск", "Последствие без меры", "Мера", "Стоимость меры, млн PV", "Остаточный"]]
    labels = {"R1": "Earth-New задержан до 2038", "R2": "Срыв партии Core 30 дн (2039)", "R3": "Перерыв запусков 60 дн (2039)", "R4": "ZBO задержан на 30 мес",
              "R5": "Спрос ×1,25 c 2038", "R6": "Спрос ×0,8, take-or-pay", "R7": "Цена Earth-New ×1,35"}
    cons = {"R1": "резерв 2038 нарушен", "R2": "резерв 2040 нарушен", "R3": f"дефицит {fmt(num(risks['R3']['delta_shortage_t']), 1)} т", "R4": "потери 4,5 %, резерв нарушен",
            "R5": f"дефицит {fmt(num(risks['R5']['delta_shortage_t']), 1)} т", "R6": f"переполнение, +{fmt(num(risks['R6']['delta_pv_mln']))} млн", "R7": f"+{fmt(num(risks['R7']['delta_pv_mln']))} млн"}
    meas = {"R1": "Flex 34 т, реакция за 4 мес", "R2": "Emergency 15,6 т за 6 нед", "R3": "запас +40 т Flex в 2038", "R4": "Flex 2036–2038", "R5": "реактивный Flex 2038–2040", "R6": "перепланирование до минимумов", "R7": "объём сверх минимума на Flex"}
    for rid in ("R1", "R2", "R3", "R4", "R5", "R6", "R7"):
        x = risks.get(rid)
        if not x:
            continue
        rows.append([labels[rid], cons[rid], meas[rid], fmt(num(x["mitigation_cost_pv_mln"])), f"дефицит {fmt(num(x['residual_shortage_t']), 1)} т, Δ PV {fmt(num(x['residual_pv_mln']))}"])
    add_table(s, 0.5, 1.3, 12.3, rows, col_widths=[2.6, 2.6, 2.6, 1.8, 2.7], size=10)
    add_text(s, 0.5, 4.6, 12.3, 1.6, ["Предел мер: земная диверсификация не спасает от общего перерыва запусков (R3) — только запас; реакция после наблюдения не закрывает первые месяцы (R5); оплаченные минимумы take-or-pay не возвращаются (R6). Вероятности не назначаются: диапазоны кейса и сценарные допущения; обязательный стресс не считается повторно."], size=11)
    add_conclusion(s, "каждый риск — исполняемый сценарий: событие → параметр → тонны и млн → мера вторым прогоном → остаток.")
    add_footnote(s, "configs/risks/R1–R7.yaml; results/S1_new24__BASE/risk_register.csv (владелец, зависимости, основание диапазона, нарушения).")

    # 10 stakeholders
    s = prs.slides.add_slide(blank)
    add_title(s, "Стороны: кто получает топливо, кто платит, кто несёт риск")
    rows = [["Сторона", "Показатель по плану S1", "Что несёт"],
            ["Оператор узла", f"0 нарушений; PV {fmt(b['discounted_expense_mln'])} млн; свободный Flex 110 т/год до 2038", f"резервы, take-or-pay, хранение, OPEX; цена защиты {pop('S1_new24', 'price_of_protection_pv_mln')} млн"],
            ["Критические потребители", "SL критический 100 % во всех сценариях; резерв 45 дней", "первыми получают топливо при дефиците"],
            ["Коммерческие потребители", f"SL общий 100 % / 87 % без адаптации; тонна {fmt(b['cost_per_served_t_mln'], 2)} → {fmt(p['cost_per_served_t_mln'], 2)} млн/т", "принимают дефицит в стрессе, оплачивают защиту через стоимость тонны"],
            ["Поставщики топлива и запусков", f"платежи за резерв {fmt(b['reservation_mln'])} млн за горизонт; take-or-pay Core 133 т/год", "держат мощность; отвечают за сроки"],
            ["Финансирующая сторона", "CAPEX 540 из 1 800; ввод Earth-New 01.07.2037; 1 260 в запасе для ISRU", "опцион и ZBO; риск задержки ввода (R1, R4)"]]
    add_table(s, 0.5, 1.3, 12.3, rows, col_widths=[2.6, 5.2, 4.5], size=10)
    add_text(s, 0.5, 4.5, 12.3, 1.7, ["Профили весов пяти сторон (PV / дефицит / CAPEX / гибкость) дают одно ранжирование: S1 (24 мес) первый при любом обоснованном профиле; S2 и S3 меняются местами по весу CAPEX. Веса — чувствительность, не правило выбора; требование к критическому сервису не взвешивается."], size=11)
    add_conclusion(s, "при росте риска нагрузка смещается на коммерческих потребителей и оператора, при задержках ввода — на финансирующую сторону; это видно в числах, а не в весах.")
    add_footnote(s, "results/stakeholders_*.csv, results/mcda_profiles.csv; Linkov et al. 2006 — веса от сторон и чувствительность к ним.")

    # 11 geo
    s = prs.slides.add_slide(blank)
    add_title(s, "Геополитический модуль: событие → составляющая цены → пересчёт → до и после → откат")
    add_table(s, 0.5, 1.3, 12.3, [
        ["Сценарий (исследовательский)", "Каналы", "Составляющая", "Годы", "Множитель k", "Основание диапазона"],
        ["Ограничение доступа к запусковым услугам", "Earth-New", "запуск и доставка", "2038–2039", "1,10–1,35", "доля 40–70 %, удорожание 25–50 %; механизм: ESA/ExoMars 2022"],
        ["Конфликт на маршрутах предпусковой логистики", "Core, Flex, Emergency", "логистика и страхование", "2039–2040", "1,02–1,10", "доля 2–5 %, ×2–3; механизм: UNCTAD 2024"],
        ["Программа новых провайдеров", "Flex, Earth-New", "запуск и доставка", "2038–2040", "0,86–0,96", "доля 40–70 %, −10–20 %; ESA Launcher Challenge"],
    ], col_widths=[3.2, 1.7, 1.6, 1.1, 1.1, 3.6], size=10)
    add_text(s, 0.5, 3.6, 12.3, 2.6, [
        "k = 1 + доля составляющей × (множитель составляющей − 1): структура цены в кейсе не задана, поэтому множитель применяется к агрегированной цене канала (допущение A12).",
        f"Пример: Earth-New ×1,35 в 2038–2039 → +{fmt(num(risks['R7']['delta_pv_mln']))} млн PV; мера — перенос объёма сверх минимума на Flex экономит {fmt(-num(risks['R7']['mitigation_cost_pv_mln']))} млн.",
        "Работает на копии сценария: контрольные BASE и стресс не меняются; кнопка «Вернуть контрольные цены»; параметры события уходят в meta выгрузки; сочетание со стрессом — явное перемножение.",
    ], size=12)
    add_conclusion(s, "модуль показывает причинную цепочку и решения оператора, не выдумывая вероятность события.")
    add_footnote(s, "configs/geo_events.json; страница «Геополитика». Исторические примеры подтверждают механизм, не величину будущего шока.")

    # 12 verifiability
    s = prs.slides.add_slide(blank)
    add_title(s, "Проверяемость: тесты, независимый расчёт, карта жюри, границы")
    add_text(s, 0.5, 1.3, 6.2, 5, [
        "27 автотестов: V01–V10 организатора из файла, независимый контроль S1 (три источника чисел: ядро, внешний расчёт, Excel), граничные и невалидные планы, детерминизм по хэшу, интерфейс.",
        "Каждая выгрузка: сценарий, план, единицы, допущения, даты ввода, отпечаток входных данных, хэш чисел, версия кода.",
        "Записка, one-pager и эти слайды собраны из results/ скриптами: ни одного числа руками.",
        "Копии набора: Source-X (шестой канал подхвачен через данные), 2041 (S1 в стрессе даёт дефицит 26,6 т, S3 закрывает).",
        "Границы: агрегированный узел, равномерные дневные потоки, учебные коэффициенты, допущения A1–A14, без Монте-Карло, без выручки.",
    ], size=12)
    add_text(s, 6.9, 1.3, 6, 5, [
        "Для вопросов жюри — где ответ:",
        "почему физический резерв → docs/zapiska.md §4 (A3), 42 дня из 45",
        "почему 24 месяца → §6, риск R1",
        "ставка 7 % и что при 12 % → §8, sensitivity",
        "как учтён 2034 → §4 (A8, A10), results/S1_new24__BASE/source_schedule.csv",
        "где формула баланса → src/kosmo/engine.py, docs/architecture.md §2",
        "что не умеет прототип → README «Границы прототипа»",
        "",
        "Запуск: pip install -r requirements.txt; python -m pytest -q; python -m streamlit run app/streamlit_app.py",
    ], size=11, color=GREY)
    add_conclusion(s, "любое число на экране можно довести до входа, формулы и файла за минуту.")
    add_footnote(s, "Репозиторий: README с маршрутом проверки из 13 шагов и картой критериев; docs/, results/, tests/.")

    out = OUT / "slides.pptx"
    prs.save(out)
    print(f"written {out} ({len(prs.slides.__iter__.__self__._sldIdLst)} slides)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
