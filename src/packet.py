# *****************************
# tftp协议内容参考自：https://blog.csdn.net/weixin_43996145/article/details/134265843
# *****************************

import enum
import struct

from typing import List


def int_to_bytes(num: int) -> bytes:
    return struct.pack("!H", num)


def bytes_to_int(buf: bytes) -> int:
    return struct.unpack("!H", buf)[0]


class OperateCode(enum.Enum):
    READ = int_to_bytes(1)
    WRITE = int_to_bytes(2)
    DATA = int_to_bytes(3)
    ACK = int_to_bytes(4)
    ERROR = int_to_bytes(5)
    REQ_ACK = int_to_bytes(6)


class Mode(enum.Enum):
    NET_ASCII = b"netascii"
    OCTET = b"octet"
    MAIL = b"mail"  # 已经弃用


class ErrorCode(enum.Enum):
    FILE_NOT_FOUND = int_to_bytes(1)  # 文件未找到
    ACCESS_VIOLATION = int_to_bytes(2)  # 访问违规
    DISK_FULL_OR_ALLOCATION_EXCEEDED = int_to_bytes(3)  # 磁盘不足
    ILLEGAL_TFTP_OPERATION = int_to_bytes(4)  # 非法tftp操作吗码
    UNKNOWN_TRANSFER_ID = int_to_bytes(5)  # 未知传输标识
    FILE_ALREADY_EXIST = int_to_bytes(6)  # 文件已经存在
    NO_SUCH_USER = int_to_bytes(7)  # 无该用户


class Packet:

    @classmethod
    def from_buffer(cls, buffer):
        raise NotImplementedError


class RequestPacket(Packet):
    """读写报文"""

    def __init__(self, operate_code: OperateCode, file_name: bytes, mode: Mode, options: List[bytes]):
        """
        :param operate_code:
        :param file_name:
        :param mode:
        :param options: 由于工作中只用到了blksize和tsize，目前只实现了这两个
        """
        self.operate_code = operate_code
        self.file_name = file_name
        self.mode = mode
        self.options = options

    def __bytes__(self):
        return b"".join((self.operate_code.value, self.file_name, b"\x00", self.mode.value, b"\x00", *self.options))

    @classmethod
    def from_buffer(cls, buffer: bytes):
        filename, mode, *options, _ = buffer[2:].split(b"\x00")
        return cls(OperateCode(buffer[:2]), filename, mode, options)

    @property
    def tsize(self) -> int:
        ind = self.options.index(b"tsize")
        return int(self.options[ind + 1])

    @property
    def blksize(self) -> int:
        if b"blksize" in self.options:
            ind = self.options.index(b"blksize")
            print("blksize", self.options[ind + 1])
            return int(self.options[ind + 1])
        return 512


class DataPacket(Packet):

    def __init__(self, data: bytes, block_id: bytes):
        self.data = data
        self.block_id = block_id
        self.operate_code = OperateCode.DATA

    @property
    def block_data_id(self) -> int:
        return bytes_to_int(self.block_id)

    def __bytes__(self):
        return b"".join((self.operate_code.value, self.block_id, self.data))

    @classmethod
    def from_buffer(cls, buffer: bytes):
        if OperateCode(buffer[:2]) != OperateCode.DATA:
            raise TypeError("Invalid operate code in DATA")
        return cls(
            block_id=buffer[2:4],
            data=buffer[4:],
        )


class AckPacket(Packet):

    def __init__(self, block_id: int):
        self.block_id = block_id
        self.operate_code = OperateCode.ACK

    def __bytes__(self):
        return b"".join((self.operate_code.value, int_to_bytes(self.block_id)))

    @classmethod
    def from_buffer(cls, buffer: bytes):
        if OperateCode(buffer[:2]) != OperateCode.ACK:
            raise TypeError("Invalid operate code in ACK")
        return cls(block_id=bytes_to_int(buffer[2:4]))


class ErrorPacket(Packet):

    def __init__(self, error_code: ErrorCode, error_message: bytes):
        self.error_code = error_code
        self.error_message = error_message
        self.operate_code = OperateCode.ERROR

    def __bytes__(self):
        return b"".join((self.operate_code.value, self.error_code.value, self.error_message, b"\x00"))

    @classmethod
    def from_buffer(cls, buffer: bytes):
        if OperateCode(buffer[:2]) != OperateCode.ERROR:
            raise TypeError("Invalid operate code in ERROR")
        return cls(
            error_code=ErrorCode(buffer[2:4]),
            error_message=buffer[4:],
        )

    def format_error_msg(self) -> str:
        *msg, _ = self.error_message.split(b"\x00")
        return b"".join(msg).decode(errors="ignore")


class ReqAckPacket(Packet):

    def __init__(self, blk_size: int, t_size: int):
        self.blk_size = blk_size
        self.t_size = t_size
        self.operate_code = OperateCode.REQ_ACK

    def __bytes__(self):
        return b"".join((
            self.operate_code.value,
            "blksize".encode("ascii"), b"\x00", str(self.blk_size).encode("ascii"), b"\x00",
            "tsize".encode("ascii"), b"\x00", str(self.t_size).encode("ascii"), b"\x00"
        ))

    @classmethod
    def from_buffer(cls, buffer: bytes):
        if OperateCode(buffer[:2]) != OperateCode.REQ_ACK:
            raise TypeError("Invalid operate code in REQ_ACK")
        *options, _ = buffer[2:].split(b"\x00")
        if b"blksize" in options:
            blk_size = int(options[options.index(b"blksize") + 1])
        else:
            blk_size = 512
        t_size = int(options[options.index(b"tsize") + 1])
        return cls(
            blk_size=blk_size,
            t_size=t_size
        )


PACKET_CLASS_MAP = {
    OperateCode.READ: RequestPacket,
    OperateCode.WRITE: RequestPacket,
    OperateCode.DATA: DataPacket,
    OperateCode.ACK: AckPacket,
    OperateCode.ERROR: ErrorPacket,
    OperateCode.REQ_ACK: ReqAckPacket,
}


def create_packet_from_buffer(buffer: bytes):
    packet_class = PACKET_CLASS_MAP.get(OperateCode(buffer[:2]))
    if packet_class is None:
        raise TypeError("Invalid packet type")
    return packet_class.from_buffer(buffer)
