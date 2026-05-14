import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

import yaml

import requests
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from branch_config import BranchConfig, parse_branches
from runtime_config import get_log_level, sanitize_payload
from visit_message import render_visit_call_message

# Логирование в stdout (Docker friendly)
logging.basicConfig(
    level=get_log_level(),
    format='%(asctime)s - [%(levelname)s] -  %(name)s - (%(filename)s).%(funcName)s(%(lineno)d) - %(message)s',
)

# ================================================================
# CONFIG
# ================================================================

API_TOKEN = os.getenv('API_TOKEN', "8263375262:AAEGdPIg4wgBoQCC8lDB-tSNPdQycVocT2s")
ORCHESTRA_URL = os.getenv('ORCHESTRA_URL', 'http://192.168.0.38:8080/')
ORCHESTRA_LOGIN = os.getenv('ORCHESTRA_LOGIN', 'superadmin')
ORCHESTRA_PASSWORD = os.getenv('ORCHESTRA_PASSWORD', 'ulan')

BRANCH_ID = os.getenv('BRANCH_ID', '6')
ORCHESTRA_ENTRY_POINT_ID = os.getenv('ORCHESTRA_ENTRY_POINT_ID', '2')
ORCHESTRA_BRANCH_CODE = os.getenv('ORCHESTRA_BRANCH_CODE', 'NTR')

SERVICE_BLACKLIST = {
    name.strip()
    for name in os.getenv('SERVICE_BLACKLIST', 'Оплата услуг').split(',')
    if name.strip()
}
QUEUE_SYSTEM = os.getenv("QUEUE_SYSTEM", "orchestra").strip().lower()
SYSTEM_BASE_URL = os.getenv("AXIOMA_URL" if QUEUE_SYSTEM == "axioma" else "ORCHESTRA_URL", ORCHESTRA_URL)
SYSTEM_LOGIN = os.getenv("AXIOMA_LOGIN" if QUEUE_SYSTEM == "axioma" else "ORCHESTRA_LOGIN", ORCHESTRA_LOGIN)
SYSTEM_PASSWORD = os.getenv("AXIOMA_PASSWORD" if QUEUE_SYSTEM == "axioma" else "ORCHESTRA_PASSWORD", ORCHESTRA_PASSWORD)
logging.info("Queue system: %s", QUEUE_SYSTEM)
logging.info("Service blacklist: %s", SERVICE_BLACKLIST)
DEFAULT_VISIT_CALL_TEMPLATE = os.getenv(
    "VISIT_CALL_TEMPLATE",
    "Уважаемый клиент! Вы вызваны к специалисту. Обратите внимание на ТВ-панель. Заранее спасибо!",
)


def load_branches() -> List[BranchConfig]:
    return parse_branches(
        branches_raw=os.getenv("ORCHESTRA_BRANCHES", ""),
        default_branch_id=BRANCH_ID,
        default_branch_name=os.getenv("ORCHESTRA_BRANCH_NAME", "Основное отделение"),
        default_branch_code=ORCHESTRA_BRANCH_CODE,
        default_entry_point_id=ORCHESTRA_ENTRY_POINT_ID,
        default_queue_system=QUEUE_SYSTEM,
        default_visit_call_template=DEFAULT_VISIT_CALL_TEMPLATE,
        branch_visit_call_templates_raw=os.getenv("ORCHESTRA_BRANCH_VISIT_CALL_TEMPLATES", ""),
    )


BRANCHES = load_branches()
BRANCH_MAP: Dict[str, BranchConfig] = {b.branch_id: b for b in BRANCHES}
USER_BRANCH_SUBSCRIPTIONS: Dict[int, Set[str]] = {}




@dataclass
class PathOption:
    text: str
    next_question_id: Optional[str] = None
    service_ids: Optional[List[str]] = None
    service_names: Optional[List[str]] = None
    multi_services_action: str = "choose"


@dataclass
class PathQuestion:
    question_id: str
    text: str
    options: List[PathOption]
    include_other_services_option: bool = False


@dataclass
class ClientPathConfig:
    root_question_id: str
    questions: Dict[str, PathQuestion]


def _parse_single_client_path(data: dict) -> Optional[ClientPathConfig]:
    root_question_id = str(data.get("root_question_id") or "").strip()
    questions_raw = data.get("questions") or {}
    if not root_question_id or not isinstance(questions_raw, dict):
        return None

    questions: Dict[str, PathQuestion] = {}
    for qid, qraw in questions_raw.items():
        qid_str = str(qid)
        if not isinstance(qraw, dict):
            continue
        options: List[PathOption] = []
        for oraw in (qraw.get("options") or []):
            if not isinstance(oraw, dict):
                continue
            text = str(oraw.get("text") or "").strip()
            if not text:
                continue
            service_ids = [str(x) for x in oraw.get("services", [])] if isinstance(oraw.get("services"), list) else None
            service_names = [str(x).strip() for x in oraw.get("service_names", []) if str(x).strip()] if isinstance(oraw.get("service_names"), list) else None
            next_question_id = str(oraw.get("next_question_id")).strip() if oraw.get("next_question_id") else None
            raw_action = str(oraw.get("multi_services_action") or "choose").strip().lower()
            multi_services_action = raw_action if raw_action in {"auto", "choose", "choose_many"} else "choose"
            options.append(
                PathOption(
                    text=text,
                    next_question_id=next_question_id,
                    service_ids=service_ids,
                    service_names=service_names,
                    multi_services_action=multi_services_action,
                )
            )

        text = str(qraw.get("text") or "").strip()
        if text and options:
            questions[qid_str] = PathQuestion(
                question_id=qid_str,
                text=text,
                options=options,
                include_other_services_option=bool(qraw.get("include_other_services_option", False)),
            )

    if root_question_id not in questions:
        return None
    return ClientPathConfig(root_question_id=root_question_id, questions=questions)


def load_client_paths() -> Dict[str, ClientPathConfig]:
    path = os.getenv("CLIENT_PATH_YAML", "client_path.yml")
    if not os.path.exists(path):
        logging.info("Client path config is not found: %s", path)
        return {}
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
    except Exception:
        logging.exception("Failed to load client path yaml: %s", path)
        return {}

    result: Dict[str, ClientPathConfig] = {}
    journeys = data.get("journeys")
    if isinstance(journeys, list):
        for idx, journey in enumerate(journeys):
            if not isinstance(journey, dict):
                continue
            cfg = _parse_single_client_path(journey)
            if not cfg:
                continue
            for branch_key in journey.get("branches", []):
                key = str(branch_key).strip()
                if key:
                    result[key] = cfg
            if journey.get("default") is True:
                result["default"] = cfg
    else:
        cfg = _parse_single_client_path(data)
        if cfg:
            result["default"] = cfg

    return result


CLIENT_PATHS = load_client_paths()


def get_client_path_for_branch(branch: BranchConfig) -> Optional[ClientPathConfig]:
    return CLIENT_PATHS.get(str(branch.branch_id)) or CLIENT_PATHS.get(branch.prefix) or CLIENT_PATHS.get(branch.name) or CLIENT_PATHS.get("default")


def get_service_name(service: dict) -> str:
    return service.get('internalName') or service.get('name') or str(service.get('id'))


def resolve_service_ids_by_names(services: List[dict], names: List[str]) -> List[str]:
    names_lower = {n.casefold() for n in names}
    return [str(s['id']) for s in services if get_service_name(s).casefold() in names_lower]


def build_client_path_keyboard(question: PathQuestion, services: List[dict]) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=1)
    for idx, option in enumerate(question.options):
        keyboard.add(InlineKeyboardButton(text=option.text, callback_data=f"path:{question.question_id}:{idx}"))

    if question.include_other_services_option:
        used_ids: Set[str] = set()
        for option in question.options:
            used_ids.update(get_option_service_ids(option, services))
        if [s for s in services if str(s['id']) not in used_ids]:
            keyboard.add(InlineKeyboardButton(text="Другое", callback_data=f"path_other:{question.question_id}"))
    return keyboard


def get_option_service_ids(option: PathOption, services: List[dict]) -> List[str]:
    if option.service_ids:
        return option.service_ids
    if option.service_names:
        return resolve_service_ids_by_names(services, option.service_names)
    return []

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

# ================================================================
#  GLOBAL METRICS FOR WATCHDOG
# ================================================================

last_connect_ok = 0        # timestamp последнего успешного /meta/connect
last_event_received = 0    # timestamp последнего события
cometd_task = None         # ссылка на фоновой CometD-задачу
kafka_task = None          # ссылка на фоновой Kafka-задачу для Axioma
cometd_reconnecting = False # флаг: идёт цикл переподключения после ошибки


# ================================================================
#   CometD IMPLEMENTATION (FIX + RECOVERY)
# ================================================================
async def run_cometd_session(
    bot: Bot,
    cometd_url: str,
    channel_subscribe_list: List[str],
    channel_init: str,
    login: str,
    password: str,
):
    """
    Полностью исправленная сессия CometD.
    Реализует новый handshake, subscribe, INIT и бесконечный loop connect.
    """
    global last_connect_ok, last_event_received

    logging.info("Opening new aiohttp ClientSession() for CometD")
    auth = aiohttp.BasicAuth(login, password)

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

            logging.debug("Connect reply received")

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

                    branch_prefix = channel.split("/")[2] if channel and channel.count("/") >= 2 else None
                    await process_visit_call_event(bot, data if isinstance(data, dict) else {}, branch_prefix)




async def process_visit_call_event(bot: Bot, data: dict, branch_prefix: str = None):
    event_context = (data or {}).get("E", {})
    if event_context.get("evnt") not in {"VISIT_CALL", "VISIT_RECALL"}:
        return

    prm = event_context.get("prm", {})
    logging.info("VISIT_CALL payload: %s", sanitize_payload(prm))
    chat_id = prm.get("TelegramCustomerId")
    if not chat_id:
        return

    try:
        chat_id_int = int(chat_id)
    except (TypeError, ValueError):
        logging.warning("VISIT_CALL skipped: TelegramCustomerId is not numeric (%s)", chat_id)
        return

    allowed_prefixes = USER_BRANCH_SUBSCRIPTIONS.get(chat_id_int, set())
    if branch_prefix and allowed_prefixes and branch_prefix not in allowed_prefixes:
        return

    branch = next((b for b in BRANCHES if b.prefix == branch_prefix), None) if branch_prefix else None
    if not branch:
        branch = BRANCHES[0] if len(BRANCHES) == 1 else None
    if not branch:
        return

    try:
        await bot.send_message(
            chat_id_int,
            render_visit_call_message(
                branch.visit_call_template,
                DEFAULT_VISIT_CALL_TEMPLATE,
                prm,
                event_context,
            ),
        )
    except Exception:
        logging.exception("Telegram send error")


def normalize_axioma_kafka_event(payload: dict) -> Tuple[dict, str]:
    if not isinstance(payload, dict):
        return {}, None

    event_type = payload.get("eventType")
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    if event_type not in {"VISIT_CALLED", "VISIT_RECALLED"} or not body:
        return {}, None

    mapped_event_type = "VISIT_CALL" if event_type == "VISIT_CALLED" else "VISIT_RECALL"
    prm = dict(body.get("parameterMap") or {})
    if "ticketId" not in prm and body.get("ticket"):
        prm["ticketId"] = body.get("ticket")
    if "servicePointName" not in prm:
        prm["servicePointName"] = ((body.get("events") or [{}])[-1].get("parameters") or {}).get("servicePointName")

    normalized = {
        "E": {
            "evnt": mapped_event_type,
            "prm": prm,
        }
    }
    return normalized, (body.get("branchPrefix") or payload.get("branchPrefix"))


def resolve_axioma_kafka_servers_by_branch() -> Dict[str, str]:
    """
    Returns mapping: branch_id -> bootstrap servers.
    Priority:
    1) ORCHESTRA_BRANCH_KAFKA_SERVERS JSON (by branch_id or prefix)
    2) AXIOMA_KAFKA_BOOTSTRAP_SERVERS
    3) debug default 192.168.8.40:29092
    """
    default_servers = os.getenv("AXIOMA_KAFKA_BOOTSTRAP_SERVERS", "").strip() or "192.168.8.40:29092"
    raw = os.getenv("ORCHESTRA_BRANCH_KAFKA_SERVERS", "").strip()
    per_branch = {}

    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                per_branch = {str(k): str(v).strip() for k, v in parsed.items() if str(v).strip()}
        except json.JSONDecodeError:
            logging.warning("Invalid ORCHESTRA_BRANCH_KAFKA_SERVERS JSON: %s", raw)

    out: Dict[str, str] = {}
    for branch in BRANCHES:
        if get_branch_connection(branch)[0] != "axioma":
            continue
        out[branch.branch_id] = (
            per_branch.get(branch.branch_id)
            or per_branch.get(branch.prefix)
            or default_servers
        )
    return out


async def consume_kafka_group(bot: Bot, topic: str, group_id: str, bootstrap_servers: str):
    from aiokafka import AIOKafkaConsumer

    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=[x.strip() for x in bootstrap_servers.split(",") if x.strip()],
        group_id=group_id,
        enable_auto_commit=True,
        auto_offset_reset="latest",
        value_deserializer=lambda v: v.decode("utf-8", errors="ignore"),
    )

    logging.info("Starting Kafka consumer for Axioma branches. topic=%s servers=%s", topic, bootstrap_servers)
    await consumer.start()
    try:
        async for msg in consumer:
            try:
                payload = json.loads(msg.value)
            except Exception:
                continue

            normalized, branch_prefix = normalize_axioma_kafka_event(payload)
            if normalized:
                await process_visit_call_event(bot, normalized, branch_prefix)
    finally:
        await consumer.stop()


async def kafka_events_consumer(bot: Bot):
    axioma_servers_by_branch = resolve_axioma_kafka_servers_by_branch()
    if not axioma_servers_by_branch:
        logging.info("No Axioma branches configured for Kafka events")
        return

    try:
        import aiokafka  # noqa: F401
    except Exception:
        logging.exception("aiokafka is not available; cannot start Kafka consumer")
        return

    topic = os.getenv("AXIOMA_KAFKA_EVENTS_TOPIC", "events").strip() or "events"
    base_group_id = os.getenv("AXIOMA_KAFKA_GROUP_ID", "telegram-queue-bot")

    unique_server_groups = sorted(set(axioma_servers_by_branch.values()))
    tasks = []
    for idx, servers in enumerate(unique_server_groups, start=1):
        group_id = f"{base_group_id}-{idx}"
        tasks.append(asyncio.create_task(consume_kafka_group(bot, topic, group_id, servers)))

    await asyncio.gather(*tasks)

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
    global cometd_task, kafka_task, last_connect_ok, last_event_received, cometd_reconnecting

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
async def run_cometd_group_forever(
    bot: Bot,
    cometd_url: str,
    channel_subscribe_list: List[str],
    channel_init: str,
    login: str,
    password: str,
):
    retry_delay = 2
    max_retry_delay = 60

    global cometd_reconnecting, last_connect_ok

    while True:
        try:
            await run_cometd_session(
                bot,
                cometd_url,
                channel_subscribe_list,
                channel_init,
                login,
                password,
            )
            retry_delay = 2
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Ошибка одной CometD-группы не должна ронять остальные.
            cometd_reconnecting = True
            last_connect_ok = 0
            logging.exception("CometD group %s ended, will reconnect in %ss: %s", cometd_url, retry_delay, exc)
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_retry_delay)


async def cometd(bot: Bot):
    channel_init = "/events/INIT"
    grouped_channels: Dict[Tuple[str, str, str], List[str]] = {}
    for branch in BRANCHES:
        queue_system, base_url, login, password = get_branch_connection(branch)
        if queue_system != "orchestra":
            logging.info("Skip CometD subscribe for branch %s (%s): queue system is %s", branch.branch_id, branch.prefix, queue_system)
            continue
        key = (base_url.rstrip("/"), login, password)
        grouped_channels.setdefault(key, []).append(f"/events/{branch.prefix}/QVoiceLight")

    global cometd_reconnecting

    cometd_reconnecting = False
    tasks = []
    for (base_url, login, password), channel_subscribe_list in grouped_channels.items():
        cometd_url = f"{base_url}/cometd"
        tasks.append(
            asyncio.create_task(
                run_cometd_group_forever(
                    bot,
                    cometd_url,
                    channel_subscribe_list,
                    channel_init,
                    login,
                    password,
                )
            )
        )

    if not tasks:
        logging.info("No Orchestra branches configured for CometD subscriptions")
        return

    await asyncio.gather(*tasks)


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


def get_single_branch_id() -> str:
    if len(BRANCHES) == 1:
        return BRANCHES[0].branch_id
    return 0


def is_branch_selection_first() -> bool:
    value = os.getenv("ORCHESTRA_FLOW_ORDER", "ACTION_FIRST").strip().upper()
    return value in {"BRANCH_FIRST", "BRANCH_THEN_ACTION"}

def get_branch_connection(branch: BranchConfig) -> Tuple[str, str, str, str]:
    queue_system = (branch.queue_system or QUEUE_SYSTEM).strip().lower()
    if queue_system not in {"orchestra", "axioma"}:
        queue_system = QUEUE_SYSTEM

    base_url = (branch.base_url or SYSTEM_BASE_URL).strip()
    login = (branch.login or SYSTEM_LOGIN).strip()
    password = (branch.password or SYSTEM_PASSWORD).strip()
    return queue_system, base_url, login, password


def get_services_request(branch: BranchConfig):
    queue_system, base_url, login, password = get_branch_connection(branch)
    base = base_url.rstrip('/')
    if queue_system == 'axioma':
        branch_id = branch.branch_id
        url = f'{base}/entrypoint/branches/{branch_id}/services'
    else:
        branch_id = branch.branch_id
        url = f'{base}/rest/servicepoint/branches/{branch_id}/services/'
    logging.info("GET services: %s", url)
    r = requests.get(url, auth=(login, password))
    return r.json()


def create_visit(branch: BranchConfig, service_ids: List[str], customer_id: str, customer_name: str):
    queue_system, base_url, login, password = get_branch_connection(branch)
    base = base_url.rstrip('/')
    if queue_system == 'axioma':
        url = f'{base}/entrypoint/branches/{branch.branch_id}/entry-points/{branch.entry_point_id}/visits'
        params = {"printTicket": "false"}
        payload = {
            "serviceIds": service_ids,
            "parameters": {
                "TelegramCustomerId": customer_id,
                "TelegramCustomerFullName": customer_name,
            },
        }
    else:
        url = f'{base}/rest/entrypoint/branches/{branch.branch_id}/entryPoints/{branch.entry_point_id}/visits/'
        params = None
        payload = {
            "services": service_ids,
            "parameters": {
                "TelegramCustomerId": customer_id,
                "TelegramCustomerFullName": customer_name,
            }
        }

    logging.info("POST create visit: %s payload=%s", url, payload)
    r = requests.post(
        url,
        json=payload,
        params=params,
        auth=(login, password),
        headers={'Content-type': 'application/json'}
    )

    if r.status_code in (200, 201):
        try:
            return r.json()
        except ValueError:
            logging.error("Create visit response is not JSON. status=%s body=%s", r.status_code, r.text)
            return None

    logging.error("Create visit failed. status=%s body=%s", r.status_code, r.text)
    return None




def is_multi_service_enabled(branch: BranchConfig) -> bool:
    global_enabled = os.getenv("ORCHESTRA_MULTI_SERVICE_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
    raw = os.getenv("ORCHESTRA_BRANCH_MULTI_SERVICE_ENABLED", "")
    if not raw:
        return global_enabled
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logging.warning("Invalid ORCHESTRA_BRANCH_MULTI_SERVICE_ENABLED JSON: %s", raw)
        return global_enabled

    branch_value = parsed.get(str(branch.branch_id), parsed.get(branch.prefix)) if isinstance(parsed, dict) else None
    if branch_value is None:
        return global_enabled
    return str(branch_value).lower() in {"1", "true", "yes", "on"}


def get_services_data(branch: BranchConfig) -> List[dict]:
    items = get_services_request(branch)
    return [
        service for service in items
        if (service.get('internalName') or service.get('name') or str(service.get('id'))) not in SERVICE_BLACKLIST
    ]


def build_services_keyboard(services: List[dict], selected_ids: Set[str], multi_enabled: bool) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=2)
    for service in services:
        service_id = str(service['id'])
        name = get_service_name(service)
        prefix = "✅ " if service_id in selected_ids else ""
        keyboard.insert(InlineKeyboardButton(text=f"{prefix}{name}", callback_data=f"service:{service_id}"))

    if multi_enabled:
        keyboard.add(InlineKeyboardButton(text="Подтвердить выбор", callback_data="service:confirm"))
    return keyboard


def get_services(branch_id: str, selected_ids: Set[str] = None, multi_enabled: bool = False) -> Tuple[InlineKeyboardMarkup, List[dict]]:
    services = get_services_data(branch)
    return build_services_keyboard(services, selected_ids or set(), multi_enabled), services


def get_path_mapped_services(state_data: dict, services: List[dict]) -> List[dict]:
    mapped_ids = {str(x) for x in state_data.get("path_mapped_service_ids", [])}
    if not mapped_ids:
        return services
    mapped_services = [service for service in services if str(service['id']) in mapped_ids]
    return mapped_services or services
@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("Добро пожаловать!")
    if is_branch_selection_first() and len(BRANCHES) > 1:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Выбрать отделение", callback_data="choose-branch")],
        ])
        await message.answer("Сначала выберите отделение:", reply_markup=keyboard)
    else:
        await message.answer("Выберите действие:", reply_markup=main_menu_keyboard)



@dp.callback_query_handler(lambda c: c.data.startswith("path:"), state="*")
async def pick_path_option(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()

    state_data = await state.get_data()
    branch_id = str(state_data.get("branch_id", BRANCH_ID))
    branch = BRANCH_MAP.get(branch_id)
    if not branch:
        await bot.send_message(callback.from_user.id, "Отделение не найдено")
        await state.finish()
        return

    client_path = get_client_path_for_branch(branch)
    if not client_path:
        await bot.send_message(callback.from_user.id, "Сценарий клиента для отделения не настроен")
        return

    _, question_id, option_idx_raw = callback.data.split(":", 2)
    question = client_path.questions.get(question_id)
    if not question:
        await bot.send_message(callback.from_user.id, "Маршрут клиента устарел, начните заново")
        await state.finish()
        return

    option_idx = int(option_idx_raw)
    if option_idx < 0 or option_idx >= len(question.options):
        await bot.send_message(callback.from_user.id, "Некорректный вариант ответа")
        return

    option = question.options[option_idx]
    services = get_services_data(branch)

    if option.next_question_id:
        next_question = client_path.questions.get(option.next_question_id)
        if not next_question:
            await bot.send_message(callback.from_user.id, "Маршрут клиента настроен неверно")
            await state.finish()
            return
        await state.update_data(path_question_id=next_question.question_id)
        await bot.send_message(callback.from_user.id, next_question.text, reply_markup=build_client_path_keyboard(next_question, services))
        await state.set_state(States.get_ticket)
        return

    service_ids = sorted(set(get_option_service_ids(option, services)))
    if not service_ids:
        await bot.send_message(callback.from_user.id, "Для этого варианта не настроены услуги")
        return

    if len(service_ids) > 1 and option.multi_services_action == "auto":
        visit = create_visit(branch, service_ids, str(callback.from_user.id), callback.from_user.full_name)
        if visit:
            ticket = visit.get("ticketId") or visit.get("ticket")
            await bot.send_message(callback.from_user.id, f"Ваш талон: {ticket}")
            USER_BRANCH_SUBSCRIPTIONS.setdefault(callback.from_user.id, set()).add(branch.prefix)
            await state.finish()
        else:
            await bot.send_message(callback.from_user.id, "Ошибка создания талона")
        return

    if len(service_ids) > 1:
        mapped_services = [service for service in services if str(service['id']) in set(service_ids)]
        allow_multi_choice = option.multi_services_action == "choose_many"
        await state.update_data(path_mapped_service_ids=service_ids, selected_service_ids=[], path_allow_multi_choice=allow_multi_choice)
        await bot.send_message(
            callback.from_user.id,
            "По выбранному ответу доступны несколько услуг. Выберите нужную:",
            reply_markup=build_services_keyboard(mapped_services, set(), allow_multi_choice),
        )
        await state.set_state(States.get_ticket)
        return

    visit = create_visit(branch, service_ids, str(callback.from_user.id), callback.from_user.full_name)
    if visit:
        ticket = visit.get("ticketId") or visit.get("ticket")
        await bot.send_message(callback.from_user.id, f"Ваш талон: {ticket}")
        USER_BRANCH_SUBSCRIPTIONS.setdefault(callback.from_user.id, set()).add(branch.prefix)
        await state.finish()
    else:
        await bot.send_message(callback.from_user.id, "Ошибка создания талона")


@dp.callback_query_handler(lambda c: c.data.startswith("path_other:"), state="*")
async def pick_path_other(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    state_data = await state.get_data()
    branch_id = str(state_data.get("branch_id", BRANCH_ID))
    branch = BRANCH_MAP.get(branch_id)
    if not branch:
        return
    client_path = get_client_path_for_branch(branch)
    if not client_path:
        return
    question_id = callback.data.split(":", 1)[1]
    question = client_path.questions.get(question_id)
    if not question:
        await bot.send_message(callback.from_user.id, "Маршрут клиента устарел, начните заново")
        await state.finish()
        return

    services = get_services_data(branch)
    used_ids: Set[str] = set()
    for option in question.options:
        used_ids.update(get_option_service_ids(option, services))

    other_services = [s for s in services if str(s['id']) not in used_ids]
    if not other_services:
        await bot.send_message(callback.from_user.id, "Других услуг не найдено")
        return

    branch = BRANCH_MAP.get(branch_id)
    await state.update_data(path_mapped_service_ids=[], selected_service_ids=[], path_allow_multi_choice=False)
    await bot.send_message(callback.from_user.id, "Выберите услугу:", reply_markup=build_services_keyboard(other_services, set(), is_multi_service_enabled(branch)))
    await state.set_state(States.get_ticket)


@dp.callback_query_handler(lambda c: c.data.startswith("service:"), state="*")
async def pick_service(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    state_data = await state.get_data()
    branch_id = str(state_data.get("branch_id", BRANCH_ID))
    branch = BRANCH_MAP.get(branch_id)
    if not branch:
        await bot.send_message(callback.from_user.id, "Отделение не найдено")
        await state.finish()
        return

    path_multi_override = state_data.get("path_allow_multi_choice")
    multi_enabled = bool(path_multi_override) if path_multi_override is not None else is_multi_service_enabled(branch)
    selected_service_ids = set(str(x) for x in state_data.get("selected_service_ids", []))
    services = get_services_data(branch)
    available_services = get_path_mapped_services(state_data, services)
    available_service_ids = {str(service['id']) for service in available_services}

    service_data = callback.data.split(":", 1)[1]
    if service_data == "confirm":
        if not selected_service_ids:
            await bot.send_message(callback.from_user.id, "Выберите хотя бы одну услугу")
            return
        service_ids = sorted(selected_service_ids)
    else:
        service_id = str(service_data)
        if service_id not in available_service_ids:
            await bot.send_message(callback.from_user.id, "Эта услуга недоступна для текущего шага. Выберите из предложенных вариантов.")
            return
        if multi_enabled:
            if service_id in selected_service_ids:
                selected_service_ids.remove(service_id)
            else:
                selected_service_ids.add(service_id)
            await state.update_data(selected_service_ids=list(selected_service_ids))
            keyboard = build_services_keyboard(available_services, selected_service_ids, multi_enabled=True)
            await callback.message.edit_reply_markup(reply_markup=keyboard)
            return
        service_ids = [service_id]

    visit = create_visit(
        branch,
        service_ids,
        str(callback.from_user.id),
        callback.from_user.full_name,
    )
    if visit:
        ticket = visit.get("ticketId") or visit.get("ticket")
        await bot.send_message(callback.from_user.id, f"Ваш талон: {ticket}")
        USER_BRANCH_SUBSCRIPTIONS.setdefault(callback.from_user.id, set()).add(branch.prefix)
    else:
        await bot.send_message(callback.from_user.id, "Ошибка создания талона")

    await state.finish()


@dp.callback_query_handler(state="*")
async def callbacks(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.data == "take-ticket":
        state_data = await state.get_data()
        preset_branch_id = str(state_data.get("branch_id", "") or "")
        if preset_branch_id in BRANCH_MAP:
            client_path = get_client_path_for_branch(BRANCH_MAP[preset_branch_id])
            if client_path:
                root_question = client_path.questions[client_path.root_question_id]
                services = get_services_data(BRANCH_MAP[preset_branch_id])
                await state.update_data(path_question_id=root_question.question_id)
                await bot.send_message(callback.from_user.id, root_question.text, reply_markup=build_client_path_keyboard(root_question, services))
            else:
                await bot.send_message(
                    callback.from_user.id,
                    "Выберите услугу:",
                    reply_markup=get_services(preset_branch_id, set(), is_multi_service_enabled(BRANCH_MAP[preset_branch_id]))[0]
                )
            await state.set_state(States.get_ticket)
            return
        single_branch_id = get_single_branch_id()
        if single_branch_id:
            await state.update_data(branch_id=single_branch_id)
            client_path = get_client_path_for_branch(BRANCH_MAP[single_branch_id])
            if client_path:
                root_question = client_path.questions[client_path.root_question_id]
                services = get_services_data(BRANCH_MAP[single_branch_id])
                await state.update_data(path_question_id=root_question.question_id)
                await bot.send_message(callback.from_user.id, root_question.text, reply_markup=build_client_path_keyboard(root_question, services))
            else:
                await bot.send_message(
                    callback.from_user.id,
                    "Выберите услугу:",
                    reply_markup=get_services(single_branch_id, set(), is_multi_service_enabled(BRANCH_MAP[single_branch_id]))[0]
                )
            await state.set_state(States.get_ticket)
        else:
            await bot.send_message(
                callback.from_user.id,
                "Выберите отделение:",
                reply_markup=get_branches_keyboard()
            )
            await state.set_state(States.branch)
    elif callback.data == "choose-branch":
        await bot.send_message(
            callback.from_user.id,
            "Выберите отделение:",
            reply_markup=get_branches_keyboard()
        )
        await state.set_state(States.branch)
    elif callback.data.startswith("branch:"):
        branch_id = callback.data.split(":", 1)[1]
        if branch_id not in BRANCH_MAP:
            await bot.send_message(callback.from_user.id, "Не удалось выбрать отделение")
            await state.finish()
            return
        await state.update_data(branch_id=branch_id)
        if is_branch_selection_first():
            await bot.send_message(callback.from_user.id, "Выберите действие:", reply_markup=main_menu_keyboard)
            await state.set_state(States.appointment)
        else:
            client_path = get_client_path_for_branch(BRANCH_MAP[branch_id])
            if client_path:
                root_question = client_path.questions[client_path.root_question_id]
                services = get_services_data(branch)
                await state.update_data(path_question_id=root_question.question_id)
                await bot.send_message(callback.from_user.id, root_question.text, reply_markup=build_client_path_keyboard(root_question, services))
            else:
                await bot.send_message(
                    callback.from_user.id,
                    "Выберите услугу:",
                    reply_markup=get_services(branch_id, set(), is_multi_service_enabled(BRANCH_MAP[branch_id]))[0]
                )
            await state.set_state(States.get_ticket)


# ================================================================
# STARTUP LOGIC
# ================================================================
async def on_startup(dp: Dispatcher):
    global cometd_task, kafka_task

    def start():
        return asyncio.create_task(cometd(dp.bot))

    # старт CometD
    cometd_task = start()

    # старт watchdog
    asyncio.create_task(cometd_watchdog(start))

    # старт Kafka consumer для Axioma branches
    kafka_task = asyncio.create_task(kafka_events_consumer(dp.bot))


def main():
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)


if __name__ == "__main__":
    main()
