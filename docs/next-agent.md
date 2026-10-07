# Продолжение работы для Codex

Читайте [полную спецификацию](PRODUCT_SPEC.md), [допущения](assumptions.md) и [фактическое покрытие требований](implementation-status.md). В `README.md` есть запуск и демо-учётные записи. Сохраняйте существующий код: сквозной сценарий уже реализован, не начинайте проект заново.

Перед любыми продуктовыми решениями сначала сверяйтесь с [живым исследовательским источником](research/PRODUCT_RESEARCH.md): там сохранены конкурентный/пользовательский ресерч, хакатонные аналоги, бизнес-риски и прямые источники. Новые выводы дописывайте с датой, доказательностью и ограничениями; не затирайте историю.

Signal v2 интегрирован в `main`: [дизайн/архитектура](superpowers/specs/2026-10-05-signal-v2-design.md) и [план задач](superpowers/plans/2026-10-05-signal-v2.md). Исходное ТЗ остаётся в PRODUCT_SPEC; продуктовые решения сверять с ресерчем и release gates. T1–T8 реализованы в ограниченном MVP. Независимый rubric review и человеческий A/B sample остаются release gate; не заявлять пользовательскую/экспертную калибровку без результатов.

Ветка `codex/signal-product-v2` была проверена и перенесена в `main` без конфликта: 73 backend-теста и сборка фронтенда прошли до интеграции. Сохранённые employer search snapshots, список истории и возврат к результатам остаются в `backend/main.py` и `frontend/src/App.tsx`; сохраняйте эту возможность при следующих правках.

## Текущая точка

- Backend: FastAPI, SQLAlchemy, Alembic; frontend: React/TypeScript/Vite. T4 migration `d4a7b2f019ce` adds candidate-owned JSON achievement stories; old profiles receive `{}`. SQLite и PostgreSQL migration chains пройдены.
- Проверка на Windows 7 октября: **81 passed на выделенной PostgreSQL**, **73 passed, 8 PostgreSQL-only skipped на временной SQLite**, **4 Playwright passed**, `npm run build`, `docker compose config --quiet`, `git diff --check`. Конкурентный тест обнаружил deadlock при accept против reject/withdraw/expire; переходы и worker expiry теперь блокируют `HiringNeed` до `Invitation`, а гонка worker/accept добавлена в тесты.
- Alembic до TestClient поднимает собственную временную SQLite; `TEST_DATABASE_URL` явно выбирает базу, а PostgreSQL разрешён только с именем БД, оканчивающимся на `_test`. Runtime `create_all` убран из API/worker/seed.
- T2 backend добавил immutable role versions, проверяемые условия/attestation, version CAS, draft/active/paused/closed, freshness 14 дней, старые migration snapshots только из известных данных, owner/CSRF-protected API и deduplicated allowlisted domain events.
- T3 backend добавил hard/soft preferences с CAS и legacy projection, salary floor private, explicit age attestation, compatibility report только кандидату, incompatible acceptance guard, блокировку/отзыв всех grants пары; банк и старые snapshot response скрывают заблокированную пару. Preferences/access UI подключён в T7; существующий employer search-history экран сохранён.
- T4 candidate form собирает историю через context/contribution/result (+ optional decision/basis), явно размечает командный результат, хранит рассказ приватно и требует отдельный share opt-in. Candidate `/evidence` DTO не содержит CV, ответы, ключи или failed attempts. Employer resolver проверяет роль, публикацию, согласие, block-list, owner и opt-in.
- T5/T6 добавляют `match_v2`, versioned search snapshots и закрепление role/preference версий, условий и выбранных evidence в invitation/accept flow. Тесты покрывают права, версии и конфликты; все 8 PostgreSQL-only race tests прошли на выделенной БД.
- T7/T8 подключают role editor, preferences/evidence/invitation UI и candidate role feed с пагинацией, save/hide/undo. Лента не отправляет отклик и не раскрывает контакты. Четыре браузерных сценария проверены на Windows.
- T4 blueprint 2026.2 меняет только backend:middle/event_idempotency на структурированное решение + minimal duplicate test + changed-payload mutation. Старые сохранённые 2026.1 варианты gradable; `verified_attempt_id` устанавливается только успешным submit в той же транзакции.
- Приватный минимум намеренно не валидирует employer response при отправке: иначе success/409 даёт прямой oracle для серии зарплатных запросов. Кандидат видит report; несовместимое принять нельзя, а работодателю причина и данные preferences не возвращаются.
- Локально доступны `http://127.0.0.1:5173`, API `http://127.0.0.1:8000`, OpenAPI `/api/openapi.json` при активных процессах. Локальные процессы могут завершиться при смене среды.
- Изолированный Compose-проект `fsp-signal-smoke-20261007` поднял PostgreSQL/Alembic/API/worker/web/Mailpit на Windows с `FSP_WEB_PORT=58080` (порт 8080 был зарезервирован системой). Регистрация доставила письмо в Mailpit, токен подтвердил email, вход сработал; seed создал 48 синтетических кандидатов. Внешний SMTP и публичный HTTPS ещё не проверены. Сервис оставлен запущенным для локального показа, его данные находятся в отдельном Docker volume.
- UI путь двух ролей пройден с синтетическими данными. Импорт PDF проверен API-тестом, но ещё не проверен вручную в браузере. PDF-паспорт визуально проверен на Windows; в Linux-контейнере сформирован одностраничный PDF с извлекаемой кириллицей. Браузерную загрузку ещё проверить.

## Следующие задачи по приоритету

1. Внешние release checks: человеческий rubric review/A-B, PDF и импорт в браузере, календарные границы, защищённые/сканированные/большие PDF, внешний SMTP. PostgreSQL, локальный Mailpit и PDF в Linux закрыты автоматической/сквозной проверкой.
2. До заявления качества ранжирования разметить хотя бы 20–30 пар «потребность–кандидат» и посчитать Precision@5 / nDCG@5 против baseline; synthetic fixture не выдавать за реальную релевантность.
3. Измерить пилотом время, долю завершения и сопоставимость вариантов. По результатам решить, нужны ли employer-visible interest/отклики или короткие повторные задания; не менять основной сценарий обратного найма без данных.
4. Собрать публичный стенд, презентацию, видео и документы PDF/DOC для финальной сдачи.

## Трёхчленная команда

| Человек | Главная зона до закрытия P0 |
|---|---|
| 1 | Backend, миграции, права, SMTP и развертывание |
| 2 | Тесты навыков, рубрика, человеческий пилот и замеры |
| 3 | UI, демо-сценарий, PDF, презентация и упаковка |

Каждый день интегрировать общий сквозной сценарий. Реальные контакты и персональные данные использовать только после согласия; для демонстрации хватает seed.
