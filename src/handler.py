import asyncio
import os
import time

from typing import Optional


class BasePacketHandler:

    def __init__(self, blk_size: int, t_size: Optional[int] = None):
        self._buffer = asyncio.Queue()
        self.blk_size = blk_size
        self.t_size = t_size
        self.cur_size = 0

    @property
    def cur_percent(self):
        if self.t_size is None:
            return 0
        return round(self.cur_size / self.t_size, 4)

    def feed_eof(self):
        self._buffer.put_nowait(None)

    def feed_data(self, data):
        self.cur_size += len(data)
        self._buffer.put_nowait(data)

    def set_exception(self, exception):
        self._buffer.put_nowait(exception)

    async def get(self):
        return await self._buffer.get()

    def start(self, *args, **kwargs):
        """使用asyncio.create_task启动一个协程，去消费buffer"""


class TftpReceiveHandler(BasePacketHandler):
    async def _write_file(self, file_path: str):
        a = time.time()
        fd = open(file_path, 'wb')
        try:
            while True:
                item = await self.get()
                if item is None:
                    break
                fd.write(item)
                if len(item) < self.blk_size:
                    break
        finally:
            fd.close()

    def start(self, file_path: str):
        asyncio.create_task(self._write_file(file_path))

class TftpSendHandler(BasePacketHandler):

    async def _read_file(self, file_path: str):
        fd = open(file_path, 'rb')
        try:
            while True:
                data = fd.read(self.blk_size)
                await self.queue.put(data)
                if len(data) < self.blk_size:
                    self.feed_eof()
                    break
        finally:
            fd.close()

    def start(self, file_path):
        if os.path.exists(file_path):
            self.t_size = os.stat(file_path).st_size
            asyncio.create_task(self._read_file(file_path))
        else:
            self.set_exception(FileNotFoundError)
