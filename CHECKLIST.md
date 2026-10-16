## B2. Чеклист «готовность приложения к Kubernetes»

Каждый пункт — проверяемый. Разработчик может сам прогнать команду и убедиться.
Пункты, которые разработчик не может проверить сам (например, настройка Vector
DaemonSet, PVC), вынесены в зону DevOps и в чеклист не включены.

| # | Пункт | Как проверить | Антипаттерн |
|---|---|---|---|
| 1 | Все настройки читаются из переменных окружения, нет хардкода хостов и портов | `grep -rn "localhost\|127.0.0.1\|redis://\|db:5432" --include="*.py"` — пусто | `HOST: "db"` в settings.py |
| 2 | Обязательные переменные читаются через `os.environ[...]`, а не `get(..., "default")` | `grep -rn "os.environ.get.*PASSWORD\|SECRET_KEY" --include="*.py"` — пусто | `get("POSTGRES_PASSWORD", "postgres123")` |
| 3 | `DEBUG=0` в проде, `ALLOWED_HOSTS` задан явно без `*` | `curl -fsS http://<pod>/nonexistent` → 404 без traceback; `grep ALLOWED_HOSTS` | `DEBUG=True`, `ALLOWED_HOSTS=["*"]` |
| 4 | Версии зависимостей зафиксированы, есть lock-файл с хешами | `pip install --require-hashes -r requirements/lock.txt` в чистом venv | `Django` без версии, `pip freeze > requirements.txt` |
| 5 | Контейнер бежит от non-root, ФС read-only, лишних пакетов нет | `docker run --rm image id` → uid≠0; `which vim curl nc gcc` — пусто | `USER root`, `apt-get install vim curl gcc` в runtime |
| 6 | Логи пишутся в stdout/stderr, а не в файлы | `grep -rn "RotatingFileHandler\|FileHandler" --include="*.py"` — пусто; `kubectl logs <pod>` показывает логи | `RotatingFileHandler("/var/log/app/app.log")` |
| 7 | Формат логов структурированный (JSON) с `timestamp`, `level`, `logger`, `message`, `request_id` | `kubectl logs <pod> \| jq .` парсится | `print("some log")` |
| 8 | Есть `/healthz`, отвечает 200 без авторизации и не зависит от БД/Redis | `curl -fsS http://<pod>:8000/healthz` → 200 | healthcheck на эндпоинт с авторизацией или с запросом в БД |
| 9 | Приложение обрабатывает `SIGTERM`: доигрывает запросы, завершается < 30 сек | `kubectl delete pod <pod>` → в логах `graceful shutdown`; pod завершается < 30s | `CMD ["sh", "-c", "..."]` без `exec` |
| 10 | Приложение устойчиво к недоступности БД/Redis при старте: ретраит, логирует, не падает | запустить pod с недоступной БД → в логах `connection refused, retrying...`, pod не в `CrashLoopBackOff` | падение с `OperationalError` при первом запросе |
| 11 | `/live` и `/ready` — разные эндпоинты (или один с разной семантикой) | `curl /live` при недоступной БД → 200; `curl /ready` → 503 | один эндпоинт на всё; liveness проверяет БД |
| 12 | Приложение не пишет данные в локальную ФС pod'а (кроме `/tmp`) | `grep -rn "/var/\|/srv/\|/data/" --include="*.py"` — пусто | `/var/log/app`, `/data/artifacts` |
| 13 | Beat — 1 реплика (или распределённая блокировка); задачи идемпотентны | `kubectl get deploy celery-beat` → `replicas: 1`; двойной вызов задачи → нет дублей | `replicas: 3` для beat без блокировки |
| 14 | Секреты не в образе и не в git; передаются через Secret | `docker history <image>` — без `ENV PASSWORD=...`; `git log --all -- .env` — пусто | `ENV POSTGRES_PASSWORD=...`, `.env` в git |
| 15 | Приложение корректно работает при `replicas > 1` (нет гонок, нет локального состояния) | `kubectl scale deploy web --replicas=3`, прогнать нагрузку — ошибок нет | файловые блокировки, локальный кэш, `SESSION_ENGINE=file` |
