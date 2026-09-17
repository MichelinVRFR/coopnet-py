"""
Binary packet protocol – faithful recreation of the original C++ MPacket system.
"""

from __future__ import annotations

from enum import IntEnum
from dataclasses import dataclass, field
from typing import List
import struct

PROTOCOL_VERSION = 4
MAX_PACKET_SIZE = 5100

HEADER_FMT = "<HHH"  # packetType, dataSize, stringSize
HEADER_SIZE = struct.calcsize(HEADER_FMT)


class PacketType(IntEnum):
    NONE = 0
    JOINED = 1
    LOBBY_CREATE = 2
    LOBBY_CREATED = 3
    LOBBY_UPDATE = 4
    LOBBY_JOIN = 5
    LOBBY_JOINED = 6
    LOBBY_LEAVE = 7
    LOBBY_LEFT = 8
    LOBBY_LIST_GET = 9
    LOBBY_LIST_GOT = 10
    LOBBY_LIST_FINISH = 11
    PEER_SDP = 12
    PEER_CANDIDATE = 13
    PEER_CANDIDATE_DONE = 14
    PEER_FAILED = 15
    STUN_TURN = 16
    ERROR = 17
    KEEP_ALIVE = 18
    INFO = 19
    LOAD_BALANCE = 20


# Error codes matching the original enum MPacketErrorNumber
class ErrorCode(IntEnum):
    NONE = 0
    LOBBY_NOT_FOUND = 1
    LOBBY_JOIN_FULL = 2
    LOBBY_JOIN_FAILED = 3
    LOBBY_PASSWORD_INCORRECT = 4
    COOPNET_VERSION = 5
    PEER_FAILED = 6


@dataclass
class Packet:
    type: PacketType
    data: bytes = b""
    strings: List[str] = field(default_factory=list)

    def encode(self) -> bytes:
        str_blob = b""
        for s in self.strings:
            encoded = s.encode("utf-8")
            if len(encoded) >= 0xFFFF:
                raise ValueError(f"string too long ({len(encoded)} bytes)")
            str_blob += struct.pack("<H", len(encoded)) + encoded

        data_size = len(self.data)
        string_size = len(str_blob)
        total = HEADER_SIZE + data_size + string_size
        if total > MAX_PACKET_SIZE:
            raise ValueError(f"packet too large ({total} > {MAX_PACKET_SIZE})")

        header = struct.pack(HEADER_FMT, int(self.type), data_size, string_size)
        return header + self.data + str_blob

    @classmethod
    def decode(cls, buf: bytes) -> "Packet":
        if len(buf) < HEADER_SIZE:
            raise ValueError("short header")
        ptype, data_size, string_size = struct.unpack(HEADER_FMT, buf[:HEADER_SIZE])
        total = HEADER_SIZE + data_size + string_size
        if len(buf) < total:
            raise ValueError("incomplete packet")

        data = buf[HEADER_SIZE : HEADER_SIZE + data_size]
        strings: List[str] = []
        offset = HEADER_SIZE + data_size
        end = offset + string_size
        while offset + 2 <= end:
            slen = struct.unpack_from("<H", buf, offset)[0]
            offset += 2
            if offset + slen > end:
                break
            strings.append(buf[offset : offset + slen].decode("utf-8", errors="replace"))
            offset += slen

        try:
            ptype_enum = PacketType(ptype)
        except ValueError:
            ptype_enum = PacketType.NONE

        return cls(ptype_enum, data, strings)

    def __repr__(self) -> str:
        return f"Packet({self.type.name}, data={len(self.data)}B, strings={self.strings})"
