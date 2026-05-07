import asyncio
import json
import logging
import os
from typing import Dict, List, Set

import requests
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from branch_config import BranchConfig, parse_branches

# Логирование в stdout (Docker friendly)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - [%(levelname)s] -  %(name)s - (%(filename)s).%(funcName)s(%(lineno)d) - %(message)s',
)

# ================================================================
# CONFIG
# ================================================================

API_TOKEN = os.getenv('API_TOKEN', "8263375262:AAEGdPIg4wgBoQCC8lDB-tSNPdQycVocT2s")
ORCHESTRA_URL = os.getenv('ORCHESTRA_URL', 'http://192.168.0.38:8080/')
ORCHESTRA_LOGIN = os.getenv('ORCHESTRA_LOGIN', 'superadmin')
ORCHESTRA_PASSWORD = os.getenv('ORCHESTRA_PASSWORD', 'ulan')

BRANCH_ID = int(os.getenv('BRANCH_ID', '6'))
ORCHESTRA_ENTRY_POINT_ID = int(os.getenv('ORCHESTRA_ENTRY_POINT_ID', '2'))
ORCHESTRA_BRANCH_CODE = os.getenv('ORCHESTRA_BRANCH_CODE', 'NTR')

SERVICE_BLACKLIST = {
    name.strip()
    for name in os.getenv('SERVICE_BLACKLIST', 'Оплата услуг').split(',')
    if name.strip()
}
logging.info("Service blacklist: %s", SERVICE_BLACKLIST)


def load_branches() -> List[BranchConfig]:
    return parse_branches(
        branches_raw=os.getenv("ORCHESTRA_BRANCHES", ""),
        default_branch_id=BRANCH_ID,
        default_branch_name=os.getenv("ORCHESTRA_BRANCH_NAME", "Основное отделение"),
        default_branch_code=ORCHESTRA_BRANCH_CODE,
        default_entry_point_id=ORCHESTRA_ENTRY_POINT_ID,
    )


BRANCHES = load_branches()
BRANCH_MAP: Dict[int, BranchConfig] = {b.branch_id: b for b in BRANCHES}
USER_BRANCH_SUBSCRIPTIONS: Dict[int, Set[str]] = {}

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

# ================================================================
#  GLOBAL METRICS FOR WATCHDOG
# ================================================================

last_connect_ok = 0        # timestamp последнего успешного /meta/connect
last_event_received = 0    # timestamp последнего события
cometd_task = None         # ссылка на фоновой CometD-задачу
cometd_reconnecting = False # флаг: идёт цикл переподключения после ошибки


# ================================================================
#   CometD IMPLEMENTATION (FIX + RECOVERY)
# ================================================================
async def run_cometd_session(bot: Bot, cometd_url: str, channel_subscribe_list: List[str], channel_init: str):
    """
    Полностью исправленная сессия CometD.
    Реализует новый handshake, subscribe, INIT и бесконечный loop connect.
    """
    global last_connect_ok, last_event_received

    logging.info("Opening new aiohttp ClientSession() for CometD")
    auth = aiohttp.BasicAuth(ORCHESTRA_LOGIN, ORCHESTRA_PASSWORD)

    async with aiohttp.ClientSession(auth=auth) as session:

        # Сбрасываем cookie
        bayeux_cookies = {}
        last_connect_ok = last_event_received = asyncio.get_event_loop().time()

        # ============================================================
        # HANDSHAKE
        # ============================================================
        handshake_msg = [{
            "channel": "/meta/handshake",
            "version": "1.0",
            "minimumVersion": "1.0",
            "supportedConnectionTypes": ["long-polling"],
            "id": "0",
        }]
        logging.info("Sending handshake to %s", cometd_url)

        async with session.post(cometd_url, json=handshake_msg, timeout=20) as resp:
            text = await resp.text()
            logging.debug("Handshake HTTP %s body=%s", resp.status, text)

            # Сохраняем BAYEUX_BROWSER
            if "BAYEUX_BROWSER" in resp.cookies:
                v = resp.cookies["BAYEUX_BROWSER"].value
                bayeux_cookies["BAYEUX_BROWSER"] = v
                logging.info("Handshake cookie BAYEUX_BROWSER=%s", v)
            else:
                logging.warning("Handshake did NOT return BAYEUX_BROWSER cookie")

        try:
            payload = json.loads(text)
        except:
            raise RuntimeError(f"Handshake returned invalid JSON: {text}")

        if not isinstance(payload, list) or not payload:
            raise RuntimeError(f"Handshake unexpected payload: {payload}")

        hs = payload[0]
        if not hs.get("successful"):
            raise RuntimeError(f"Handshake FAILED: {hs.get('error')}")

        client_id = hs.get("clientId")
        if not client_id:
            raise RuntimeError("Handshake returned no clientId")

        logging.info("Handshake OK clientId=%s", client_id)

        # ============================================================
        # SUBSCRIBE
        # ============================================================
        for index, channel_subscribe in enumerate(channel_subscribe_list, start=1):
            sub_msg = [{
                "channel": "/meta/subscribe",
                "clientId": client_id,
                "subscription": channel_subscribe,
                "id": str(index),
            }]
            logging.info("Subscribing to %s", channel_subscribe)

            async with session.post(
                    cometd_url,
                    json=sub_msg,
                    timeout=20,
                    cookies=bayeux_cookies or None,
            ) as resp:
                text = await resp.text()
                logging.debug("Subscribe HTTP %s body=%s", resp.status, text)

            payload = json.loads(text)
            if not payload[0].get("successful"):
                raise RuntimeError(f"Subscribe FAILED: {payload[0].get('error')}")

        # ============================================================
        # INIT
        # ============================================================
        for index, channel_subscribe in enumerate(channel_subscribe_list, start=2):
            branch_prefix = channel_subscribe.split("/")[2]
            prm = {"uid": f"{branch_prefix}:QVoiceLight", "type": 67, "encoding": "QP_JSON"}
            c = {"CMD": "INIT", "TGT": "CFM", "PRM": prm}
            publish_data = {"M": "C", "C": c, "N": "0"}

            init_msg = [{
                "channel": channel_init,
                "clientId": client_id,
                "data": publish_data,
                "id": str(index),
            }]
            logging.info("Publishing INIT for prefix %s", branch_prefix)

            async with session.post(
                    cometd_url,
                    json=init_msg,
                    timeout=20,
                    cookies=bayeux_cookies or None
            ) as resp:
                logging.debug("INIT reply: %s", await resp.text())

        # ============================================================
        # CONNECT LOOP
        # ============================================================
        next_id = 3

        while True:

            connect_msg = [{
                "channel": "/meta/connect",
                "clientId": client_id,
                "connectionType": "long-polling",
                "id": str(next_id),
            }]
            next_id += 1

            try:
                async with session.post(
                        cometd_url,
                        json=connect_msg,
                        timeout=90,
                        cookies=bayeux_cookies or None,
                ) as resp:
                    text = await resp.text()

            except Exception as e:
                logging.error("Connect error: %s", e)
                raise RuntimeError("Connection dropped")

            logging.debug("Connect reply: %s", text)

            try:
                messages = json.loads(text)
            except:
                logging.warning("Bad JSON in connect: %s", text)
                continue

            if isinstance(messages, dict):
                messages = [messages]

            for msg in messages:
                channel = msg.get("channel")

                # --------- META CONNECT ---------
                if channel == "/meta/connect":
                    if msg.get("successful"):
                        last_connect_ok = asyncio.get_event_loop().time()
                    else:
                        error = msg.get("error", "")
                        if "402::Unknown" in error:
                            raise RuntimeError("Unknown client - restart required")
                        advice = msg.get("advice", {})
                        if advice.get("reconnect") == "handshake":
                            raise RuntimeError("Server requested re-handshake")
                    continue

                # --------- SUBSCRIBE CHANNEL ---------
                if channel in channel_subscribe_list:
                    last_event_received = asyncio.get_event_loop().time()
                    data = msg.get("data")

                    # Parse JSON
                    if isinstance(data, str):
                        try:
                            data = json.loads(data)
                        except:
                            continue

                    E = (data or {}).get("E", {})
                    event_type = E.get("evnt")

                    if event_type == "VISIT_CALL":
                        prm = E.get("prm", {})
                        chat_id = prm.get("TelegramCustomerId")
                        if chat_id:
                            branch_prefix = channel.split("/")[2] if channel and channel.count("/") >= 2 else None
                            try:
                                chat_id_int = int(chat_id)
                            except (TypeError, ValueError):
                                continue
                            allowed_prefixes = USER_BRANCH_SUBSCRIPTIONS.get(chat_id_int, set())
                            if branch_prefix and allowed_prefixes and branch_prefix not in allowed_prefixes:
                                continue
                            try:
                                await bot.send_message(
                                    chat_id_int,
                                    "Уважаемый клиент! Вы вызваны к специалисту. Обратите внимание на ТВ-панель. Заранее спасибо!"
                                )
                            except:
                                logging.exception("Telegram send error")


# ================================================================
# WATCHDOG — гарантирует восстановление при любом зависании
# ================================================================
async def cometd_watchdog(start_callback):
    """
    Следит за живучестью CometD:
    - отсутствие connect > 120 сек
    - падение фоновой задачи
    - «тихая смерть» после пересброса Orchestra
    """
    global cometd_task, last_connect_ok, last_event_received, cometd_reconnecting

    CHECK_INTERVAL = 30
    CONNECT_TIMEOUT = 120

    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        now = asyncio.get_event_loop().time()

        reason = None

        if cometd_task is None or cometd_task.done():
            reason = "CometD coroutine crashed"

        elif last_connect_ok and (now - last_connect_ok) > CONNECT_TIMEOUT:
            # если основной цикл уже в фазе reconnect/backoff — не форсируем отдельный restart
            if not cometd_reconnecting:
                reason = "No /meta/connect replies"

        if reason:
            logging.warning("WATCHDOG: restarting CometD because: %s", reason)

            if cometd_task is not None:
                cometd_task.cancel()
                try:
                    await cometd_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logging.exception("CometD task failed during watchdog restart")

            await asyncio.sleep(2)
            cometd_task = start_callback()


# ================================================================
# MAIN WRAPPER
# ================================================================
async def cometd(bot: Bot):
    cometd_url = f"{ORCHESTRA_URL.rstrip('/')}/cometd"
    channel_subscribe_list = [f"/events/{branch.prefix}/QVoiceLight" for branch in BRANCHES]
    channel_init = "/events/INIT"

    global cometd_reconnecting, last_connect_ok

    retry_delay = 2
    max_retry_delay = 60

    while True:
        try:
            cometd_reconnecting = False
            await run_cometd_session(bot, cometd_url, channel_subscribe_list, channel_init)
            retry_delay = 2
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # connect-сессия завершилась: переходим в режим controlled reconnect
            cometd_reconnecting = True
            last_connect_ok = 0
            logging.exception("CometD session ended, will reconnect in %ss: %s", retry_delay, exc)
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_retry_delay)


# ================================================================
# TELEGRAM BOT PART
# ================================================================
class States(StatesGroup):
    repair_ticket = State()
    branch = State()
    get_ticket = State()
    appointment = State()


main_menu_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Взять талон", callback_data="take-ticket")],
])


def get_branches_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    for branch in BRANCHES:
        keyboard.add(InlineKeyboardButton(text=branch.name, callback_data=f"branch:{branch.branch_id}"))
    return keyboard


def get_single_branch_id() -> int:
    if len(BRANCHES) == 1:
        return BRANCHES[0].branch_id
    return 0


def get_services_request(branch_id: int):
    url = f'{ORCHESTRA_URL}rest/servicepoint/branches/{branch_id}/services/'
    logging.info("GET services: %s", url)
    r = requests.get(url, auth=(ORCHESTRA_LOGIN, ORCHESTRA_PASSWORD))
    return r.json()


def create_visit(branch_id: int, entry_point_id: int, service_id: int, customer_id: str, customer_name: str):
    url = f'{ORCHESTRA_URL}rest/entrypoint/branches/{branch_id}/entryPoints/{entry_point_id}/visits/'
    data = {
        "services": [service_id],
        "parameters": {
            "TelegramCustomerId": customer_id,
            "TelegramCustomerFullName": customer_name,
        }
    }
    r = requests.post(
        url, json.dumps(data),
        auth=(ORCHESTRA_LOGIN, ORCHESTRA_PASSWORD),
        headers={'Content-type': 'application/json'}
    )
    if r.status_code == 200:
        return r.json()
    return None


def get_services(branch_id: int):
    items = get_services_request(branch_id)
    keyboard = InlineKeyboardMarkup(row_width=2)

    for service in items:
        name = service.get('internalName') or service.get('name') or str(service.get('id'))
        if name in SERVICE_BLACKLIST:
            continue
        keyboard.insert(InlineKeyboardButton(text=name, callback_data=str(service['id'])))

    return keyboard


@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("Добро пожаловать!")
    await message.answer("Выберите действие:", reply_markup=main_menu_keyboard)


@dp.callback_query_handler(lambda c: c.data.isdigit(), state="*")
async def pick_service(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    service_id = int(callback.data)
    state_data = await state.get_data()
    branch_id = int(state_data.get("branch_id", BRANCH_ID))
    branch = BRANCH_MAP.get(branch_id)
    if not branch:
        await bot.send_message(callback.from_user.id, "Отделение не найдено")
        await state.finish()
        return

    visit = create_visit(
        branch.branch_id,
        branch.entry_point_id,
        service_id,
        str(callback.from_user.id),
        callback.from_user.full_name,
    )
    if visit:
        ticket = visit.get("ticketId") or visit.get("ticket")
        await bot.send_message(callback.from_user.id, f"Ваш талон: {ticket}")
        USER_BRANCH_SUBSCRIPTIONS.setdefault(callback.from_user.id, set()).add(branch.prefix)
#         await bot.send_message(
#             callback.from_user.id,
#             "Хотите ещё? Выберите услугу:",
#             reply_markup=get_services(BRANCH_ID)
#         )
    else:
        await bot.send_message(callback.from_user.id, "Ошибка создания талона")

    await state.finish()


@dp.callback_query_handler(state="*")
async def callbacks(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.data == "take-ticket":
        single_branch_id = get_single_branch_id()
        if single_branch_id:
            await state.update_data(branch_id=single_branch_id)
            await bot.send_message(
                callback.from_user.id,
                "Выберите услугу:",
                reply_markup=get_services(single_branch_id)
            )
            await state.set_state(States.get_ticket)
        else:
            await bot.send_message(
                callback.from_user.id,
                "Выберите отделение:",
                reply_markup=get_branches_keyboard()
            )
            await state.set_state(States.branch)
    elif callback.data.startswith("branch:"):
        branch_id = int(callback.data.split(":")[1])
        if branch_id not in BRANCH_MAP:
            await bot.send_message(callback.from_user.id, "Не удалось выбрать отделение")
            await state.finish()
            return
        await state.update_data(branch_id=branch_id)
        await bot.send_message(
            callback.from_user.id,
            "Выберите услугу:",
            reply_markup=get_services(branch_id)
        )
        await state.set_state(States.get_ticket)


# ================================================================
# STARTUP LOGIC
# ================================================================
async def on_startup(dp: Dispatcher):
    global cometd_task

    def start():
        return asyncio.create_task(cometd(dp.bot))

    # старт CometD
    cometd_task = start()

    # старт watchdog
    asyncio.create_task(cometd_watchdog(start))


def main():
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)


if __name__ == "__main__":
    main()
