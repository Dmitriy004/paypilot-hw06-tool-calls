# ДЗ_6 · Tool Call Assertion Suite

Окремий набір до L07: 13 сценаріїв, з них H01–H03 — три нові власні. Попередні прийняті ДЗ не змінено. Джерело завдання: [GoIT](https://www.edu.goit.global/uk/learn/53575439/54507480/54593585/homework).

## Відтворення

Потрібні Docker Desktop і [paypilot-stand-shared](https://github.com/sergeytkachenko/paypilot-stand-shared), перевірений commit `74f1995`. Ключ OpenRouter зберігайте **тільки** в локальному `.env` стенду. Не публікуйте його. Модель фактичних вимірів підтверджується usage/трейсами, а не назвою провайдера в конфігурації.

З кореня цього кіту:

```powershell
docker compose run --rm --entrypoint python eval build_mock.py
docker compose up -d --force-recreate llm-mock
```

З кореня стенду (замініть шлях абсолютним шляхом клону цього кіту):

```powershell
$env:L07_DIR = 'C:/path/to/paypilot-hw06-tool-calls'
docker compose -f docker-compose.yml -f "$env:L07_DIR/mock/stand.override.yml" up -d --force-recreate stand
```

Після готовності `/health`, знову в корені кіту, **послідовно**, бо раннер скидає спільну seed-базу:

```powershell
$env:L07_RUN_LABEL = 'daily'
docker compose run --rm eval --gate daily
$env:L07_RUN_LABEL = 'baseline'
docker compose run --rm eval --condition baseline
$env:L07_RUN_LABEL = 'release'
docker compose run --rm eval --gate release
docker compose run --rm --entrypoint python eval -m unittest discover -v
```

Для Docker з іншим активним context можна додати `--context desktop-linux`, як у нашому перевіреному запуску. Порт 1080 має бути вільний. Після зміни сценаріїв обов'язково повторити generator і restart mock. Не запускайте одночасно інші тести/чат цього стенду. `CLOCK_OVERRIDE=2026-09-15T10:00:00Z`; baseline явно встановлює `clean` і порожні defects.

Штатні `run_step.py` і `build_mock.py` не змінено. Entrypoint `capture_run.py` лише додає автоматичний JSON-звіт і збереження повної відповіді/трейсу/стану **до наступного reset**. Зберігаються тільки лічильники proxy, не заголовки з ключем. `reports/<label>.json` і `reports/<label>.evidence.jsonl` локальні; для нового запуску беріть новий label, бо evidence дописується. Відібрані власні первинні докази здачі розміщуються в `evidence/`. Штатний раннер показує assertion FAIL, але його exit code не є production CI-гейтом; перевіряйте verdict-и JSON. ERROR не вважається коректним виявленням дефекту.

Daily: S1/S3/S4/S6/H02 ×1; release: S2/S5/S7/S8/S9/S10/H01/H03 ×5. `tool_called` у daily — передумова досягнення операції, не перевірка якості вибору моделі. Вибір, параметри з історії, порядок, відмова і cache винесено в release. S3 — лише контракт; S10 — окремо поведінка без write. S7 і H03 — легітимні позитивні контроли.

## Походження й чесність вимірів

Лабораторний прогноз збережено незмінним у `evidence/lab-prediction.md`, первинні повні відповіді — `evidence/lab-evidence.md`. [Прогноз ДЗ](evidence/homework-prediction.md) закомічено окремо (`2ae14ca`) до запусків на фінальному hash. Він поінформований лабораторною, а не сліпий. Бюджет/час виправлень у Policy слід відрізняти від виміряних latency й cost.

Результат: [заповнена Policy](tool-call-testing-policy.md), [універсальна порожня форма](tool-call-testing-policy-template.md), [аудит вимог і вартості](evidence/verification.md), [дослівні відповіді та докази](evidence/homework-evidence.md). Baseline 13/13; daily baseline 5/5; release baseline 40/40. Виявлено всі шість дефектних умов (3 daily, 3 release). 203 платні виклики коштували $0.038970875, точно звірено з приростом OpenRouter usage. Для повторної офлайн-перевірки архіву: `python archive_evidence.py evidence/homework-runs` (лише стандартна бібліотека, жодних API-викликів).

Після перевірки зупиніть mock і поверніть стенд без override:

```powershell
# у кіті
docker compose stop llm-mock
# у стенді
docker compose up -d --force-recreate stand
```
