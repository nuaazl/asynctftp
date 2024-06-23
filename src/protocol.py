import asyncio
import traceback
from asyncio import DatagramProtocol, DatagramTransport
from typing import Optional, cast, Any

from packet import OperateCode, create_packet_from_buffer, AckPacket, ReqAckPacket, ErrorPacket, ErrorCode, DataPacket, int_to_bytes
from handler import TftpReceiveHandler, TftpSendHandler


class TftpReceiveProtocol(DatagramProtocol):
    """
    接收数据
    """

    def __init__(
        self, stream_handler: TftpReceiveHandler,
    ):
        self._transport: Optional[DatagramTransport] = None
        self._ack_task: Optional[asyncio.Task] = None
        self._ack_waiter: Optional[asyncio.Future] = None
        self._block_data_id: int = 0
        self._streams = stream_handler
        self._last = False

    def connection_made(self, transport):
        self._transport = transport

    def datagram_received(self, data, addr):
        packet_data = create_packet_from_buffer(data)
        if packet_data.operate_code == OperateCode.ERROR:
            raise Exception(packet_data.error_message)
        self._last = len(packet_data.data) < self._streams.blk_size
        if packet_data.block_data_id == self._block_data_id:
            self._streams.feed_data(packet_data.data)
            self.ack(addr)
        else:
            if self._ack_waiter:
                self._ack_waiter.set_exception(
                    Exception(f"self:{self._block_data_id} and received: {packet_data.block_data_id}")
                )

    def update_block_id(self):
        """增加块序号的值"""
        self._block_data_id += 1
        if self._block_data_id > 65535:
            self._block_data_id = 0

    def create_ack_packet(self):
        if self._block_data_id != 0:
            ack_data = AckPacket(block_id=self._block_data_id).__bytes__()
        else:
            ack_data = ReqAckPacket(
                blk_size=self._streams.blk_size,
                t_size=self._streams.t_size).__bytes__()
        return ack_data

    def ack(self, addr):
        if self._ack_waiter:
            self._ack_waiter.set_result(None)
        if self._last:
            if self._ack_task:
                self._ack_task.cancel()
                self._ack_task = None
            ack_data = self.create_ack_packet()
            self._transport.sendto(ack_data, addr)
            self._streams.feed_eof()
            self._transport.close()
            return
        if self._ack_task is None:
            self._ack_task = asyncio.create_task(self._ack(addr))

    async def _ack(self, addr):
        while not self._last:
            ack_data = self.create_ack_packet()
            self.update_block_id()
            await self._ack_until_check(ack_data, addr)

    async def _ack_until_check(self, ack_data, addr):
        """
        因为有可能失败，所以一直发送，await _ack_waiter直到block_id的响应正确，否则一直发送，
        如果长时间没有回应，设置超时10s，超时后继续尝试发送
        :param ack_data:
        :param addr:
        :return:
        """
        while 1:
            self._ack_waiter = asyncio.Future()
            try:
                self._transport.sendto(ack_data, addr)
                await asyncio.wait_for(self._ack_waiter, 10)
                break
            except Exception as e:
                print(traceback.format_exc())
            finally:
                del self._ack_waiter

    def error_received(self, exc):
        if exc:
            self._streams.set_exception(exc)
            self._transport.close()
            self._last = True
            self._ack_task.cancel()


class TftpSendProtocol(DatagramProtocol):

    def __init__(self, stream: TftpSendHandler):
        self._transport: Optional[DatagramTransport] = None
        self._block_data_id: int = 0
        self._last = False
        self._stream = stream
        self._waiter: Optional[asyncio.Future] = None
        self._send_task: Optional[asyncio.Task] = None

    def connection_made(self, transport):
        self._transport = transport

    def set_exception(self, exc):
        if self._waiter:
            self._waiter.set_exception(exc)

    def set_result(self, result: Any):
        if self._waiter:
            self._waiter.set_result(result)

    def datagram_received(self, data, addr):
        packet_data = create_packet_from_buffer(data)
        print("data_received:", packet_data, self._block_data_id)
        if packet_data.operate_code == OperateCode.ERROR:
            raise Exception(packet_data.error_message)
        if cast(AckPacket, packet_data).block_id == self._block_data_id - 1:
            self.send(addr)
        else:
            self.set_exception(Exception(f"self:{self._block_data_id} and ack is :{packet_data.block_id}"))

    def update_block_id(self):
        self._block_data_id += 1
        if self._block_data_id > 65535:
            self._block_data_id = 0

    async def _get_data(self):
        data = await self._stream.get()
        if isinstance(data, Exception):
            if isinstance(data, FileNotFoundError):
                return ErrorPacket(error_code=ErrorCode.FILE_NOT_FOUND, error_message=str(data).encode()).__bytes__()
            # 需要自定义错误类型
            return ErrorPacket(error_code=ErrorCode.ILLEGAL_TFTP_OPERATION, error_message=str(data).encode()).__bytes__()
        elif data is None:
            return None
        else:
            return DataPacket(data, int_to_bytes(self._block_data_id)).__bytes__()

    def send(self, addr):
        self.set_result(None)
        if self._last:
            if self._send_task:
                self._send_task.cancel()
                self._send_task = None
            self._stream.feed_eof()
            self._transport.close()
            return
        if self._send_task is None:
            self._send_task = asyncio.create_task(self._send(addr))

    async def _send(self, addr):
        while not self._last:
            print(self._block_data_id)
            if self._block_data_id != 0:
                data = await self._get_data()
                if data is None:
                    break
                if len(data) < self._stream.blk_size:
                    self._last = True
            else:
                data = ReqAckPacket(blk_size=self._stream.blk_size, t_size=self._stream.t_size).__bytes__()
            self.update_block_id()
            while 1:
                self._waiter = asyncio.Future()
                try:
                    print("try")
                    self._transport.sendto(data, addr)
                    await asyncio.wait_for(self._waiter, 10)
                    break
                except Exception as e:
                    print(traceback.format_exc())
                finally:
                    del self._waiter

    def error_received(self, exc):
        self._stream.set_exception(exc)
        self._transport.close()
        self._last = True
        self._send_task.cancel()
