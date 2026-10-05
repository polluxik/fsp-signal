# Продолжение работы для Codex

Читайте [полную спецификацию](PRODUCT_SPEC.md), [допущения](assumptions.md) и [фактическое покрытие требований](implementation-status.md). В `README.md` есть запуск и демо-учётные записи. Сохраняйте существующий код: сквозной сценарий уже реализован, не начинайте проект заново.

Перед любыми продуктовыми решениями сначала сверяйтесь с [живым исследовательским источником](research/PRODUCT_RESEARCH.md): там сохранены конкурентный/пользовательский ресерч, хакатонные аналоги, бизнес-риски и прямые источники. Новые выводы дописывайте с датой, доказательностью и ограничениями; не затирайте историю.

Следующая продуктовая итерация спроектирована в ветке `codex/signal-product-v2`: [дизайн/архитектура](superpowers/specs/2026-10-05-signal-v2-design.md) и [план задач](superpowers/plans/2026-10-05-signal-v2.md). Исходное ТЗ остаётся в PRODUCT_SPEC; продуктовые решения сверять с ресерчем и release gates. T1–T3 реализованы; T4 реализован как vertical slice. Независимый rubric review и человеческий A/B sample остаются release gate; не заявлять пользовательскую/экспертную калибровку без результатов.

При проверке основной ветки подтверждено: `main`/`origin/main` — предок этой ветки (`b49c989 Restore employer search history across sessions`, впереди нет отдельных коммитов). Сохранённые employer search snapshots, список истории и возврат к результатам остались в текущем `backend/main.py` и `frontend/src/App.tsx`; сохранять эту возможность при следующих frontend/backend правках.

## Текущая точка

- Backend: FastAPI, SQLAlchemy, Alembic; frontend: React/TypeScript/Vite. T4 migration `d4a7b2f019ce` adds candidate-owned JSON achievement stories; old profiles receive `{}`. SQLite migration chain is exercised by tests. T4 PostgreSQL migration smoke was not run: Docker daemon socket access was denied in the current environment.
- Fresh T4 verification: `./.venv/bin/pytest -q` — **33 passed**, one third-party Starlette/httpx deprecation warning; `npm --prefix frontend run build`, `docker compose config --quiet`, `git diff --check` pass. Docker config validation does not verify PostgreSQL startup.
- Alembic до TestClient поднимает собственную временную SQLite; `TEST_DATABASE_URL` явно выбирает базу, а PostgreSQL разрешён только с именем БД, оканчивающимся на `_test`. Runtime `create_all` убран из API/worker/seed.
- T2 backend добавил immutable role versions, проверяемые условия/attestation, version CAS, draft/active/paused/closed, freshness 14 дней, старые migration snapshots только из известных данных, owner/CSRF-protected API и deduplicated allowlisted domain events.
- T3 backend добавил hard/soft preferences с CAS и legacy projection, salary floor private, explicit age attestation, compatibility report только кандидату, incompatible acceptance guard, блокировку/отзыв всех grants пары; банк и старые snapshot response скрывают заблокированную пару. UI preferences/access/compatibility ещё не подключён; существующий employer search-history экран сохранён.
- T4 candidate form собирает одну историю через короткие context/contribution/result поля (+ optional decision/basis), явно размечает командный результат, хранит рассказ приватно и требует отдельный share opt-in. Candidate `/evidence` DTO не содержит CV, ответы, ключи или failed attempts. Employer resolver проверяет роль, публикацию, согласие, block-list, owner и opt-in; приглашение ещё не передаёт `evidence_ids` — это следующий pinned-invitation этап.
- T4 blueprint 2026.2 меняет только backend:middle/event_idempotency на структурированное решение + minimal duplicate test + changed-payload mutation. Старые сохранённые 2026.1 варианты gradable; `verified_attempt_id` устанавливается только успешным submit в той же транзакции.
- Приватный минимум намеренно не валидирует employer response при отправке: иначе success/409 даёт прямой oracle для серии зарплатных запросов. Кандидат видит report; несовместимое принять нельзя, а работодателю причина и данные preferences не возвращаются.
- Локально доступны `http://127.0.0.1:5173`, API `http://127.0.0.1:8000`, OpenAPI `/api/openapi.json` при активных процессах. Локальные процессы могут завершиться при смене среды.
- Изолированные Compose-проекты `signal-v2-check-latest` и `signal-v2-final-20261006` проверили PostgreSQL/Alembic/API readiness и повторяемый synthetic seed; volumes сохранены. Старый `signal-v2-check` держит Mailpit на `127.0.0.1:8025`, поэтому новые smoke-проекты не запускали с Mailpit; никакие volumes не удалять (`down -v`). SMTP end-to-end не отправлялся.
- UI путь двух ролей пройден с синтетическими данными. Импорт PDF проверен API-тестом, но ещё не проверен вручную в браузере. PDF-паспорт визуально проверен на Windows с демо-профилем; рендер в Linux-контейнере остаётся проверить.

## Следующие задачи по приоритету

1. T5: включить structured compatibility/matching, сохраняя hard constraints отдельно от ranker и search-history API/UI.
2. T6: закрепить role/preference версии и выбранные candidate-owned `evidence_ids` в invitation/accept flow; текущий resolver пока не подключён к invitation API.
3. После T5/T6 продолжать T7/T8 UI-интеграцию preferences/access и candidate discovery; не переписывать старую employer search history.
4. Внешние release checks: человеческий rubric review/A-B для T4, PostgreSQL smoke новой миграции (после восстановления Docker access), PDF в Linux/браузере, SMTP, гонки/сроки приглашений и защищённые/сканированные/большие PDF.
5. До заявления качества ранжирования разметить хотя бы 20–30 пар «потребность–кандидат» и посчитать Precision@5 / nDCG@5 против baseline; synthetic fixture не выдавать за реальную релевантность.
6. Измерить пилотом время, долю завершения, качество пересказа достижений и сопоставимость вариантов; только после этого расширять банк и подбирать P1-функции.

## Трёхчленная команда

| Человек | Главная зона до закрытия P0 |
|---|---|
| 1 | Backend, миграции, права, SMTP и развертывание |
| 2 | Тесты навыков, рубрика, человеческий пилот и замеры |
| 3 | UI, демо-сценарий, PDF, презентация и упаковка |

Каждый день интегрировать общий сквозной сценарий. Реальные контакты и персональные данные использовать только после согласия; для демонстрации хватает seed.
