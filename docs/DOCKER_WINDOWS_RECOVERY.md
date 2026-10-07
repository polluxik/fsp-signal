# Сбой Docker Desktop на Windows · 7 октября 2026

## Что подтверждено локально

Ранее Compose запускался и проходил проверки. Теперь Docker Desktop падает до запуска Linux Engine на удалении служебного Unix socket:

```text
initializing Inference manager ... Docker/run/dockerInference
The file cannot be accessed by the system
The filename, directory name, or volume label syntax is incorrect
```

В журнале после обхода первого сокета появилась такая же ошибка для `docker-secrets-engine/engine.sock`. После выполненного пользователем Factory Reset снова появилась ошибка `dockerInference`. Это сбой запуска самого Desktop, до миграций/кода приложения. Точная причина повреждения сокетов не установлена; совпадающий симптом описан в [Docker issue #527](https://github.com/docker/desktop-feedback/issues/527) и [#625](https://github.com/docker/desktop-feedback/issues/625). Объяснение про AF_UNIX/NTFS в issue является сообщением автора, а не подтверждённым диагнозом этого компьютера.

## Что уже сделано

При закрытом Docker два каталога, содержащих только runtime-сокеты, переименованы и сохранены; создана пустая замена. Резервные копии на этом компьютере:

- `C:/Users/chelo/AppData/Local/Docker/run-backup-20261007-calendar`
- `C:/Users/chelo/AppData/Local/docker-secrets-engine-backup-20261007-calendar`

Агент не удалял Docker volumes, VHDX, WSL-дистрибутивы и не выполнял Factory Reset. Пользователь позднее сообщил, что самостоятельно сделал Factory Reset. Сохранность прежней PostgreSQL после него не подтверждена.

Обход каталогов не дал устойчивого запуска. Дальше не повторять reset/prune: они не доказаны как решение этого сбоя и могут удалить данные.

## Следующий шаг

1. Закрыть Docker Desktop, сохранить открытые документы и **перезагрузить Windows**. Агент сам компьютер не перезагружал.
2. Запустить Docker, проверить `docker info`. Успех — возвращается Server Version, а не ошибка отсутствующего pipe.
3. Если ошибка повторится, собрать локальные diagnostics через Troubleshoot по [официальной инструкции Docker](https://docs.docker.com/desktop/troubleshoot-and-support/troubleshoot/). Не публиковать диагностику/настройки без проверки секретов. Переустановка/смена версии требует отдельного решения; переустановка сама по себе не подтверждена как исправление.
4. После восстановления Engine из корня репозитория:

```powershell
docker compose -p fsp-signal-smoke-20261007 up --build -d
docker compose -p fsp-signal-smoke-20261007 exec api python -m backend.seed_demo
docker compose -p fsp-signal-smoke-20261007 ps
```

Демо-профили создаются идемпотентным seed. Это восстановление синтетических данных, не восстановление удалённых пользовательских записей. Провести отдельный полный PostgreSQL-прогон на выделенной БД `*_test`: новые SQLite-тесты не заменяют проверку конкурентной брони на PostgreSQL.

## Временный работающий стенд

На этом компьютере подняты Vite `127.0.0.1:58080` и API `127.0.0.1:58081` с отдельной SQLite в `new-chat/work/fsp-local-demo.sqlite3`. `/api/v1/health/ready` возвращает `ok`. Qwen загружает ключ из игнорируемой `.env`. Запуск обслуживают терминальные процессы текущего чата; после перезагрузки их нужно запустить снова.

Для переносимого запуска без Docker см. README. Без SMTP доступны демо-аккаунты и очередь уведомлений, но доставка писем/регистрация нового email требуют отдельного SMTP worker и сервера. Mailpit сейчас через Docker недоступен. Новая SQLite не содержит прежних сессий/данных PostgreSQL; потребуется повторный вход.
