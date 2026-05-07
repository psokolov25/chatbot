# Queue Telegram Bot (Orchestra + CometD)

Бот для Telegram, который:
- показывает клиенту доступные услуги,
- создаёт визиты в Orchestra,
- слушает события Orchestra через CometD,
- отправляет уведомление клиенту при событии `VISIT_CALL`.

Основной рабочий файл: `bot2.py`.

---

## 1) Для кого этот документ

### Для разработчиков
- Где логика: `bot2.py`.
- Важные блоки: Telegram handlers, REST-интеграция Orchestra, CometD-сессия, watchdog.
- Что настраивается через env: все ключевые параметры интеграции (см. ниже).

### Для внедренцев
- Дайте корректные URL/логин/пароль Orchestra.
- Подставьте `BRANCH_ID`, `ORCHESTRA_ENTRY_POINT_ID`, `ORCHESTRA_BRANCH_CODE`.
- Проверьте, что в Orchestra в параметрах визита используются `TelegramCustomerId` и `TelegramCustomerFullName`.

### Для техподдержки
- Проверяйте логи контейнера/процесса на ошибки `Handshake`, `Connect error`, `Unknown client`.
- Бот умеет автоматически переподключаться к CometD с backoff.
- При длительных обрывах следите за доступностью `ORCHESTRA_URL` и валидностью учётных данных.

### Для отдела продаж
- Бот ускоряет цифровую очередь: выдача талона прямо в Telegram и вызов клиента без физического терминала.
- Можно быстро адаптировать сценарий под филиалы через env-параметры без изменения кода.

### Для DevOps
- Есть запуск как обычный Python-процесс, через `venv`, и через Docker/Docker Compose.
- Рекомендуемый prod-вариант: Docker Compose + `.env` + `restart: unless-stopped`.

---

## 2) Параметры конфигурации

Все параметры читаются из переменных окружения, **при этом значения по умолчанию в коде сохранены**.

| Переменная | Назначение | Значение по умолчанию |
|---|---|---|
| `API_TOKEN` | Токен Telegram-бота | задан в `bot2.py` |
| `ORCHESTRA_URL` | Базовый URL Orchestra | `http://192.168.0.38:8080/` |
| `ORCHESTRA_LOGIN` | Логин Orchestra | `superadmin` |
| `ORCHESTRA_PASSWORD` | Пароль Orchestra | `ulan` |
| `BRANCH_ID` | ID филиала | `6` |
| `ORCHESTRA_ENTRY_POINT_ID` | ID точки входа | `2` |
| `ORCHESTRA_BRANCH_CODE` | Код филиала (для CometD канала) | `NTR` |
| `SERVICE_BLACKLIST` | Услуги, скрытые в меню, через запятую | `Оплата услуг` |

Шаблон файла переменных: `.env.example`.

---

## 3) Быстрый старт

### 3.1 Подготовка `.env`

```bash
cp .env.example .env
# отредактируйте .env
```

---

## 4) Варианты развертывания

## 4.1 Запуск просто на сервере с Python

Требования:
- Python 3.8+
- Доступ к Telegram API и Orchestra

Команды:

```bash
cd /path/to/chatbot
pip install -r requirements.txt
export API_TOKEN="..."
export ORCHESTRA_URL="http://...:8080/"
export ORCHESTRA_LOGIN="..."
export ORCHESTRA_PASSWORD="..."
export BRANCH_ID="6"
export ORCHESTRA_ENTRY_POINT_ID="2"
export ORCHESTRA_BRANCH_CODE="NTR"
python bot2.py
```

---

## 4.2 Запуск на основе `venv`

```bash
cd /path/to/chatbot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
set -a
source .env
set +a
python bot2.py
```

Для Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Get-Content .env | ForEach-Object {
  if ($_ -match '^(.*?)=(.*)$') { Set-Item -Path Env:$($matches[1]) -Value $matches[2] }
}
python bot2.py
```

---

## 4.3 Запуск на основе Docker

### Вариант A: напрямую через `docker run`

```bash
docker build -t queue-bot:latest .
docker run -d \
  --name queue-bot \
  --restart unless-stopped \
  --env-file .env \
  queue-bot:latest
```

### Вариант B (рекомендуется): Docker Compose

```bash
docker compose up -d --build
```

Остановка:

```bash
docker compose down
```

Логи:

```bash
docker compose logs -f queue-bot
```

---

## 5) Операционная проверка после запуска

1. Откройте Telegram и отправьте `/start` боту.
2. Нажмите «Взять талон», убедитесь, что список услуг пришёл.
3. Создайте талон, проверьте ответ бота с номером.
4. Проверьте в логах, что CometD-сессия успешно делает handshake/connect.

---

## 6) Диагностика и типовые проблемы

- `Handshake FAILED` / `Connect error`:
  - проверьте `ORCHESTRA_URL`, сеть, логин/пароль.
- `Unknown client - restart required`:
  - штатный случай после сброса серверной сессии; бот должен переподключиться автоматически.
- Не приходят уведомления `VISIT_CALL`:
  - проверьте `ORCHESTRA_BRANCH_CODE`, канал CometD и наличие `TelegramCustomerId` в параметрах визита.

---

## 7) Безопасность

- Не храните реальные токены/пароли в Git.
- Используйте `.env`/секреты CI/CD/секреты оркестратора.
- Ограничьте доступ к логам, если в них могут встречаться чувствительные данные.

---

## 8) Развитие

Рекомендуемые улучшения:
- вынести конфигурацию в отдельный модуль,
- добавить unit/integration тесты на reconnect/watchdog,
- добавить healthcheck endpoint (если будет web-обвязка),
- добавить structured logging (JSON) для централизованного мониторинга.
