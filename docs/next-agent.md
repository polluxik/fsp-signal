# Продолжение работы для Codex

Читайте [полную спецификацию](PRODUCT_SPEC.md), [допущения](assumptions.md) и [фактическое покрытие требований](implementation-status.md). В `README.md` есть запуск и демо-учётные записи. Сохраняйте существующий код: сквозной сценарий уже реализован, не начинайте проект заново.

Перед любыми продуктовыми решениями сначала сверяйтесь с [живым исследовательским источником](research/PRODUCT_RESEARCH.md): там сохранены конкурентный/пользовательский ресерч, хакатонные аналоги, бизнес-риски и прямые источники. Новые выводы дописывайте с датой, доказательностью и ограничениями; не затирайте историю.

Следующая продуктовая итерация спроектирована в ветке `codex/signal-product-v2`: [дизайн/архитектура](superpowers/specs/2026-10-05-signal-v2-design.md) и [план задач](superpowers/plans/2026-10-05-signal-v2.md). Исходное ТЗ остаётся в PRODUCT_SPEC; продуктовые решения сверять с ресерчем и release gates. T1–T3 реализованы; следующий шаг — T4: evidence и подробный narrative достижений без удлинения первичного ввода.

При проверке основной ветки подтверждено: `main`/`origin/main` — предок этой ветки (`b49c989 Restore employer search history across sessions`, впереди нет отдельных коммитов). Сохранённые employer search snapshots, список истории и возврат к результатам остались в текущем `backend/main.py` и `frontend/src/App.tsx`; сохранять эту возможность при следующих frontend/backend правках.

## Текущая точка

- Backend: FastAPI, SQLAlchemy, Alembic; frontend: React/TypeScript/Vite. Миграции `2ef663c4542b`, `41dbe7c98854`, `c6b21e90a441`, `89ea0f2d6c3b` применяются на SQLite и PostgreSQL.
- `./.venv/bin/pytest -q`: **23 passed**, один сторонний Starlette/httpx deprecation warning. `npm run build`, `docker compose config --quiet`, `git diff --check` проходят.
- Alembic до TestClient поднимает собственную временную SQLite; `TEST_DATABASE_URL` явно выбирает базу, а PostgreSQL разрешён только с именем БД, оканчивающимся на `_test`. Runtime `create_all` убран из API/worker/seed.
- T2 backend добавил immutable role versions, проверяемые условия/attestation, version CAS, draft/active/paused/closed, freshness 14 дней, старые migration snapshots только из известных данных, owner/CSRF-protected API и deduplicated allowlisted domain events.
- T3 backend добавил hard/soft preferences с CAS и legacy projection, salary floor private, explicit age attestation, compatibility report только кандидату, incompatible acceptance guard, блокировку/отзыв всех grants пары; банк и старые snapshot response скрывают заблокированную пару. UI preferences/access/compatibility ещё не подключён; существующий employer search-history экран сохранён.
- Приватный минимум намеренно не валидирует employer response при отправке: иначе success/409 даёт прямой oracle для серии зарплатных запросов. Кандидат видит report; несовместимое принять нельзя, а работодателю причина и данные preferences не возвращаются.
- Локально доступны `http://127.0.0.1:5173`, API `http://127.0.0.1:8000`, OpenAPI `/api/openapi.json` при активных процессах. Локальные процессы могут завершиться при смене среды.
- Изолированные Compose-проекты `signal-v2-check-latest` и `signal-v2-final-20261006` проверили PostgreSQL/Alembic/API readiness и повторяемый synthetic seed; volumes сохранены. Старый `signal-v2-check` держит Mailpit на `127.0.0.1:8025`, поэтому новые smoke-проекты не запускали с Mailpit; никакие volumes не удалять (`down -v`). SMTP end-to-end не отправлялся.
- UI путь двух ролей пройден с синтетическими данными. Импорт PDF проверен API-тестом, но ещё не проверен вручную в браузере. PDF-паспорт визуально проверен на Windows с демо-профилем; рендер в Linux-контейнере остаётся проверить.

## Следующие задачи по приоритету

1. Реализовать T4: доказательства из assessment и подробный editable achievement narrative. Короткий старт должен быстро собирать подробный рассказ о вкладе кандидата, не теряя контекст/источник/уровень проверки.
2. Затем T5/T6 matching и pinned consent; T7/T8 подключают role editor, preferences/access и candidate discovery к UI, сохраняя employer search-history flow.
3. Отдельными релизными проверками остаются PDF в Linux и в браузере, SMTP end-to-end, гонки/сроки приглашений и сценарии защищённого/сканированного/большого PDF.
4. До заявления качества ранжирования провести независимую разметку хотя бы 20–30 пар «потребность–кандидат» и посчитать Precision@5 / nDCG@5 против baseline. Synthetic fixture не выдавать за реальную релевантность.
5. Провести пилот с людьми; измерить время, долю завершения и сопоставимость вариантов. После этого расширять банк заданий.
6. Подготовить публичный стенд, короткое видео, презентацию и документы в PDF/DOC для финальной сдачи.

## Трёхчленная команда

| Человек | Главная зона до закрытия P0 |
|---|---|
| 1 | Backend, миграции, права, SMTP и развертывание |
| 2 | Тесты навыков, рубрика, человеческий пилот и замеры |
| 3 | UI, демо-сценарий, PDF, презентация и упаковка |

Каждый день интегрировать общий сквозной сценарий. Реальные контакты и персональные данные использовать только после согласия; для демонстрации хватает seed.
