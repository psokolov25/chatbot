import asyncio
import json
import logging

import requests
from aiocometd import Client, ConnectionType
from aiogram import Bot, Dispatcher, types, Router
from aiogram.dispatcher.fsm.context import FSMContext
from aiogram.dispatcher.fsm.state import StatesGroup, State
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

logging.basicConfig(filename='chatbot.log', level=logging.DEBUG,
                    format='%(asctime)s - [%(levelname)s] -  %(name)s - (%(filename)s).%(funcName)s(%(lineno)d) - %(message)s')

# Токен чат бота
API_TOKEN = '7981001863:AAHuu3nXf97tFqHgag84FquU9qGTsyAxwTU'  # В одинарных кавычках размещаем токен, полученный от @BotFather.
# УРЛ Орчестры
ORCHESTRA_URL = 'http://test-dev05.q-matic.su:8080/'
# Логин к орчестре
ORCHESTRA_LOGIN = 'superadmin'
# Пароль к орчестре
ORCHESTRA_PASSWORD = 'ulan'
BRANCH_ID = 6
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
form_router = Router()


async def cometd(bot: Bot):
    nickname = "John"
    logging.basicConfig(filename='chatbot.log', level=logging.DEBUG,
                        format='%(asctime)s - [%(levelname)s] -  %(name)s - (%(filename)s).%(funcName)s(%(lineno)d) - %(message)s')
    # connect to the server

    async with Client("http://test-dev05.q-matic.su:8080/cometd", connection_types=[ConnectionType.LONG_POLLING,
                                                                                 ConnectionType.WEBSOCKET]) as client:
        # subscribe to channels to receive chat messages and
        # notifications about new members
        await client.subscribe("/events/CHA/QVoiceLight")
        prm = {'uid': 'CHA:QVoiceLight', 'type': 67, 'encoding': 'QP_JSON'}
        c = {'CMD': 'INIT', 'TGT': 'CFM', 'PRM': prm}
        publishData = {'M': 'C', 'C': c, 'N': '0'}
        await client.publish(data=publishData, channel="/events/INIT")

        # listen for incoming messages
        async for message in client:
            data = message['data']
            print(message)
            a: dict = json.loads(data)

            E: dict = a.get('E')
            try:
                if E.get('evnt') == 'VISIT_CALL':
                    prm: dict = E.get('prm')
                    if prm.keys().__contains__('TelegramCustomerId'):
                        if E.get('evnt') == 'VISIT_CALL':
                            print(f"{prm}")
                            await bot.send_message(prm.get('TelegramCustomerId'),
                                                   f"Уважаемый {prm.get('TelegramCustomerFullName')}! Ваш талон {prm.get('ticket')} был вызван в кабинет {prm.get('servicePointName')}, к вам скоро подойдёт наш специалист!")
            except:
                print("")


class States(StatesGroup):
    repair_ticket = State()
    get_ticket = State()
    appointment = State()


main_menu_buttons = [
    [
        types.InlineKeyboardButton(text="Взять талон", callback_data="take-ticket"),
        #types.InlineKeyboardButton(text="Восстановить талон", callback_data="recover-ticket"),
        types.InlineKeyboardButton(text="По предзаписи", callback_data="appointment")

    ]
    ,
    []
]

main_menu_keyboard = types.InlineKeyboardMarkup(inline_keyboard=main_menu_buttons)


def get_services_request(branchId: int):
    r = requests.get(f'{ORCHESTRA_URL}rest/servicepoint/branches/{branchId}/services/',
                     auth=(f'{ORCHESTRA_LOGIN}', f'{ORCHESTRA_PASSWORD}'))
    return r.json()


def create_visit(branchId: int, serviceId: int, customerId: str, customerName: str):
    data = {'services': [serviceId],
            'parameters': {'TelegramCustomerId': customerId, 'TelegramCustomerFullName': customerName}}
    r = requests.post(f'{ORCHESTRA_URL}rest/entrypoint/branches/{branchId}/entryPoints/1/visits/',
                      json.dumps(data),
                      auth=(f'{ORCHESTRA_LOGIN}', f'{ORCHESTRA_PASSWORD}'),
                      headers={'Content-type': 'application/json'})
    if r.status_code == 200:
        return r.json()
    else:
        return ""


def get_services(branchId: int):
    items = get_services_request(branchId)
    builder = InlineKeyboardBuilder()
    i = 0

    for service in items:

        print(service)
        if i < 2:
            builder.add(types.InlineKeyboardButton(text=service['internalName'], callback_data=service['id']))
        else:
            builder.row(types.InlineKeyboardButton(text=service['internalName'], callback_data=service['id']))
            i = 0
        i = i + 1

    keyboard = builder.as_markup()
    return keyboard


@dp.message(commands=["start"])
async def send_welcome(message: types.Message, state: FSMContext):
    """
    This handler will be called when user sends `/start` or `/help` command
    """

    await state.clear()

    await message.answer("Добро пожаловать!")
    await message.answer("Выберите действие!",
                         reply_markup=main_menu_keyboard)  # Так как код работает асинхронно, то обязательно пишем await.


@dp.message(commands=['Терапевт'])
async def send_welcome(message: types.Message):
    """
    This handler will be called when user sends `/start` or `/help` command
    """
    await message.answer("Терапевт этажом выше!.")


@dp.message(States.repair_ticket)
async def process_name(message: Message, state: FSMContext) -> None:
    await message.answer(f"Ваш талон {message.text} восстановлен!")
    await state.clear()


@dp.message(States.appointment)
async def process_name(message: Message, state: FSMContext) -> None:
    r = await message.answer(f"Здравствуйте {message.reply_to_message.from_user.full_name}! Вас ждут!")

    await state.clear()


@dp.callback_query(States.get_ticket)
async def process_name(callback: types.CallbackQuery, state: FSMContext) -> None:
    r = create_visit(BRANCH_ID, callback.data, callback.from_user.id, callback.from_user.full_name)

    await bot.send_message(callback.from_user.id, f"Ваш талон {r['ticketId']}!")
    # await state.clear()


@dp.callback_query()
async def callbacks(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "take-ticket":
        keyboard = get_services(BRANCH_ID)
        await bot.send_message(callback.from_user.id, "Выберите услугу!", reply_markup=keyboard)
        await state.set_state(States.get_ticket)

    elif callback.data == "recover-ticket":
        await state.set_state(States.repair_ticket)
        await bot.send_message(callback.from_user.id, "Введите номер талона!")
    elif callback.data == "appointment":
        await state.set_state(States.appointment)
        await bot.send_message(callback.from_user.id, "Введите код предварительной записи!")


# Запуск процесса поллинга новых апдейтов

def main() -> None:
    """Starts the chat client application"""

    loop = asyncio.get_event_loop()
    chat_task = asyncio.ensure_future(cometd(bot), loop=loop)

    try:
        loop.run_until_complete(dp.start_polling(bot))
        loop.run_until_complete(chat_task)
    except KeyboardInterrupt:
        chat_task.cancel()
        loop.run_until_complete(chat_task)


if __name__ == "__main__":
    main()
loop = asyncio.get_event_loop()
