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

Ниже добавлены PlantUML-диаграммы. В репозитории хранятся исходники (`.puml`) и сгенерированные SVG, которые отображаются прямо в README.

### 5.1 Сетевая работа (Network Flow)

Исходник: `docs/diagrams/network-flow.puml`  
SVG: `docs/diagrams/network-flow.svg`

![Network Flow](docs/diagrams/network-flow.svg)

### 5.2 Последовательность получения талона

Исходник: `docs/diagrams/ticket-sequence.puml`  
SVG: `docs/diagrams/ticket-sequence.svg`

![Ticket Sequence](docs/diagrams/ticket-sequence.svg)

### 5.3 Последовательность CometD-подписки и нотификаций

Исходник: `docs/diagrams/cometd-sequence.puml`  
SVG: `docs/diagrams/cometd-sequence.svg`

![CometD Sequence](docs/diagrams/cometd-sequence.svg)

