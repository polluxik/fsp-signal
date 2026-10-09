# Docker Desktop: сбой dockerInference на Windows

9 октября 2026: Docker Desktop снова запущен после переноса WSL-дисков на D:. Junction `AppData/Local/Docker/wsl` → `D:\CodexData\Docker\wsl` работает, Engine 29.4.3 отвечает. Контейнеры Compose `fsp-signal-smoke-20261007` и прежний том PostgreSQL сохранены; сайт поднят на `http://127.0.0.1:58080`.

При запуске обнаружен отдельный сбой старого migrate-контейнера: `Can't locate revision identified by 'c918e47a25bf'`. База уже находилась на этой версии, но в старом контейнере отсутствовал файл миграции рынка. Текущий файл скопирован в его `/app/backend/migrations/versions`, `alembic upgrade head` успешно завершился без изменения версии БД. Перезапущены существующие API/worker/web; свежий frontend dist установлен в `/srv` без Docker build. Данные не сбрасывались: три встречи и 352 записи рынка сохранились.

Readiness и совпадение раздаваемого index с новой сборкой подтверждены. Браузерная проверка каталога на 1440/1180/1024/768/390px, старого URL, CV/сравнения и встреч прошла; новая колода и помощник кандидата также проверены на текущем стенде, без записей решений/предпочтений или запросов к LLM. Ошибок JavaScript нет. Отчёты: `D:\CodexData\fsp-signal\work\fsp-ui-live-report.json` и `twin-live-report.json`. Изменения файлов внутри старых контейнеров сохраняются при start/restart, но при их пересоздании из старых образов исчезнут; будущая обычная сборка должна использовать актуальный Git.

Проверено 8 октября 2026 на этой машине: Desktop 4.74.0, после обхода Engine 29.4.3 отвечает. Свежий host log показал сбой до запуска контейнеров: `initializing Inference manager`, невозможность удалить `AppData/Local/Docker/run/dockerInference`, `The file cannot be accessed by the system`. После предыдущего factory reset и повторного запуска ошибка сохранилась.

Что помогло в текущем сеансе: дождаться полного завершения Desktop/backend, переименовать только папку `AppData/Local/Docker/run` в `run-backup-20261008-182325`, создать пустую `run`, запустить Desktop. У исходной папки был один служебный socket `dockerInference`. Через минуту `docker desktop status` сообщил running, `docker info` вернул версию Engine, отдельный PostgreSQL-контейнер запустился. Никаких `down -v`, удаления VHDX, unregister WSL или нового factory reset агент не выполнял.

## При повторении

1. Зафиксировать точную свежую ошибку в `AppData/Local/Docker/log/host/com.docker.backend.exe.log`. Не публиковать весь лог: там могут оказаться ссылки авторизации и идентификаторы.
2. Если это опять тот же runtime socket, закрыть Desktop и проверить отсутствие `Docker Desktop` / `com.docker.backend` процессов. Переименовывать папку при работающем Desktop нельзя.
3. Сохранить runtime-каталог под новым именем рядом, создать пустой `run`, запустить Desktop. Операция не гарантирует долгосрочного исправления; старую папку не удалять автоматически.
4. Если появился другой путь, исследовать его отдельно. Не переносить произвольные secrets-каталоги, не трогать пользовательские данные или Docker volumes.
5. Проверить именно `docker info` и запуск контейнера. Запущенный интерфейс Desktop сам по себе не подтверждает доступность Engine.

Сходная ошибка описана пользователями в [Docker issue #527](https://github.com/docker/desktop-feedback/issues/527) и [#625](https://github.com/docker/desktop-feedback/issues/625). Их объяснение о причинах в Windows/NTFS — гипотеза из issue, не установленный нами диагноз. В этом сеансе подтверждены ошибка runtime socket и успешный обход переименованием его папки. Последующая остановка/перезапуск Windows ещё не проверены.

В нашем проекте отсутствует зависимость от Docker Model Runner: внешний Qwen вызывается HTTP API. Падение inference-службы Desktop случается ещё до нашего Compose.
