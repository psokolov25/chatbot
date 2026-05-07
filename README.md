# Queue Telegram Bot (Orchestra + CometD)

Бот для Telegram, который:
- показывает список отделений;
- после выбора отделения показывает услуги;
- создаёт талон (visit) в правильный `entryPoint` выбранного отделения;
- подписывается на CometD события по префиксам отделений;
- уведомляет клиента о вызове талона (`VISIT_CALL`) только для отделения, где клиент получил талон.

Основной runtime-файл: `main_bot.py`.

---

## 1. Конфигурация

### 1.1 Обязательные параметры

| Переменная | Назначение |
|---|---|
| `API_TOKEN` | Токен Telegram-бота |
| `ORCHESTRA_URL` | Базовый URL Orchestra |
| `ORCHESTRA_LOGIN` | Логин Orchestra |
| `ORCHESTRA_PASSWORD` | Пароль Orchestra |

### 1.2 Многофилиальный режим

Настраивается через `ORCHESTRA_BRANCHES` (JSON-массив):

```json
[
  {"id": 6, "name": "Центральное отделение", "prefix": "NTR", "entry_point_id": 2},
  {"id": 7, "name": "Северное отделение", "prefix": "SVR", "entry_point_id": 3}
]
```

Поля:
- `id` — ID отделения (`branchId`) в Orchestra;
- `name` — отображаемое имя в Telegram-меню;
- `prefix` — префикс CometD канала (`/events/{prefix}/QVoiceLight`);
- `entry_point_id` — ID точки входа для выдачи талона в этом отделении.

### 1.3 Обратная совместимость (однофилиальный режим)

Если `ORCHESTRA_BRANCHES` не задан, используется fallback:
- `BRANCH_ID`
- `ORCHESTRA_ENTRY_POINT_ID`
- `ORCHESTRA_BRANCH_CODE`
- `ORCHESTRA_BRANCH_NAME` (необязательный, название кнопки отделения)

### 1.4 Дополнительные параметры

| Переменная | Назначение | По умолчанию |
|---|---|---|
| `SERVICE_BLACKLIST` | Услуги, скрытые в меню (через запятую) | `Оплата услуг` |
| `VISIT_CALL_TEMPLATE` | Общий шаблон текста вызова посетителя для всех филиалов | `Уважаемый клиент! ...` |
| `ORCHESTRA_BRANCH_VISIT_CALL_TEMPLATES` | JSON-объект переопределений шаблона по `branchId` или `prefix` | пусто |

Шаблоны поддерживают плейсхолдеры Python `str.format` из полей `prm` события `VISIT_CALL`, например:
- `{ticketId}`, `{ticket}`, `{servicePointId}`, `{servicePointName}`, `{branchName}`, `{waitingTime}`, `{TelegramCustomerFullName}`.

Примеры:

```env
# один шаблон на все филиалы
VISIT_CALL_TEMPLATE=Клиент {ticketId}, пройдите к рабочему месту {servicePointId}

# отдельные шаблоны по branchId/prefix
ORCHESTRA_BRANCH_VISIT_CALL_TEMPLATES={"6":"Нотариус: талон {ticketId}, окно {servicePointName}","SVR":"Северный филиал: {ticket} -> {servicePointId}"}
```

---

### 1.5 Пример `.env` для нескольких филиалов

```env
API_TOKEN=...
ORCHESTRA_URL=http://127.0.0.1:8080/
ORCHESTRA_LOGIN=superadmin
ORCHESTRA_PASSWORD=ulan
ORCHESTRA_BRANCHES=[{"id":6,"name":"Центральное отделение","prefix":"NTR","entry_point_id":2},{"id":7,"name":"Северное отделение","prefix":"SVR","entry_point_id":3}]
SERVICE_BLACKLIST=Оплата услуг
```

Если `ORCHESTRA_BRANCHES` задан, бот полностью работает в многофилиальном режиме и fallback-переменные (`BRANCH_ID`, `ORCHESTRA_ENTRY_POINT_ID`, `ORCHESTRA_BRANCH_CODE`) не используются.

---

## 2. Поведение бота

1. Пользователь отправляет `/start`.
2. Нажимает «Взять талон».
3. Выбирает отделение.
4. Выбирает услугу.
5. Получает номер талона.
6. При `VISIT_CALL` в выбранном отделении получает уведомление.

---

## 3. Запуск

### 3.1 Локально

```bash
pip install -r requirements.txt
export API_TOKEN="..."
export ORCHESTRA_URL="http://...:8080/"
export ORCHESTRA_LOGIN="..."
export ORCHESTRA_PASSWORD="..."
export ORCHESTRA_BRANCHES='[{"id":6,"name":"Центральное","prefix":"NTR","entry_point_id":2}]'
python main_bot.py
```

### 3.2 Docker Compose

```bash
cp .env.example .env
# заполните .env (особенно API_TOKEN и ORCHESTRA_BRANCHES)
docker compose up -d --build
docker compose logs -f queue-bot
```

---

## 4. Тесты

```bash
pytest -q
```

Тесты покрывают парсинг и валидацию многофилиальной конфигурации (`ORCHESTRA_BRANCHES`) в `branch_config.py`.

---

## 5. Архитектура и UML-диаграммы

Ниже добавлены PlantUML-диаграммы. В репозитории хранятся исходники (`.puml`) в `docs/diagrams/src/` и сгенерированные SVG в `docs/diagrams/`, которые отображаются прямо в README.

### 5.1 Сетевая схема размещения и доступов (Network & Security Layout)

Исходник диаграммы: `docs/diagrams/src/network-flow.puml`.

> Ниже — целевая схема для ИБ/инфраструктуры: где размещать сервисы, какие потоки разрешать и что блокировать по умолчанию.

#### 5.1.1 Размещение компонентов

- **Контур заказчика (private LAN / DC / VPC):**
  - `Queue Bot` (`main_bot.py`) — VM/контейнер без внешней публикации порта.
  - `Orchestra REST API` и `Orchestra CometD endpoint` — внутренние сервисы.
  - `Orchestra DB` — отдельный внутренний сегмент (backend/data zone).
- **Внешний контур (Интернет):**
  - только `Telegram Cloud API` (`api.telegram.org`).

#### 5.1.2 Матрица сетевых доступов (ACL/FW)

| Источник | Назначение | Протокол/порт | Направление | Зачем нужно | Политика |
|---|---|---|---|---|---|
| Queue Bot | `api.telegram.org` | TCP 443 (HTTPS) | EGRESS | `getUpdates`, `sendMessage` | **ALLOW** |
| Queue Bot | Orchestra REST | TCP 443 (или 8080) | EGRESS | `GET /services`, `POST /visits` | **ALLOW** |
| Queue Bot | Orchestra CometD | TCP 443 (или порт Bayeux) | EGRESS | handshake/connect/subscribe | **ALLOW** |
| Orchestra REST/CometD | Orchestra DB | TCP `<db_port>` | EAST-WEST | чтение/запись бизнес-данных | **ALLOW (внутри private zone)** |
| Интернет | Queue Bot | Any | INGRESS | не требуется | **DENY** |
| Интернет | Orchestra REST/CometD | Any | INGRESS | не требуется | **DENY** |
| Интернет | Orchestra DB | Any | INGRESS | не требуется | **DENY** |

> Если используете нестандартные порты, зафиксируйте их в change-request и в правилах FW/NACL как отдельные явные ALLOW-правила.

#### 5.1.3 Что обязательно закрыть

- Проброс `ports:` у контейнера бота наружу.
- Публичный IP/NAT на сервере бота.
- Прямой внешний доступ к БД Orchestra.
- Админ-интерфейсы (SSH/RDP/панели) из Интернета.

#### 5.1.4 Рекомендуемая сегментация

- `APP zone`: Queue Bot.
- `SERVICE zone`: Orchestra REST/CometD.
- `DATA zone`: Orchestra DB.
- Межзонные правила — принцип **least privilege** (только конкретный src/dst/port).

#### 5.1.5 Минимальные требования к TLS и доступу

- Для всех внешних и межсервисных соединений использовать TLS 1.2+.
- Для исходящего доступа бота разрешать DNS + HTTPS только к требуемым хостам.
- Администрирование — через VPN/jump host + allowlist по источникам.
- Секреты (`API_TOKEN`, `ORCHESTRA_PASSWORD`) хранить в vault/secret-store, не в открытом `.env` в git.

#### 5.1.6 Контрольный чек-лист перед запуском

- [ ] У бота нет открытых входящих портов (`ss -lntp` / `docker ps`).
- [ ] Есть исходящий доступ к `api.telegram.org:443`.
- [ ] Есть исходящий доступ к Orchestra REST и CometD endpoint.
- [ ] Из Интернета недоступны Orchestra и DB.
- [ ] Включены логи и алерты на обрыв CometD-сессии/ошибки reconnect.


#### 5.1.7 Уточнения с учётом текущей версии бота (изменения за сегодня)

- Бот работает в **polling-режиме** (webhook не используется), поэтому внешний входящий порт для бота не требуется.
- CometD-сессия поддерживается через `handshake -> subscribe -> INIT -> connect-loop`, плюс watchdog-перезапуск при сбоях.
- Подписка выполняется **по всем филиалам** из `ORCHESTRA_BRANCHES` на каналы `/events/{prefix}/QVoiceLight`.
- Уведомления `VISIT_CALL` отправляются только адресату из `prm.TelegramCustomerId`.
- Шаблон текста вызова поддерживает глобальный `VISIT_CALL_TEMPLATE` и филиальные override через `ORCHESTRA_BRANCH_VISIT_CALL_TEMPLATES`.

![Network Flow](docs/diagrams/network-flow.svg)


### 5.2 Последовательность получения талона

Исходник: `docs/diagrams/src/ticket-sequence.puml`  
SVG: `docs/diagrams/ticket-sequence.svg`

![Ticket Sequence](docs/diagrams/ticket-sequence.svg)


**Что важно в актуальном процессе (по диаграмме):**
- На старте бот поднимает polling и CometD-подключение, включая `INIT` для каждого branch prefix.
- При выдаче талона используется endpoint `entryPoints/{entryPointId}/visits` и передаётся `parameters.TelegramCustomerId`.
- При `VISIT_CALL` бот матчит `TelegramCustomerId` из события и отправляет персональное сообщение в Telegram.

### 5.3 Последовательность CometD-подписки и нотификаций

Исходник: `docs/diagrams/src/cometd-sequence.puml`  
SVG: `docs/diagrams/cometd-sequence.svg`

![CometD Sequence](docs/diagrams/cometd-sequence.svg)


**Что важно в актуальном процессе CometD (по диаграмме):**
- Подписка создаётся по каждому `prefix` из `ORCHESTRA_BRANCHES`, затем публикуется `INIT` в `/events/INIT`.
- Основной режим доставки событий — long-polling через цикл `/meta/connect`.
- На `VISIT_CALL` бот валидирует контекст филиала и выбирает шаблон уведомления (глобальный или филиальный override).
- Сообщение отправляется строго в `chat_id = prm.TelegramCustomerId`, что исключает рассылку «чужим» пользователям.

#### 5.4 Эксплуатационные примечания по диаграммам

- `docs/diagrams/src/*.puml` — единственный источник правды для UML.
- `docs/diagrams/*.svg` — артефакты рендера для README; их нужно обновлять при изменении `.puml`.
- При изменениях в логике бота (REST endpoint, CometD lifecycle, шаблоны сообщений, multi-branch) синхронно обновляйте:
  1) соответствующий `.puml`;
  2) SVG;
  3) пояснение в разделах 5.1–5.3.
