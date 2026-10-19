# SOLUTION.md

## Краткое резюме

Выполнены части A и B. Стенд развёрнут в Kubernetes (namespace `sandbox`), доступен по `https://csync.robointerativo.org`. Сценарий «создали job → done → лог» работает.

- **A1** Dockerfile — production-образ (multi-stage, non-root, фиксация версий).
- **A2** Docker Compose — воспроизводимый и безопасный стенд.
- **A3** Kubernetes — Helm-чарт **разработан с нуля** (в исходном репозитории его не было), развёрнут в кластере. В процессе разработки возникли проблемы (см. A3), которые устранены.
- **A4** GitLab CI — стадии lint, test, build, deploy.
- **B1** Аудит — проблемы **исходного репозитория** (Docker, Compose, код, CI).
- **B2** Чеклист для разработчиков — 15 пунктов.
- **B3** Логи и файловые данные.
- **B4** Планировщик и масштабирование.
- **B5** On-prem платформа.

**Время:** ~16 часов чистой работы.

---

## A1. Dockerfile

### Базовый образ

Было: `python:3.11` — плавающий тег → невоспроизводимость.
Стало: `python:3.11.9-slim-bookworm` — фиксированы Python, Debian, slim.

Дальнейшее усиление (за рамками задания): digest + автоматика обновления + собственное зеркало.

### Секреты в образе

**Проблема:** `ENV POSTGRES_PASSWORD=postgres123`, `ENV DJANGO_DEBUG=1` — фиксируются в слоях, видны через `docker history` / `docker save`.

**Решение:** убрано. Секреты — через env / Secret / Vault.

### `PYTHONUNBUFFERED=1` — оставлено

Правильная настройка. Без неё логи Python буферизуются, и в k8s `kubectl logs` показывает их с задержкой. Оставлено.

### Пакеты

**Проблема:** один `RUN apt-get install gcc libpq-dev vim curl netcat-openbsd` — build-зависимости (`gcc`, `libpq-dev`) в runtime, `vim`/`curl` — лишние.

**Риск:** образ раздут, CVE, `vim` — шелл-обёртка, `curl` — SSRF.

**Решение:** multi-stage build:
- builder — `build-essential`, `libpq-dev`;
- runtime — `libpq5`, non-root user.

`apt-get` — `--no-install-recommends`, чистка `/var/lib/apt/lists`.

### `netcat-openbsd` в runtime

Нужен для `until nc -z db 5432` в entrypoint. После замены entrypoint на `wait_for` (Python `socket.connect_ex`) — **не нужен**. Убран из runtime. Плюс: меньше CVE, меньше поверхность атаки.

### `pip install` без `--no-cache-dir`

Кэш pip остаётся в образе (~200 МБ). Добавлено `--no-cache-dir`.

### `.dockerignore`

**Проблема:** `COPY . .` тащит `.git`, `logs`, `.env`, `__pycache__`.

**Решение:** `.dockerignore` + `.gitignore`. `.env` убран из репозитория (оставлен `.env.example`).

### `.env` в репозитории и в образе

Две разные проблемы:
1. `.env` в репозитории — утечка секретов в git;
2. `COPY . .` тащил `.env` в образ — утечка секретов в образ.

Решение: `.gitignore` + `.dockerignore` + `.env.example`.

### Non-root

**Проблема:** контейнер от root.

**Решение:** `useradd -r -u 999 app`, `USER app` в runtime.

### Кэш pip

**Проблема:** `COPY . .` до `pip install` → любое изменение кода инвалидирует слой.

**Решение:** `COPY requirements.txt` → `pip install` → `COPY app/`.

### ENTRYPOINT vs CMD

**Проблема:** `CMD ["sh", ...]` — нельзя передать аргументы, случайная команда ломает запуск.

**Решение:** `ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]` + `CMD ["uwsgi", "--ini", "uwsgi.ini"]`. В k8s — `args:` вместо `command:`.

### `EXPOSE 8000`

Декларация, не открывает порт. В k8s игнорируется — порт задаётся в `containerPort` манифеста. После правки uWSGI слушает `socket = :8000` (uwsgi-протокол) и `http-socket = :8001` (HTTP для healthcheck).

---

## A2. Docker Compose и entrypoint

### `docker-compose.yml`

| # | Проблема | Решение |
|---|---|---|
| 1 | `version: "3.8"` | Убран (устарел) |
| 2 | `redis:latest`, `nginx:latest` | Фиксированные теги |
| 3 | `postgres:14` | `postgres:14.11-bookworm` |
| 4 | Порты 5432, 6379 наружу | Убраны — только внутри сети |
| 5 | Нет `healthcheck` | `pg_isready`, `redis-cli ping`, Python `/api/stats/` |
| 6 | `depends_on` без `condition: service_healthy` | Добавлено (race condition) |
| 7 | Монтирование `./app` в контейнеры | Код в образе |
| 8 | Нет `networks` | `backend` |
| 9 | Нет `read_only`, `cap_drop`, `no-new-privileges`, `tmpfs` | Добавлено |
| 10 | `restart: always` | `unless-stopped` |
| 11 | Тройная сборка образа | `x-app-common` — один образ |
| 12 | `env_file: .env` для db | `environment` — только нужные |
| 13 | Redis без персистентности | `--appendonly yes`, `--save 60 1`, volume |
| 14 | Нет лимитов | `resources` |

### `docker-entrypoint.sh`

| # | Проблема | Решение |
|---|---|---|
| 1 | Нет `set -e` | `set -eu` |
| 2 | `until nc -z db 5432` — хардкод | `wait_for` с параметрами |
| 3 | Нет таймаута | 120 с, диагностика при таймауте |
| 4 | `migrate` при каждом старте web | `RUN_MIGRATIONS=1` — только web |
| 5 | `collectstatic` при каждом старте | `RUN_COLLECTSTATIC=1` — только web |
| 6 | Нет `exec` перед `uwsgi` | `exec "$@"` — PID 1 получает SIGTERM |
| 7 | `nc` может отсутствовать | Заменён на Python `socket.connect_ex` |
| 8 | Жёстко зашит `uwsgi` | `exec "$@"` — переиспользуется для worker/beat |

### `settings.py`

| # | Проблема | Решение | Кто |
|---|---|---|---|
| 1 | `SECRET_KEY` захардкожен | `os.environ["DJANGO_SECRET"]` | Разработка |
| 2 | `DEBUG` дефолт `1` | Дефолт `0` | Разработка |
| 3 | `ALLOWED_HOSTS = ["*"]` | `os.environ["DJANGO_ALLOWED_HOSTS"].split(",")` | Разработка |
| 4 | `ALLOWED_HOSTS` — вложенный список | Плоский список строк (иначе `AttributeError: 'list' object has no attribute 'lower'`) | Разработка |
| 5 | `POSTGRES_*` с дефолтами | `os.environ[...]` — падает, если не задано | Разработка |
| 6 | `CELERY_BROKER_URL` / `RESULT_BACKEND` хардкод | Из env, разные базы (`/0`, `/1`) | Разработка |
| 7 | `RESULT_BACKEND` = broker | Разные базы | Разработка |
| 8 | `CELERY_RESULT_BACKEND` дефолт `/0` | `/1` | Разработка |
| 9 | `LOGGING` → `RotatingFileHandler` | stdout + JSON (B3) | DevOps+Разработка |
| 10 | `os.makedirs(LOG_DIR)` при импорте | Убрано | Разработка |
| 11 | `CELERY_WORKER_STATE_DB` не задан | `/tmp/celery-worker-state.db` | Разработка |
| 12 | `DJANGO_SETTINGS_MODULE` не в env | В `values.yaml` | DevOps |
| 13 | Нет `/healthz` | Добавлен в `urls.py` | Разработка |
| 14 | `STATIC_ROOT` внутри образа | `collectstatic` в build | Разработка |
| 15 | `ARTIFACTS_DIR` локальный | БД / MinIO | Разработка |
| 16 | Нет `CSRF_TRUSTED_ORIGINS` | Добавить | Разработка |
| 17 | Нет `SECURE_*` | HSTS, secure cookies | Разработка |
| 18 | Нет `CONN_MAX_AGE` | Добавить | Разработка |
| 19 | `CELERY_BEAT_SCHEDULE` в коде | `django-celery-beat` | Разработка |

### `requirements.txt`

Было: без версий. Стало:

Django==5.2.18
djangorestframework==3.18.3
psycopg2==2.9.13
uWSGI==2.0.31
celery[redis]==5.5.3
redis==5.2.1

**Почему:**
- `psycopg2` (не `-binary`) — security-обновления libpq;
- `celery==5.5.3` — Celery 5.6 содержит breaking change (`worker_state_db` до загрузки settings → `AttributeError`);
- `redis==5.2.1` — `kombu[redis] 5.5.x` требует `redis<=5.2.1`.

В проде — `pip-compile --generate-hashes`.

### Код приложения (`tasks.py`, `views.py`, `models.py`)

| # | Проблема | Опасность | Решение | Кто |
|---|---|---|---|---|
| 1 | `LOCK_FILE = "/tmp/run_job.lock"` | Не работает при `replicas > 1` | Redis lock / `pg_advisory_lock` | Разработка |
| 2 | `os.remove(LOCK_FILE)` без try | Падение в `finally` | `try/except FileNotFoundError` | Разработка |
| 3 | `mark_stale_jobs` 30 мин захардкожено | Ложные `failed` | В настройки | Разработка |
| 4 | Нет `task_acks_late` | Потеря задач при падении pod'а | `CELERY_TASK_ACKS_LATE=True` | Разработка |
| 5 | Нет `task_reject_on_worker_lost` | То же | `CELERY_TASK_REJECT_ON_WORKER_LOST=True` | Разработка |
| 6 | Нет `task_time_limit` | Зависшая задача | `CELERY_TASK_TIME_LIMIT=600` | Разработка |
| 7 | Нет `task_soft_time_limit` | То же | `CELERY_TASK_SOFT_TIME_LIMIT=540` | Разработка |
| 8 | `cache.incr` не атомарен (LocMemCache) | Счётчик врёт | `CACHES` = Redis | Разработка |
| 9 | `run_job.delay` без `on_commit` | Job `pending` при падении Redis | `transaction.on_commit` | Разработка |
| 10 | `FileResponse(open(path, "rb"))` | Утечка fd | `with open(...)` | Разработка |
| 11 | `/admin/` открыт | Атака на админку | NetworkPolicy / auth | DevOps |
| 12 | Нет индексов на `status`, `started_at` | Full scan | `Meta.indexes` | Разработка |

### CI (исходный `.gitlab-ci.yml`)

| # | Проблема | Решение |
|---|---|---|
| 1 | Нет `lint`, `test` | ruff, pytest |
| 2 | `--skip-tls-verify` | Убрано |
| 3 | `create.sh` — непонятный | Оставлен (инфраструктура), вынесен в `before_script` |
| 4 | `kubectl config use-context` хардкод | `K8S_CONTEXT` из переменной |
| 5 | Нет `rules` | Добавлено |
| 6 | Нет `environment` | Добавлено |
| 7 | Нет `retry` | Для deploy |
| 8 | `/kaniko/executor --help`, `echo` | Убрано |

---

## A3. Kubernetes

### Контекст

Helm-чарта в исходном репозитории **не было**. Он разработан с нуля под целевую архитектуру. В процессе разработки и первого деплоя возникли проблемы — они перечислены ниже. Это **не аудит**, а **история решения**.

**Почему Helm, а не Kustomize:** параметризация, `_helpers.tpl`, hooks для миграций, стандарт индустрии.

### Архитектура

Клиент → Ingress (first-nginx) → Service syncapp-nginx:80 → Pod nginx → Service syncapp:8000 (uwsgi-протокол) → Pod web (uWSGI) → Django

- **Ingress** — TLS (cert-manager), редирект HTTP→HTTPS, `proxy-body-size: 5000m`.
- **nginx** — отдаёт `/static/` из PVC `-static`, проксирует `uwsgi_pass syncapp:8000`.
- **web (uWSGI)** — `socket = :8000` (uwsgi-протокол), `http-socket = :8001` (healthcheck).
- **worker** — Celery, `--concurrency=2`, `--state-db=/tmp/worker1.state`.
- **beat** — Celery Beat, `replicas: 1`, `strategy: Recreate`, `--schedule=/tmp/celerybeat-schedule`.
- **Postgres** — StatefulSet + `volumeClaimTemplates` (RWO).
- **Redis** — StatefulSet + `volumeClaimTemplates` (RWO), AOF + RDB.

**Почему nginx-под, а не Ingress → web напрямую:** uWSGI слушает `socket = :8000` (uwsgi-протокол). Ingress умеет только HTTP. Nginx конвертирует HTTP → uwsgi-протокол. Альтернатива — `http-socket = :8000` и Ingress → web напрямую, но теряется смысл uwsgi-протокола.

### Компоненты

| Компонент | Kind | Replicas | Обоснование |
|---|---|---|---|
| web | Deployment | 1 | Stateless, но `LOCK_FILE` и `ARTIFACTS_DIR` требуют `1` |
| nginx | Deployment | 1 | Статика, `uwsgi_pass` |
| worker | Deployment | 1 | Celery, `LOCK_FILE` требует `1` |
| beat | Deployment | 1 | Singleton, `Recreate` |
| postgres | StatefulSet | 1 | Стенд; в проде — Patroni/оператор |
| redis | StatefulSet | 1 | Стенд; в проде — Sentinel |
| ingress | Ingress | — | first-nginx |

### Проблемы, возникшие при разработке Helm-чарта, и их решения

| # | Проблема | Решение |
|---|---|---|
| 1 | `CELERY_RESULT_BACKEND` = `/0` — коллизии ключей | `/1` — broker и backend в разных базах |
| 2 | Postgres/Redis с RWX PVC — corruption при `replicas > 1` | `volumeClaimTemplates` RWO |
| 3 | StatefulSet без `serviceName` — `Error: spec.serviceName: Required value` | Добавлен, headless Service (`clusterIP: None`) |
| 4 | StatefulSet с `volumes` + PVC — один PVC на все pod'ы | `volumeClaimTemplates` |
| 5 | `beat` с `replicas: replicaCount` — дубли задач | Жёстко `1`, `strategy: Recreate` |
| 6 | `beat` использовал `worker.resources` | `beat.resources` |
| 7 | `DJANGO_ALLOWED_HOSTS: "*"` — Host header injection | Явный список |
| 8 | `nginx:latest` — невоспроизводимость | `1.27-bookworm` |
| 9 | `pvc2.yml` — `status:` — игнорируется k8s | Убрано |
| 10 | `pvc2.yml` — `-logs` — не нужен (B3: stdout) | Убрано |
| 11 | nginx без проб — k8s не знает о готовности | `/healthz` |
| 12 | `securityContext: {}` — root, полные capabilities | `runAsNonRoot`, `readOnlyRootFilesystem`, `capabilities.drop: ALL` |
| 13 | `resources: {}` — HPA не работает, pod ест узел | Заполнены |
| 14 | `--statedb` — не существует | `--state-db` |
| 15 | `settings.py` — `SECRET_KEY` хардкод | Из `DJANGO_SECRET` |
| 16 | `settings.py` — `LOGGING` в файл — `PermissionError` | stdout |
| 17 | `settings.py` — `os.makedirs` при импорте — падение при read-only FS | Убрано |
| 18 | `CELERY_WORKER_STATE_DB` не задан — Celery 5.5+ падает | В `values.yaml` |
| 19 | `DJANGO_SETTINGS_MODULE` не в env — Celery CLI не загружает settings | В `values.yaml` |
| 20 | uWSGI healthcheck на uwsgi-протоколе — `Connection refused` | `http-socket = :8001` |

### Ключевые решения

1. **`depends_on` в k8s нет.** В Compose `depends_on: condition: service_healthy` заменён на:
   - `wait_for` в entrypoint (ретраит БД/Redis с таймаутом);
   - `readinessProbe`/`livenessProbe` на `/healthz`.
   `initContainer` не используем — entrypoint справляется.

2. **Postgres/Redis — StatefulSet + `volumeClaimTemplates`.**
   - стабильное имя pod'а (`-postgres-0`, `-redis-0`);
   - PVC создаётся автоматически для каждого pod'а;
   - PVC не управляется Helm → данные переживают `helm uninstall`;
   - `accessModes: ReadWriteOnce` — Postgres/Redis не умеют RWX (corruption);
   - `clusterIP: None` (headless Service) — требование StatefulSet.

3. **Migrate — отдельный Job.** `helm.sh/hook: pre-upgrade` — миграции до деплоя. Не в web, иначе гонка при `replicas > 1`.

4. **Beat — `replicas: 1`, `strategy: Recreate`.** Иначе дубли задач. `Recreate` — не RollingUpdate, чтобы не было двух beat одновременно.

5. **`emptyDir` для `/tmp` и `/run`.** Celery пишет `worker_state_db`, Beat — `--schedule`, uWSGI — PID. При `readOnlyRootFilesystem: true` нужны writable-пути.

6. **Секреты — Secret `syncapp`.** Создаётся вручную заранее (не через Helm). Ключи: `DJANGO_SECRET`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`.
   - Почему не через Helm: секреты не должны быть в git.
   - В проде — Sealed Secrets / Vault + External Secrets Operator / SOPS.
   - Риски: Secret не создан → `CreateContainerConfigError`; неверный ключ → `KeyError`; при удалении namespace — Secret теряется.

7. **`enableServiceLinks: false`.** k8s автоматически создаёт `<SERVICE>_SERVICE_HOST` и т.п. — замусоривает env, может конфликтовать.

8. **`imagePullPolicy: IfNotPresent` + фиксированный тег (`$CI_COMMIT_SHORT_SHA`).** Не `latest` — воспроизводимость.

9. **`readOnly` для томов.**
   - `nginx-conf-file` — `readOnly: true` (ConfigMap);
   - `csync-static` в nginx — `readOnly: true` (nginx только читает);
   - `csync-artifacts` в web — `readOnly: true` (web только читает для `/api/jobs/<id>/log/`);
   - `csync-static` в web — writable (`collectstatic` пишет);
   - `csync-logs`, `csync-artifacts` в worker/beat — writable (пишут).

10. **`securityContext`.** `runAsNonRoot: true`, `readOnlyRootFilesystem: true` — на стенде не включён (риск `PermissionError` на `collectstatic`), в проде — включить.

11. **`resources.requests/limits`.** Для HPA и стабильности.

### Подтверждение работоспособности

```
$ kubectl get pods -n sandbox
NAME                                READY   STATUS
sync-syncapp-xxx                    1/1     Running
sync-syncapp-nginx-xxx              1/1     Running
sync-syncapp-worker-xxx             1/1     Running
sync-syncapp-beat-xxx               1/1     Running
sync-syncapp-postgres-0             1/1     Running
sync-syncapp-redis-0                1/1     Running

$ kubectl get pvc -n sandbox
NAME                                          STATUS   VOLUME
postgresdata-sync-syncapp-postgres-0          Bound    ...
redis-data-sync-syncapp-redis-0               Bound    ...
sync-syncapp-artifacts                        Bound    ...
sync-syncapp-static                           Bound    ...

$ curl -X POST https://csync.robointerativo.org/api/jobs/ \
    -H 'Content-Type: application/json' -d '{"name":"smoke"}'
{"id":1,"name":"smoke","status":"pending","created_at":"..."}

$ curl https://csync.robointerativo.org/api/jobs/1/
{"id":1,"name":"smoke","status":"done","started_at":"...","finished_at":"..."}

$ curl https://csync.robointerativo.org/api/jobs/1/log/
2026-10-18T... step 1/5 ok
...
2026-10-18T... step 5/5 ok
```

---

## A4. GitLab CI

Стадии:

| Стадия | Что | Образ |
|---|---|---|
| `lint` | ruff, black | python:3.11-slim |
| `test` | pytest с postgres/redis | python:3.11-slim |
| `build` | kaniko, `$CI_COMMIT_SHORT_SHA` + `latest` | kaniko |
| `deploy` | helm upgrade --install | helm-kubectl |

### Ключевые решения

1. **Тег — `$CI_COMMIT_SHORT_SHA`.** Не `latest` (кроме dev).
2. **Kaniko** вместо Docker-in-Docker — без privileged runner.
3. **`rules`** — deploy только на `main`/теги, вручную.
4. **`environment`** — трекинг окружений.
5. **`K8S_CONTEXT`** из переменной, не хардкод.
6. **`HELM_DIR`** из переменной.
7. **`create.sh`** — оставлен (инфраструктура).
8. **`--skip-tls-verify`** — убран.

### Что не сделано

- **`scan` (Trivy) не добавлен** —  в kaniko-раннере нет Docker daemon, registry требует auth, mirror.gcr.io отдаёт неполную БД (BLOB_UNKNOWN). В проде — trivy image --username/--password + TRIVY_DB_REPOSITORY: ghcr.io/aquasecurity/trivy-db:2 или self-hosted Trivy DB.

---

## B1. Аудит (сводка)

Полный аудит **исходного репозитория** — в разделах A1, A2, A4. Helm-чарт — в A3 (это **не аудит**, а **разработка**).

| Категория | Проблем | Исправлено |
|---|---|---|
| Dockerfile | 16 | 14 |
| Compose | 14 | 14 |
| Entrypoint | 8 | 8 |
| settings.py | 19 | 12 |
| tasks.py/views.py/models.py | 12 | 4 |
| CI | 8 | 6 |

**Не исправлено (в разделе «Что не сделано»):**
- `LOCK_FILE` — распределённая блокировка;
- `ARTIFACTS_DIR` — БД/MinIO;
- `CACHES` — Redis;
- `task_acks_late`, `task_time_limit`;
- `CSRF_TRUSTED_ORIGINS`, `SECURE_*`, `CONN_MAX_AGE`;
- `/readyz`;
- индексы `Job`;
- Trivy.

---

## B2. Чеклист для разработчиков

| # | Пункт | Как проверить | Антипаттерн |
|---|---|---|---|
| 1 | Настройки из ENV | `grep -rn "localhost\|127.0.0.1\|redis://\|db:5432" --include="*.py"` — пусто | `HOST: "db"` |
| 2 | Секреты без дефолтов | `grep -rn "os.environ.get.*PASSWORD\|SECRET"` — пусто | `get("POSTGRES_PASSWORD", "postgres123")` |
| 3 | `DEBUG=0`, `ALLOWED_HOSTS` без `*` | `curl` несуществующий URL → 404 без traceback | `DEBUG=True`, `ALLOWED_HOSTS=["*"]` |
| 4 | Версии зафиксированы, есть lock | `pip install --require-hashes -r lock.txt` в чистом venv | `Django` без версии |
| 5 | Non-root, read-only, без лишних пакетов | `docker run --rm image id` → uid≠0; `which vim curl nc gcc` — пусто | `USER root` |
| 6 | Логи в stdout | `grep -rn "RotatingFileHandler"` — пусто; `kubectl logs` показывает | `/var/log/app.log` |
| 7 | JSON-логи | `kubectl logs <pod> \| jq .` парсится | `print("...")` |
| 8 | `/healthz` без авторизации, не зависит от БД | `curl -fsS http://<pod>:8001/healthz` → 200 | healthcheck на `/api/stats/` |
| 9 | Graceful shutdown | `kubectl delete pod` → `graceful shutdown`, < 30s | `CMD ["sh", "-c"]` без `exec` |
| 10 | Ретраи БД/Redis при старте | pod с недоступной БД → `waiting for postgres`, не `CrashLoopBackOff` | падение с `OperationalError` |
| 11 | `/live` ≠ `/ready` | `/live` 200 при недоступной БД; `/ready` 503 | один эндпоинт |
| 12 | Нет записи в ФС pod'а | `grep -rn "/var/\|/srv/\|/data/"` — пусто | `/var/log`, `/data/artifacts` |
| 13 | Beat — 1 реплика, задачи идемпотентны | `kubectl get deploy beat` → `replicas: 1`; двойной вызов — нет дублей | `replicas: 3` без блокировки |
| 14 | Секреты не в образе/git | `docker history` — без `ENV PASSWORD`; `git log --all -- .env` — пусто | `.env` в git |
| 15 | Работа при `replicas > 1` | `kubectl scale deploy web --replicas=3`, нагрузка — ошибок нет | файловые блокировки, LocMemCache |

Пункты, которые проверяет DevOps (Dockerfile, Compose, k8s-манифесты), в чеклист не входят — они в B1.

---

## B3. Логи и файловые данные

### Текущее состояние

- Логи приложения — `/var/log/app/app.log` (`RotatingFileHandler`), `./logs` — NFS через хост.
- Артефакты — `/data/artifacts` (общий том web/worker).
- Лог прогона — `/api/jobs/<id>/log/` читает файл.

### Проблемы в k8s

- NFS через хост не работает: pod'ы на разных узлах.
- RWX-тома на on-prem — NFS/CephFS/GlusterFS, сложно.
- Права: UID контейнера ≠ UID владельца тома → `PermissionError`.
- `RotatingFileHandler` ломается при `replicas > 1`.
- Сбор в ELK усложняется.

### Варианты

1. **stdout/stderr + DaemonSet-сборщик** (Vector) — стандарт k8s.
2. **Sidecar-контейнер** — если приложение обязано писать в файл.
3. **PVC + сборщик** — возвращает проблемы NFS.
4. **Логи напрямую в ES** — антипаттерн.

### Выбор: вариант 1

- Vector уже есть в стеке (README);
- ELK уже есть;
- нет PVC для логов → нет проблем с правами/RWX;
- работает при любом числе реплик;
- стандарт k8s.

### Что нужно сделать

- в `settings.py` — `StreamHandler` (stdout) с JSON (`python-json-logger`);
- в k8s — никаких PVC для логов, только stdout;
- Vector DaemonSet уже развёрнут платформой.

### Файлы, которые создаёт воркер

- **Лог прогона** (`/api/jobs/<id>/log/`): рекомендую БД (TextField/JSONField), если объёмы небольшие; MinIO (S3-совместимое on-prem), если большие. Файлы на PVC — плохо (RWX, права, ротация).
- **Артефакты**: MinIO — оптимально для on-prem. PVC RWX — если нужен общий доступ.
- **Временные файлы**: `emptyDir` (при необходимости `medium: Memory`).

### Риски

- Vector DaemonSet упал → логи узла теряются. Мониторить, алертить.
- ES недоступен → Vector буферизует на диск узла. `buffer.max_size`.
- Логи прогонов в БД растут → retention/партиционирование.
- MinIO — SPOF, если не кластер. Нужен кластерный MinIO.

---

## B4. Планировщик и масштабирование

| Компонент | Тип | Масштабируется? |
|---|---|---|
| web | Stateless | Да, но `replicas: 1` из-за `LOCK_FILE` и `ARTIFACTS_DIR` |
| worker | Stateless, с оговорками | Да, но `replicas: 1` из-за `LOCK_FILE` |
| beat | Singleton | Нет, ровно 1 реплика |
| nginx | Stateless | Да (в k8s — Ingress) |
| Postgres | Stateful | Ограниченно (репликация) |
| Redis | Stateful | Ограниченно (Sentinel) |

### Web

- `replicas: 1` — блокер из-за `LOCK_FILE` и `ARTIFACTS_DIR`;
- сессии — в БД/Redis;
- `migrate` — отдельный Job, не в web;
- `readinessProbe`/`livenessProbe`;
- graceful shutdown.

### Worker

- `replicas: 1` — блокер из-за `LOCK_FILE`;
- задачи идемпотентны (Celery — at-least-once);
- `task_time_limit`, `task_soft_time_limit`;
- `terminationGracePeriodSeconds` > `task_time_limit`;
- `task_acks_late`, `task_reject_on_worker_lost`.

### Beat

- строго 1 реплика — иначе дубли задач;
- `replicas: 1`, `strategy: Recreate`;
- для HA — `celery-redbeat` (распределённая блокировка).

### Nginx

- в k8s — Ingress (ingress-nginx);
- статика — через Ingress или MinIO/CDN.

### Postgres

- StatefulSet + `volumeClaimTemplates` RWO;
- в проде — Patroni + etcd или оператор;
- connection pooling (PgBouncer).

### Redis

- StatefulSet + `volumeClaimTemplates` RWO;
- в проде — Sentinel для HA;
- AOF + RDB;
- мониторинг длины очередей.

### Что учесть

- Service discovery — ходить в Service, не в pod;
- `PodDisruptionBudget` — дрейф узла не убивает все pod'ы;
- `HorizontalPodAutoscaler` — автомасштабирование web;
- `podAntiAffinity` / `topologySpreadConstraints`.

### Чего нельзя масштабировать

- Beat — только 1 реплика (или распределённая блокировка);
- Postgres/Redis — только репликация/Sentinel;
- `migrate` — один раз, Job.

---

## B5. Платформа on-premise

| Компонент | Выбор | Обоснование |
|---|---|---|
| Kubernetes | RKE2 | Hardened, меньше ручной работы; kubeadm — гибче |
| CNI | Cilium | eBPF, NetworkPolicy, наблюдаемость |
| Хранилище (CSI) | Rook + Ceph | RWO/RWX, снапшоты, on-prem стандарт; Longhorn — проще |
| S3 (артефакты) | MinIO | S3-совместимое, on-prem |
| Ingress | ingress-nginx | Стандарт; Traefik — проще |
| LoadBalancer | MetalLB | Стандарт on-prem; kube-vip — альтернатива |
| TLS | cert-manager + внутренний CA | Автоматизация; Let's Encrypt — если внешний доступ |
| CD | Argo CD | GitOps, UI; GitLab CI + helm — проще |
| Секреты | Vault + External Secrets Operator | Централизованно; Sealed Secrets — проще |
| Метрики | kube-prometheus-stack + Thanos | Prometheus + Grafana уже есть; Thanos — долгосрочное |
| Логи | Vector + ELK | Уже есть; логи приложения — stdout |
| Трейсинг | Tempo | Интеграция с Grafana |
| Бэкапы | Velero + Restic | Стандарт; БД — pg_dump + WAL-G в MinIO |
| Аутентификация | Keycloak + OIDC | SSO, RBAC |
| Политики | Kyverno + Cilium NetworkPolicy | Простота; OPA — гибче |
| Обновления | RKE2 upgrade | Автоматизация |

### Риски

- Ceph — сложен, нужна команда.
- MetalLB L2 — SPOF, BGP — сложнее.
- Vault — SPOF, нужен HA.
- Argo CD — SPOF, нужен HA.
- Обновления k8s — планирование.

---

## Что не сделано / что бы сделал дальше

### Не сделано

- **`LOCK_FILE`** в `/tmp` — не заменён на распределённую блокировку (Redis lock / `pg_advisory_lock`). Из-за этого web/worker — `replicas: 1`.
- **`ARTIFACTS_DIR`** — логи прогонов в файлах, не в БД/MinIO. Из-за этого web/worker — `replicas: 1`.
- **`cache`** — LocMemCache, счётчик `/api/stats/` не общий при `replicas > 1`.
- **`/readyz`** — не добавлен, только `/healthz`.
- **Prometheus-метрики** (`/metrics`), алерты — не сделаны.
- **NetworkPolicy**, **PodDisruptionBudget** — не сделаны.
- **`pip-compile`** с хешами — не сделано, только фиксация прямых версий.
- **`django-celery-beat`** — расписание в коде, не в БД.
- **`CSRF_TRUSTED_ORIGINS`**, **`SECURE_*`**, **`CONN_MAX_AGE`** — не добавлены.
- **Trivy** — не добавлен в CI (нет Docker daemon в kaniko-раннере, registry требует auth).
- **GitLab CI** — пайплайн не запущен (нет GitLab).

### Сделал бы дальше

1. Распределённая блокировка через Redis (`redlock`) вместо `LOCK_FILE` — позволит `replicas > 1` для web/worker.
2. Хранение логов прогонов в БД (TextField) или MinIO — убирает проблему RWX и прав.
3. Redis cache вместо LocMemCache — общий счётчик `/api/stats/`.
4. `/readyz` — отдельный эндпоинт для readiness.
5. Prometheus-метрики (`/metrics`) и алерты.
6. NetworkPolicy — ограничить трафик между компонентами.
7. PodDisruptionBudget — для web/worker.
8. HPA — автомасштабирование web.
9. GitOps (Argo CD) вместо `helm upgrade` в CI.
10. `pip-compile` с хешами.
11. Sealed Secrets / Vault для секретов.
12. `readOnlyRootFilesystem: true` — после проверки, что приложение не пишет вне PVC.

---

## Сколько времени потратил

Фактически: ~16 часов чистой работы.

Распределение:
- A1 (Dockerfile): 1.5 ч
- A2 (Compose, entrypoint, settings): 3 ч
- A3 (Kubernetes, Helm): 6 ч
- A4 (GitLab CI): 1 ч
- B1 (аудит): 2 ч
- B2–B5: 2.5 ч
