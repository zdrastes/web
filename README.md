# Аналитика L2 — сайт с бэкендом

Дашборд «Обращения L2» (без изменений внешнего вида) + FastAPI-бэкенд: данные берутся
из WB Tracker вместо Excel, вход через корпоративный Keycloak (SSO), настраиваемые проекты (продукты)
и группировка меток внутри проекта.
План доработки — `план.md`.

## Запуск

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # и заполнить KEYCLOAK_* (и TRACKER_TOKEN, когда будет выдан)
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Открыть <http://localhost:8000/>. Проверка живости: <http://localhost:8000/healthz>.

Тесты: `pip install -r requirements-dev.txt`, затем `pytest`.

За HTTPS-прокси (Caddy) — раздел «Запуск с Caddy» ниже.

## Запуск с Caddy

Caddy ставится перед uvicorn: сам раздаёт HTTPS (сертификаты Let's Encrypt — автоматически,
продление тоже), перенаправляет HTTP→HTTPS и проксирует всё на приложение. Статика и API
отдаются приложением, Caddy ничего не дублирует.

1. `Caddyfile` уже в проекте. Заменить `l2-analytics.example.com` на свой домен и запустить:
   ```powershell
   caddy run --config Caddyfile
   ```
2. Приложение слушаем только на localhost — наружу смотрит Caddy:
   ```powershell
   uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers
   ```
   `--proxy-headers` нужен: uvicorn подставит реальный IP клиента из `X-Forwarded-For`
   (его ставит Caddy) — иначе в логах все посетители как `127.0.0.1`.
   Если Caddy на другой машине — `--host 0.0.0.0` плюс `--forwarded-allow-ips=<IP Caddy>`.
3. В `.env` включить `SECURE_COOKIES=1` (cookie только по HTTPS). Для HTTP-варианта
   Caddyfile оставить `SECURE_COOKIES=0` — иначе браузер не примет cookie и вход не заработает.

Варианты `Caddyfile` (переключаются правкой одного блока):

| Вариант | Блок в Caddyfile | `SECURE_COOKIES` |
|---|---|---|
| Домен с HTTPS (основной) | `l2-analytics.example.com { reverse_proxy 127.0.0.1:8000 }` | `1` |
| Внутренняя сеть без Let's Encrypt | `l2-analytics.corp.local { tls internal; reverse_proxy 127.0.0.1:8000 }` | `1` |
| HTTP для локальной проверки | `:8080 { reverse_proxy 127.0.0.1:8000 }` | `0` |

Проверка живости через Caddy: `https://<домен>/healthz` → `{"status": "ok"}`.

## Запуск на Linux-сервере

Боевой вариант: uvicorn как systemd-сервис на 127.0.0.1:8000, Caddy перед ним — HTTPS и
доступ снаружи. Команды для Debian/Ubuntu; для RHEL/Fedora отличается только установка
Caddy (см. https://caddyserver.com/docs/install).

1. Скопировать проект на сервер (без `.venv` — она соберётся заново), например в `/opt/l2-analytics`:
   ```bash
   sudo mkdir -p /opt/l2-analytics
   # scp/rsync папку проекта с рабочей машины, или git clone, если есть репозиторий
   ```
2. Зависимости и `.env`:
   ```bash
   cd /opt/l2-analytics
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   cp .env.example .env && nano .env   # KEYCLOAK_*, SECURE_COOKIES=1 (см. «Запуск с Caddy»)
   ```
3. Сервисный пользователь и права (приложение пишет SQLite-базу в свою папку):
   ```bash
   sudo useradd -r -s /usr/sbin/nologin l2analytics
   sudo chown -R l2analytics:l2analytics /opt/l2-analytics
   ```
4. Сервис uvicorn (юнит в `deploy/l2-analytics.service`):
   ```bash
   sudo cp deploy/l2-analytics.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now l2-analytics
   curl -s http://127.0.0.1:8000/healthz   # {"status": "ok"}
   ```
   Логи: `journalctl -u l2-analytics -f`.
5. Установить Caddy (идёт как systemd-сервис `caddy`, конфиг — `/etc/caddy/Caddyfile`):
   ```bash
   sudo apt install --yes debian-keyring debian-archive-keyring apt-transport-https curl
   curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
   curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
   sudo chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg
   sudo chmod o+r /etc/apt/sources.list.d/caddy-stable.list
   sudo apt update && sudo apt install --yes caddy
   ```
6. Конфиг Caddy: `Caddyfile` из проекта (домен заменить; варианты — таблица в «Запуск с Caddy»):
   ```bash
   sudo cp Caddyfile /etc/caddy/Caddyfile
   sudo nano /etc/caddy/Caddyfile   # заменить l2-analytics.example.com на свой домен
   sudo caddy validate --config /etc/caddy/Caddyfile
   sudo systemctl reload caddy
   ```
7. Открыть порты и направить DNS: A-запись домена → IP сервера; порты 80 и 443 (если ufw):
   ```bash
   sudo ufw allow 80,443/tcp
   ```
8. Проверка: `https://<домен>/healthz` → `{"status": "ok"}` (первый запрос может занять
   несколько секунд — Caddy выпускает сертификат). Затем вход на `https://<домен>/`.

Обновление версии: скопировать новый код (без `.venv`), затем:
```bash
cd /opt/l2-analytics
.venv/bin/pip install -r requirements.txt
sudo systemctl restart l2-analytics
```

Перенос существующей базы (если данные с рабочей машины нужны): остановить сервис
(`sudo systemctl stop l2-analytics`), скопировать `l2_analytics.db` в `/opt/l2-analytics`,
вернуть права (`sudo chown l2analytics:l2analytics l2_analytics.db`), запустить сервис.

## Деплой в K8s (WB GitLab CI/CD)

Проект подготовлен под CI/CD WB: GitLab CI собирает образ и деплоит Helm-чартом
`common-deploy` в K8s. Структура Per Service — Dockerfile и values-файлы сервиса
лежат вместе в `deploy/l2-analytics/` (systemd-вариант из раздела выше остаётся
как альтернатива для отдельного сервера):

```
.gitlab-ci.yml                  # пайплайн + переменные (namespace, кластеры, чарт)
deploy/
  l2-analytics.service          # systemd-юнит uvicorn (раздел «Запуск на Linux-сервере»)
  l2-analytics/
    Dockerfile                  # сборка образа (multi-stage, non-root)
    common-svc-values.yml       # общие values сервиса (Service, Harbor, Vault)
    k8s.*/cluster-values.yml    # переопределения по кластерам (ingress, chartMeta)
  common/
    common-values.yml           # общие values всех сервисов репозитория
```

### Чек-лист перед первым деплоем

1. `.gitlab-ci.yml` — заполнить TODO-значения:
   - `CI_TMPL_HELM_RELEASE_NAMESPACE` — имя K8s namespace (совпадает с подгруппой GitLab 2-го уровня);
   - `CI_TMPL_KUBE_CLUSTERS_DEV/STAGE/PROD` — кластеры своей команды (для PROD минимум 2, через запятую);
   - блок `include` — скопировать из `.gitlab-ci.yml` шаблона Python Tmpl (проект 101), версию взять из списка `&ci_tmpl_vers`;
2. `deploy/l2-analytics/Dockerfile` — сверить имя/версию базового образа с `versions.txt` проекта `base-images` (группа DevSecOps в GitLab).
3. Версия чарта `common-deploy` в `CI_TMPL_HELM_CHARTS` — актуальная (см. Releases чарта).
4. Vault — запросить права RW на `services/{namespace}/{env}/l2-analytics` и создать ключи `TRACKER_TOKEN`, `KEYCLOAK_ISSUER`, `KEYCLOAK_CLIENT_ID`, `KEYCLOAK_CLIENT_SECRET`, `KEYCLOAK_REDIRECT_URI` (адрес `{сервис}/auth/callback` из заявки Keycloak), `ADMINS`, `SECURE_COOKIES` (0 в DEV/STAGE, 1 в PROD), при внешней БД — ещё `DB_URL`. Пустое значение ключа = «не задано», приложение берёт дефолт; без KEYCLOAK_* вход на сайт вернёт 503.
5. Protected tag `v*` (Settings → Repository → Protected tags, создавать — Maintainer) и защищённая ветка `master` — без этого не будет деплоя в PROD.
6. Ingress-контроллер в K8s namespace — если ещё не установлен, тикет на команду CI/CD (ставится один раз на namespace).
7. PROD — заявка в SD на апстрим и домен `*.wb.ru` (например `l2-analytics.wb.ru`), после выполнения заменить домен в `deploy/l2-analytics/k8s.logistics-*/cluster-values.yml`. Внутренние адреса ресурса: `{namespace}-ingress-controller.{namespace}.k8s.logistics-<dc>` — dm/el/xs (в заявке — с префиксом `k8s.`).
8. База данных — по умолчанию SQLite `/app/l2_analytics.db` внутри контейнера: данные теряются при пересоздании пода. Для сохранения истории задать `DB_URL` на внешнюю базу (ключ в Vault) или уточнить поддержку PVC в README чарта `common-deploy`.
9. Логи — uvicorn пишет plaintext в stdout; для JSON-логов добавить в values `extendedLabels: { log_format: json }` (все поды namespace согласованно).

### Первый деплой

Dev-среды у namespace `logistics-devops` нет (решение платформенных девопсов):
пайплайны веток `dev`/`feature-*`/`fix-*` гоняют только тесты и сборку образа.
Деплой запускает защищённый тег `v*.*.*` на `master` (GitFlow): релиз уходит
сразу в прод-кластеры `CI_TMPL_KUBE_CLUSTERS_PROD` (bridge-джоба деплоя
переопределена — деплой только при окружении prod). Ссылка на окружение появится
в GitLab → Environments. Проверка: `{url}/healthz` → `{"status": "ok"}`, затем
вход на `{url}/`.

Секреты — только в Vault: `.env` в образ не попадает (`.dockerignore`) и в Git
не коммитится. Локально приложение по-прежнему читает `.env` рядом с проектом.

## Проекты (продукты)

Отчёт считается по проектам (продуктам), а не по всем меткам сразу:

- **Краткие итоги** — по всем задачам каждого проекта за выбранный период;
  группы показываются как подразбивка внутри проекта.
- **Динамика** — навигация по проектам сверху; группы фильтруются по выбранному проекту.
- **Настройки групп** — вкладки продуктов: группы и их метки привязаны к своему продукту.
- **Настройки меток** — метки из кэша задач фильтруются по выбранному продукту;
  свободные метки можно удалить (вернуть — из блока «Удалённые метки»).

Продукты хранятся в БД (таблица `products`) и настраиваются через «Настройки групп»
(добавить/изменить/удалить; удалить последний продукт нельзя). Стартовые продукты —
сид из команд `otchet` ботов: `SPL` (`LOGSUPPORT`/`SPL`), `WMS` (`LOGSUPPORT`/`WMS`),
`Trans` (`LOGSUPPORT`/`LTS`). Это коды выборки задач (`GET /public-api/v1/issues`);
alias'ы из `tracker_service.py` ботов (`transport-logistic-support`/…) нужны только
для создания задач и в продуктах сайта не используются.

Старая база мигрируется при первом запуске: создаётся таблица `products`, существующие
группы/метки/кэш задач привязываются к первому продукту (`SPL`); продукты с ошибочными
alias'ами вместо кодов проектов исправляются автоматически.

## Переменные .env

| Переменная | Назначение |
|---|---|
| `TRACKER_TOKEN` | токен `botband_sa` (Basic auth к `https://tracker.wb.ru`). Без него сайт работает: дашборд на нулях, `/api/sync` отвечает 503 |
| `TRACKER_NAMESPACE` / `TRACKER_PROJECT` | `LOGSUPPORT` / `SPL` |
| `TRACKER_STATUS_IDS` | фильтр статусов через запятую; пусто — без фильтра (см. Этап 0) |
| `KEYCLOAK_ISSUER` | адрес realm Keycloak (endpoints см. `{issuer}/.well-known/openid-configuration`); пусто — вход вернёт 503 |
| `KEYCLOAK_CLIENT_ID` / `KEYCLOAK_CLIENT_SECRET` | из заявки «KeyCloak Россия» (конфиденциальный клиент) |
| `KEYCLOAK_REDIRECT_URI` | адрес `{сервис}/auth/callback` — ровно как в заявке |
| `ADMINS` | логины Keycloak, получающие роль admin при первом входе; остальные — viewer (только дашборд) |
| `SESSION_TTL_HOURS` | срок жизни сессии (по умолчанию 12) |
| `SECURE_COOKIES` | `1` — только за HTTPS-прокси (Caddy, см. «Запуск с Caddy»); на HTTP оставить 0 |
| `DB_URL` | SQLAlchemy URL; пусто или не задано = SQLite-файл рядом с проектом |
| `SYNC_INTERVAL_MINUTES` | период автосинхронизации (по умолчанию 30) |
| `DEFAULT_WEEKS` | глубина отчёта `/api/data` (по умолчанию 6, как сейчас) |

## Как это устроено

```
web/
  app/
    main.py            # FastAPI: маршруты, статика, зависимости входа
    config.py          # чтение .env
    keycloak.py        # вход через Keycloak: discovery, PKCE, проверка id_token
    db.py              # модели (products, label_groups, group_labels, sprints, label_notes, issues_cache, user_sessions, sync_state)
    tracker_client.py  # WB Tracker: пагинация, 429-retry, нормализация задач
    aggregator.py      # чистая функция: (задачи, продукты, группы, глубина) → формат дашборда
    sync_service.py    # синхронизация кэша по всем продуктам + запись её состояния
    scheduler.py       # APScheduler: автосинхронизация
    static/index.html  # разметка дашборда и встроенные данные (ld-source-data)
    static/css/dashboard.css      # стили дашборда (одна колонка секций, порядок важен)
    static/js/dashboard-core.js   # ядро: состояние, рендер, графики, «Скачать HTML»
    static/js/dashboard-import.js # импорт Excel (разбор xlsx через JSZip)
    static/js/dashboard-app.js    # вход, сессия, вкладка настроек, загрузка /api/data
    static/js/vendor/jszip.js     # вендор: JSZip 3.10.1
  tests/               # pytest: агрегатор, клиент трекера, API, CRUD продуктов
  Caddyfile            # reverse-proxy конфиг Caddy (раздел «Запуск с Caddy»)
  deploy/              # деплой: l2-analytics.service — systemd-юнит (раздел «Запуск на Linux-сервере»);
                       # l2-analytics/ — Dockerfile и values для K8s (раздел «Деплой в K8s»)
```

Ключевое правило (план, раздел 2): бэкенд отдаёт `/api/data` **ровно в формате**
`ld-source-data`, фронт вызывает существующий `window.L2Dashboard.replaceData(...)` —
графики и вёрстка не тронуты.

### API

| Метод | Путь | Доступ | Назначение |
|---|---|---|---|
| GET | `/api/me` | все | `{username, display_name, is_admin, permissions}` (аноним: username=null, permissions=[]) |
| GET | `/api/data?weeks=N` | вход | агрегат формата `ld-source-data` (+ `stale`, `generated_at`, `label_notes` — расшифровки меток); `?date_from=…&date_to=…` — свой период пользователя (обе даты обязательны): отдаёт колонку сравнения — предшествующее окно той же длины — и поле `default_weeks` с дефолтным списком периодов |
| GET | `/api/settings` | функция «settings» | продукты и группы с их метками |
| PUT | `/api/settings` | функция «settings» | полная атомарная замена групп/меток |
| GET | `/api/products` | функция «settings» | список продуктов |
| POST | `/api/products` | функция «settings» | создание продукта (название, namespace, код проекта) |
| PUT | `/api/products/{id}` | функция «settings» | изменение продукта |
| DELETE | `/api/products/{id}` | функция «settings» | удаление продукта вместе с его группами (последний — нельзя) |
| GET | `/api/sprints` | функция «sprints» | спринты и их диапазоны дат |
| PUT | `/api/sprints` | функция «sprints» | полная атомарная замена спринтов (пересечения диапазонов запрещены) |
| GET | `/api/labels` | функция «settings» | расшифровки меток: `{notes: сохранённые, defaults: встроенные}` |
| PUT | `/api/labels` | функция «settings» | полная атомарная замена расшифровок (пустая строка отменяет расшифровку, в т.ч. дефолтную) |
| GET | `/api/users` | функция «users» | пользователи сайта: `{username, display_name, role, permissions}` |
| POST | `/api/users` | функция «users» | создание пользователя (логин Keycloak, роль задаёт стартовый набор функций) |
| PUT | `/api/users/{username}` | функция «users» | изменение пользователя (имя, роль, функции); свою роль/функции менять нельзя |
| GET | `/api/tracker/labels` | функция «settings» | метки из кэша задач + где распределены; `?product=N` — только метки выбранного продукта |
| POST | `/api/sync` | функция «sync» | форс-синхронизация, счётчики `{fetched, stored}` |
| GET | `/auth/login` | все | вход: живая сессия — редирект на дашборд, иначе — на страницу входа Keycloak (PKCE) |
| GET | `/auth/callback` | все | ответ Keycloak: обмен кода на токены, проверка id_token, серверная сессия |
| POST | `/auth/logout` | вход | выход: удаление сессии + адрес выхода из Keycloak (`logout_url`) |

### Правила счёта (решения по умолчанию — план, раздел 5)

1. Период обращения — по умолчанию спринт, в чей диапазон дат (границы включительно) попадает
   `created_at` по МСК; спринты задаются вручную в «Настройках» (вкладка «Настройки спринта»,
   функция «sprints»). Функция «period» не редактирует спринты: она даёт «Свои даты» в шапке
   и выбор готовых спринтов на главной. Если спринтов нет — ISO-неделя `created_at` по МСК,
   метка `W<номер>`, глубина — параметр `weeks`. Если пользователь выбрал «Свои даты» в шапке
   (функция «period»), спринты не применяются: отчёт строится по выбранному диапазону, а для
   сравнения берётся предшествующее окно той же длины (09.11–11.11 → сравнение с 06.11–08.11);
   селектор «Отчётная неделя» при этом сохраняет дефолтный список периодов, и выбор
   из него сбрасывает «Свои даты»;
   обращения вне всех диапазонов не считаются.
2. **Краткие итоги считаются по проектам**: каждая строка — все задачи проекта за неделю;
   группы — подразбивка внутри проекта.
3. Обращение с метками нескольких групп одного проекта считается **один раз**, в первой
   группе по порядку.
4. «Причина» внутри группы — первая метка этой группы по порядку (сумма причин = итог группы).
5. `rates` — доля группы от суммы всех групп проекта за неделю; у причины — доля внутри группы.
6. Нераспределённые метки не считаются; на «Настройках» виден бейдж «N не распределено».
7. При неудаче синхронизации отдаётся кэш с `stale: true`; в топбаре появляется пометка.
   Ошибка по одному продукту не отменяет синхронизацию остальных — она собирается в `last_error`.

## Минимальные правки фронтенда (план, п. 6.5)

Основа — `main.html` (страница, сохранённая из браузера; данные идентичны `Аналитика_L2 (4).html`).

1. CSP: `connect-src 'none'` → `connect-src 'self'` (иначе `fetch('/api/data')` запрещён).
2. Топбар: кнопки «Обновить» и «Настройки» (по функциям пользователя), имя пользователя, «Выйти», пометка о кэше.
3. Старт: `fetch('/api/data')` → `L2Dashboard.replaceData(...)`; источник в топбаре — «WB Tracker · N нед.».
4. Тексты: «% из Excel» → «%», «сумма итогов из Excel» → «сумма итогов»; футер объясняет новую базу процентов.
5. Карточка «Разбивка по проблеме» (под «Что меняется внутри»): линейчатая диаграмма причин
   за выбранную неделю (по убыванию, «Количество»/«%»), справа тот же список причин
   (шт. / % / Δ к прошлой неделе); клик по строке выделяет столбик и линию одновременно.
6. Вход: панель с кнопкой «Войти через SSO» (ведёт на Keycloak); после сохранения снапшота («Скачать HTML»)
   файл по-прежнему открывается сам по себе — glue-логика отключается вне `http(s)`.
   В сохранённом файле скрыты служебные кнопки топбара («Загрузить Excel», «Обновить»,
   «Настройки», «Скачать HTML») и элементы сессии (имя пользователя, «Выйти») —
   без бэкенда они не работают. При своих датах в скачанном файле в списке
   «Отчётная неделя» доступен только выбранный период (например, 16.11–18.11):
   предыдущее окно остаётся в данных только как база сравнения (Δ).

Не менялись: вёрстка, палитра, графики, навигация, «Загрузить Excel» (резерв), формат JSON.

## Этап 0 (разведка API) — чек-лист при первом запуске с токеном

- [ ] отдаёт ли `GET /public-api/v1/issues` закрытые задачи (без `status_id` / с фильтром);
- [ ] где в ответе `created_at`/метки (списки кандидатов в `tracker_client.py` — расширить по факту);
- [ ] права токена `botband_sa` на чтение всех задач SPL;
- [ ] совпадают ли W41–W46 с текущим Excel (первая проверка корректности, план п. 8.7).

Конспект наблюдений дописывать сюда же.

## Отклонения от плана

- **Авторизация**: сначала логин/пароль из `.env` (п. 8.3 плана, «сделать просто логин и пароль»),
  затем заменена на корпоративный Keycloak (OpenID Connect, Authorization Code + PKCE):
  `app/keycloak.py`, парольный вход удалён, пользователи создаются при первом входе;
  выдача функций — по-прежнему вкладка «Пользователи».
- **itsdangerous не используется**: сессия — серверная (случайный токен в cookie, в БД — sha256);
  подпись state-cookie входа делает HMAC по client_secret.
- **`sync_service.py`** вынесен из main.py: одна ответственность — один модуль.
- **`GroupLabel.category`** (опционально): если задать, тип «причины» на дашборде берётся из него
  (иначе из категории группы) — сохраняет смысл колонки «Тип» из старого Excel.
- Пустой список групп запрещён (`PUT /api/settings` → 422): дашборд не рассчитан на ноль контуров.
