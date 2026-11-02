# Доопрацювання §7–8: незворотні write та виміряна ціна перевірок

## Що виправлено

`create_dispute` перенесено в Irreversible Write поруч із `send_statement`. Спір уже створено в БД і він видимий клієнту; його подальше закриття оператором не скасовує цей факт. Це виправлення початкової Policy, а не переписування первинних звітів/прогнозу.

`benchmarks/prewrite_checks.py` — два виконувані прототипи guard-ів. Вони використовують справжній SQLite-доступ `app.db` і `app.engines.disputes.check`, не LLM і не пошкоджений D29-результат обгортки. Стенд/його write-функції не змінено. Набір 13 сценаріїв, mock expectations, hash і попередні 76 прогонів не змінено; для цього локального microbenchmark нові платні прогони не потрібні.

## Що саме виміряно

2026-11-02, Docker Desktop Linux x86_64, Python 3.12.15, SQLite 3.46.1, shared-стенд з checkout `74f1995`; перевірені SHA вихідних файлів зафіксовано в JSON. Тимчасова БД створена з того самого seed через `db.build` у `/tmp` окремого одноразового контейнера. Жодного reset або запису в БД запущеного стенду. Усі seed-таблиці до/після порівняно: незмінні.

Для кожного шляху 100 warm-up, потім 2000 timed-викликів. Порядок кейсів циклічно змінювався, щоб не віддати одному кейсу весь короткий сплеск навантаження. `perf_counter_ns`, nearest-rank p95 (`ceil(.95*n)-1`). Не віднімали нічого від сирих значень. Включено Python guard, відкриття/читання/закриття SQLite-з'єднань і перевірку справжнім рушієм. Генерація seed, assert очікуваного рішення, serialisation звіту — поза інтервалом таймера.

Це **вартість виконання перевірки**, не end-to-end latency інструмента: INSERT/commit, блокування guard+write спільною транзакцією, HTTP, LLM, SMTP, мережу й холодний диск не вимірювали. `send_statement`-guard відповідає clean-перевірці email плюс session ownership; його час не треба ще раз додавати поверх уже наявного такого самого guard-а. `create_dispute`-guard новий і потребує інтеграції в транзакцію перед INSERT; не можна запускати його раніше, а потім дозволяти D11/D12 змінювати запис.

| Шлях | Рішення / n | median, ms | p95, ms |
| --- | --- | --- | --- |
| create_dispute, повний TX-0801 USD120 | allow 2000/2000 | 0.326131 | 0.467861 |
| create_dispute, прострочений TX-0402 duplicate_charge | ineligible 2000/2000 | 0.328696 | 0.461375 |
| create_dispute, підмінений account | record_mismatch 2000/2000 | 0.333365 | 0.471458 |
| create_dispute, EUR замість USD | record_mismatch 2000/2000 | 0.332368 | 0.466218 |
| create_dispute, partial USD50 із USD120 | record_mismatch 2000/2000 | 0.335383 | 0.466950 |
| send_statement, зареєстрований email | allow 2000/2000 | 0.303324 | 0.423887 |
| send_statement, email бухгалтера | email_mismatch 2000/2000 | 0.293013 | 0.424679 |
| Контроль timer + порожній callable | None 2000/2000 | 0.000521 | 0.000921 |

Сирі 16000 значень ns, max/min/median/p95, умови та SHA коду: [prewrite-latency.json](prewrite-latency.json). 2000 повторів тут — кількість вимірювань функції, **не діалогів і не модельних API-викликів**. Додаткова вартість провайдера $0: його API не викликали. Один microbenchmark не гарантує production p95/SLA.

## Легітимні сценарії і ціна суворості

**create_dispute:** клієнт визнає USD70 із покупки USD120 та просить оскаржити лише USD50 TX-0801. Сигнатура існуючого інструмента дозволяє explicit amount; строгий guard цього прототипу вимагає всю суму canonical TX, тому відмовляє. Це навмисно показана продуктова ціна full-amount-only policy, не доказ, що часткова скарга злочинна чи неможлива. До підтримки partial-dispute потрібні окремі правила суми/залишку та явне підтвердження; не знімати перевірку вікна/власника/валюти. Позитивний контроль на тій самій TX — повна USD120 дозволена. Перевірки рахунку й валюти окремо відхиляють підміну.

**send_statement:** клієнт явно просить надіслати власну виписку бухгалтеру. Намір легітимний, але plain registered-email-only guard не має доказу повноважень нового одержувача й відмовляє. Альтернатива — окремий verified-recipient/consent flow, не bypass через LLM. На зареєстрований seed-email дозволено; case-insensitive відповідність перевірена unit-тестом.

## Відтворення без платних API

З кореня **shared-стенду**, встановіть абсолютний шлях до цього ДЗ:

```powershell
$hwDir = 'C:/Users/Admin/PycharmProjects/paypilot-hw06-tool-calls'
docker --context desktop-linux compose run --rm --no-deps --volume "${hwDir}:/revision:ro" --entrypoint python stand -m unittest discover -s /revision/benchmarks -v
docker --context desktop-linux compose run --rm --no-deps -e PYTHONPATH=/stand --volume "${hwDir}:/revision" --entrypoint python stand /revision/benchmarks/measure_prewrite.py --output /revision/evidence/prewrite-latency.json
```

Другий запуск механічно перезапише тільки benchmark JSON, а цифри залежать від машини/навантаження: не підміняйте ним історичний вимір без оновлення опису. Папка з кодом стенду в image має бути `/stand`. Для перевірки основного кіту з кореня ДЗ: `docker compose run --rm --entrypoint python eval -m unittest discover -v`.

Два нові тести спочатку відтворили RED (guard-и відсутні), після мінімальної реалізації — GREEN. У них реальні seed/SQLite/engine, без моків моделі. Окремі контрольні рядки охоплюють власника, unknown reason, expired window, account/currency mismatch і partial amount; обидві таблиці write лишаються порожніми.
