# Проверка интеграции синтетического рынка · 8 октября 2026

Источник: ветка команды `codex/synthetic-market-seed`, data commit `4a927dc`; исходный fixed seed `20261008`. Приложение добавляет отдельный demo-only каталог, не расширяет verified assessment-категории. Контракт: [SYNTHETIC_MARKET_INTEGRATION.md](../SYNTHETIC_MARKET_INTEGRATION.md).

| Проверка | Результат |
| --- | --- |
| Повторная генерация в отдельную папку | Все 200 CV, 120 вакансий, taxonomy, quality report и CSV-записи совпали; различие CRLF/LF нормализовано |
| Полный pytest, SQLite | 203 passed, 13 ожидаемых PostgreSQL-only skipped |
| Полный pytest, пустая PostgreSQL 17.11 test-БД | 216 passed; включая одновременный импорт и прежние concurrency guards |
| Production TypeScript/Vite | Успешно, 43 модуля |
| Полный Playwright, Chrome | 29 passed: 26 основных + 3 live-Qwen, без retries |
| Авторизация/production gate | Гость 401, кандидат не читает CV/сравнение, production-каталог 404/импорт запрещён |
| Неполный/неправильный корпус | Восемь вариантов отклонены до записи; реальные контакты/оценённые навыки не импортируются |
| Фильтры/страницы/полный документ | Проверены по исходному корпусу; mobile 390px и reload пройдены |
| Сравнение | Exact family, canonical skills, условия; unknown не становится pass; без score и hiring side effects |
| Текущий Compose, миграция | `c918e47a25bf`, healthy API; Docker build не выполнялся |
| Текущий Compose, два импорта | 352, затем 0 новых записей; 200 CV / 120 вакансий / 32 семейства |
| Сохранность текущей БД | Числа и SHA-256 содержимого десяти прежних таблиц полностью совпали до/после |
| Текущий сайт через Caddy | HR вошёл, каталог/полное CV/сравнение/reload/mobile прошли; dist совпадает с локальной сборкой |
| OpenAPI | 92 операции; runtime равен checked-in export |

Сохранены 101 аккаунт, 96 CandidateProfile, 2 EmployerProfile, 10 HiringNeed, 10 RoleVersion, 0 AssessmentAttempt, 3 Invitation, 3 ContactGrant, 3 InterviewMeeting, 0 EmployerShortlistEntry. Добавлено только 352 SyntheticMarketRecord. Это локальные вымышленные данные, не рыночные метрики или результаты человеческой калибровки.

Первый полный прогон выявил driver rowcount=−1 в psycopg и отсутствие нового demo-setting в трёх старых seed-тестах. Использован RETURNING id, настройки тестового demo-seed уточнены; финальные полные прогоны прошли. Повторный запуск в уже заполненную test-БД выдавал EMAIL_ALREADY_USED: финальная PostgreSQL-проверка выполнена на новой пустой БД, её одноразовый контейнер остановлен после проверки. Пользовательский volume не затрагивался.

Первый focused browser run потерял доступ к локальным API/Vite (`Failed to fetch`, затем connection refused). Новый focused и финальный полный прогоны на свободных портах 58084/58085 прошли; причина первоначального завершения серверов не установлена. Изменений бизнес-логики или увеличения таймаутов ради маскировки этого сбоя нет.

Команды: `python -m pytest -q`; PostgreSQL — TEST_DATABASE_URL на пустую собственную `*_test`; `npm run build`; `npm run test:e2e` с FSP_SIGNAL_LIVE_AI=1 и серверным ключом только из игнорируемой .env. Текущий runtime обновлён копированием исходников/статики в существующие контейнеры; при будущем пересоздании понадобятся актуальные образы.
