import asyncio
import logging

from aiocometd import Client, ConnectionType
from aiocometd.exceptions import TransportTimeoutError


async def chat():
    nickname = "John"
    logging.basicConfig(filename='chatbot.log', level=logging.TRACE,
                        format='%(asctime)s - [%(levelname)s] -  %(name)s - (%(filename)s).%(funcName)s(%(lineno)d) - %(message)s')
    # connect to the server
    async with Client("http://rosneft.q-matic.su:8080/cometd", connection_types=[ConnectionType.LONG_POLLING,
                                                                                 ConnectionType.WEBSOCKET]) as client:
        # subscribe to channels to receive chat messages and
        # notifications about new members
        await client.subscribe("/events/SCL/QVoiceLight")
        prm = {'uid': 'SCL:QVoiceLight','type':67,'encoding':'QP_JSON','clientId': 'w1gk090q2qb5mf1w785zmh5agew' }
        c = {'CMD':'INIT','TGT':'CFM','PRM':prm}
        publishData = {'M':'C','C':c,'N':'0'}
        await client.publish(data=publishData,channel="/events/INIT")

        # listen for incoming messages
        async for message in client:
            print(f"{message}")


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(chat())
