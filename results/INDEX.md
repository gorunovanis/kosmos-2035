# results/

Каждая папка `<план>__<сценарий>/` — один прогон ядра: `yearly_balance.csv`, `source_schedule.csv`, `financial_breakdown.csv`,
`constraint_checks.csv` (все правила с PASS/FAIL), `violations.csv`, `inventory_trace.csv` (дневной след; в репозитории не хранится из-за
размера, генерируется командой ниже, а для выбранного плана лежит листом `inventory_trace` в `export.xlsx`),
`assumptions.csv`, `risk_register.csv` (для выбранного плана), `meta.json` (сценарий, план, единицы, допущения, даты ввода, хэш чисел, версия кода),
`plan.json` (план для повторного открытия), `export.xlsx` (те же листы).

Сводки: `comparison.csv/xlsx` (все планы × сценарии), `price_of_protection.csv/xlsx`, `stakeholders_*.csv`, `mcda_profiles.csv`,
`sensitivity_*.csv`, `reverse_stress_*.csv`, `extension_*` (Source-X и 2041 на копиях), `invalid_demo_*` (заведомо неисполнимый план).

Пересборка: `python tools/make_results.py`. Числа в интерфейсе, выгрузках и записке берутся отсюда.
