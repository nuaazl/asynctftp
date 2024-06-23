import asyncio

from server import TFTPServer


async def tftp_server():
    _loop = asyncio.get_event_loop()
    await _loop.create_datagram_endpoint(lambda: TFTPServer(), local_addr=('0.0.0.0', 10088))


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.create_task(tftp_server())
    loop.run_forever()
    