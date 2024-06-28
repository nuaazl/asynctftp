import asyncio
import os
from asyncio import AbstractEventLoop
from typing import Optional, List

from packet import create_packet_from_buffer, OperateCode, ErrorPacket, ErrorCode, RequestPacket
from protocol import TftpReceiveProtocol, TftpSendProtocol
from handler import TftpReceiveHandler, TftpSendHandler


class TFTPServer(asyncio.DatagramProtocol):

    def __init__(self, file_path: str = "", loop: AbstractEventLoop = None):
        self._loop = loop or asyncio.get_event_loop()
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._tasks: List[asyncio.Task] = list()
        self._path = file_path

    @property
    def file_path(self):
        return self._path

    @file_path.setter
    def file_path(self, file_path: str):
        self._path = file_path

    async def read_func(self, request: RequestPacket, addr):
        file_path = os.path.join(self._path, request.file_name.decode())
        handler = TftpSendHandler(request.blksize)
        transport, protocol = await self._loop.create_datagram_endpoint(
            lambda: TftpSendProtocol(handler), remote_addr=addr
        )
        protocol.send(addr)
        handler.start(file_path)

    async def write_func(self, request: RequestPacket, addr):
        file_path = os.path.join(self._path, request.file_name.decode())
        handler = TftpReceiveHandler(request.blksize)
        transport, protocol = await self._loop.create_datagram_endpoint(
            lambda: TftpReceiveProtocol(handler), remote_addr=addr
        )
        protocol.ack(addr)
        handler.start(file_path)

    def connection_made(self, transport: asyncio.DatagramTransport):
        self._transport = transport

    def close(self):
        _ = map(lambda task: task.cancel(), self._tasks)
        if self._transport:
            self._transport.close()

    def connection_lost(self, exc):
        self.close()
        if exc:
            raise exc

    async def _task_func(self, request: RequestPacket, addr):
        if request.operate_code == OperateCode.READ:
            await self.read_func(request, addr)
        else:
            await self.write_func(request, addr)

    def datagram_received(self, data: bytes, addr):
        packet = create_packet_from_buffer(data)
        if packet.operate_code not in (OperateCode.WRITE, OperateCode.READ):
            self._transport.sendto(ErrorPacket(
                error_code=ErrorCode.ILLEGAL_TFTP_OPERATION,
                error_message=b"Only write or read!"
            ).__bytes__())
            return

        def call_back(t):
            if t in self._tasks:
                self._tasks.remove(t)

        task = self._loop.create_task(self._task_func(packet, addr))
        task.add_done_callback(call_back)
        self._tasks.append(task)

