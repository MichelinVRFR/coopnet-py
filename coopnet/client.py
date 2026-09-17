"""
High-level async client for the CoopNet signaling protocol.
"""

from __future__ import annotations

import asyncio
import struct
import logging
from typing import Callable, Optional, Dict, Any, List

from .protocol import Packet, PacketType, PROTOCOL_VERSION, ErrorCode

log = logging.getLogger("coopnet.client")


class CoopNetClient:
    """
    Async client that speaks the same binary protocol as the original C++ library.
    """

    def __init__(self) -> None:
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.user_id: int = 0
        self.connected: bool = False
        self._running: bool = False
        self._recv_task: Optional[asyncio.Task] = None

        # Event callbacks – same names as the original C API where possible
        self._callbacks: Dict[str, Callable] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on(self, event: str, callback: Callable) -> None:
        """Register a callback for an event.

        Supported events:
            connected(user_id)
            disconnected(intentional: bool)
            lobby_created(lobby_id, game, version, hostname, mode, max_conn)
            lobby_joined(lobby_id, user_id, owner_id, dest_id)
            lobby_left(lobby_id, user_id)
            lobby_list_got(lobby_id, owner_id, players, max_players,
                           game, version, hostname, mode, description)
            lobby_list_finish()
            peer_sdp(lobby_id, from_user_id, sdp: str)
            peer_candidate(lobby_id, from_user_id, candidate: str)
            peer_candidate_done(lobby_id, from_user_id)
            error(error_code, tag)
            receive(from_user_id, data: bytes)   # after P2P is up (future)
        """
        self._callbacks[event] = callback

    async def connect(
        self,
        host: str,
        port: int = 34197,
        name: str = "player",
        dest_id: int = 0,
    ) -> None:
        if self.connected:
            raise RuntimeError("already connected")

        self.reader, self.writer = await asyncio.open_connection(host, port)
        self._running = True
        self._recv_task = asyncio.create_task(self._recv_loop())

        # Wait until we receive the JOINED packet (or timeout)
        for _ in range(50):
            if self.user_id:
                break
            await asyncio.sleep(0.05)
        if not self.user_id:
            await self.disconnect()
            raise TimeoutError("did not receive JOINED packet")

        # Send INFO so the server knows our name / dest_id
        await self.send_info(dest_id, name)
        self.connected = True
        log.info("connected as %016x", self.user_id)

    async def disconnect(self) -> None:
        self._running = False
        self.connected = False
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass
        self.writer = None
        self.reader = None
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        cb = self._callbacks.get("disconnected")
        if cb:
            cb(True)

    async def lobby_create(
        self,
        game: str,
        version: str = "1.0",
        hostname: str = "Host",
        mode: str = "normal",
        max_connections: int = 8,
        password: str = "",
        description: str = "",
    ) -> None:
        data = struct.pack("<H", max_connections)
        await self._send(
            Packet(
                PacketType.LOBBY_CREATE,
                data,
                [game, version, hostname, mode, password, description],
            )
        )

    async def lobby_join(self, lobby_id: int, password: str = "") -> None:
        data = struct.pack("<Q", lobby_id)
        await self._send(Packet(PacketType.LOBBY_JOIN, data, [password]))

    async def lobby_leave(self, lobby_id: int) -> None:
        data = struct.pack("<Q", lobby_id)
        await self._send(Packet(PacketType.LOBBY_LEAVE, data))

    async def lobby_list(self, game: str = "", password: str = "") -> None:
        await self._send(Packet(PacketType.LOBBY_LIST_GET, b"", [game, password]))

    async def send_sdp(self, lobby_id: int, target_user_id: int, sdp: str) -> None:
        data = struct.pack("<QQ", lobby_id, target_user_id)
        await self._send(Packet(PacketType.PEER_SDP, data, [sdp]))

    async def send_candidate(
        self, lobby_id: int, target_user_id: int, candidate: str
    ) -> None:
        data = struct.pack("<QQ", lobby_id, target_user_id)
        await self._send(Packet(PacketType.PEER_CANDIDATE, data, [candidate]))

    async def send_candidate_done(self, lobby_id: int, target_user_id: int) -> None:
        data = struct.pack("<QQ", lobby_id, target_user_id)
        await self._send(Packet(PacketType.PEER_CANDIDATE_DONE, data))

    async def send_info(self, dest_id: int, name: str, info_bits: int = 0) -> None:
        # Original packs destId + infoBits + hash; we send a simplified version
        data = struct.pack("<QQ", dest_id, info_bits)
        await self._send(Packet(PacketType.INFO, data, [name]))

    async def keep_alive(self) -> None:
        await self._send(Packet(PacketType.KEEP_ALIVE, b"\x00"))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _send(self, pkt: Packet) -> None:
        if not self.writer or self.writer.is_closing():
            return
        self.writer.write(pkt.encode())
        await self.writer.drain()

    async def _recv_loop(self) -> None:
        assert self.reader is not None
        try:
            while self._running:
                header = await self.reader.readexactly(6)
                _, data_size, string_size = struct.unpack("<HHH", header)
                body = await self.reader.readexactly(data_size + string_size)
                pkt = Packet.decode(header + body)
                await self._handle(pkt)
        except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError, OSError) as e:
            log.debug("recv loop ended: %s", e)
        finally:
            was_connected = self.connected
            self.connected = False
            self._running = False
            if was_connected:
                cb = self._callbacks.get("disconnected")
                if cb:
                    cb(False)

    async def _handle(self, pkt: Packet) -> None:
        if pkt.type == PacketType.JOINED:
            if len(pkt.data) >= 12:
                self.user_id, version = struct.unpack_from("<QI", pkt.data)
                log.debug("JOINED user_id=%016x protocol=%d", self.user_id, version)
                cb = self._callbacks.get("connected")
                if cb:
                    cb(self.user_id)

        elif pkt.type == PacketType.LOBBY_CREATED:
            if len(pkt.data) >= 16:
                lobby_id, max_conn = struct.unpack_from("<QQ", pkt.data)
                strings = (pkt.strings + [""] * 4)[:4]
                game, version, hostname, mode = strings
                cb = self._callbacks.get("lobby_created")
                if cb:
                    cb(lobby_id, game, version, hostname, mode, max_conn)

        elif pkt.type == PacketType.LOBBY_JOINED:
            if len(pkt.data) >= 32:
                lobby_id, user_id, owner_id, dest_id, _prio = struct.unpack_from(
                    "<QQQQI", pkt.data
                )
                cb = self._callbacks.get("lobby_joined")
                if cb:
                    cb(lobby_id, user_id, owner_id, dest_id)

        elif pkt.type == PacketType.LOBBY_LEFT:
            if len(pkt.data) >= 16:
                lobby_id, user_id = struct.unpack_from("<QQ", pkt.data)
                cb = self._callbacks.get("lobby_left")
                if cb:
                    cb(lobby_id, user_id)

        elif pkt.type == PacketType.LOBBY_LIST_GOT:
            if len(pkt.data) >= 20:
                lobby_id, owner_id, players, max_players = struct.unpack_from(
                    "<QQHH", pkt.data
                )
                strings = (pkt.strings + [""] * 5)[:5]
                game, version, hostname, mode, description = strings
                cb = self._callbacks.get("lobby_list_got")
                if cb:
                    cb(
                        lobby_id,
                        owner_id,
                        players,
                        max_players,
                        game,
                        version,
                        hostname,
                        mode,
                        description,
                    )

        elif pkt.type == PacketType.LOBBY_LIST_FINISH:
            cb = self._callbacks.get("lobby_list_finish")
            if cb:
                cb()

        elif pkt.type == PacketType.PEER_SDP:
            if len(pkt.data) >= 16 and pkt.strings:
                lobby_id, from_id = struct.unpack_from("<QQ", pkt.data)
                sdp = pkt.strings[0]
                cb = self._callbacks.get("peer_sdp")
                if cb:
                    cb(lobby_id, from_id, sdp)

        elif pkt.type == PacketType.PEER_CANDIDATE:
            if len(pkt.data) >= 16 and pkt.strings:
                lobby_id, from_id = struct.unpack_from("<QQ", pkt.data)
                candidate = pkt.strings[0]
                cb = self._callbacks.get("peer_candidate")
                if cb:
                    cb(lobby_id, from_id, candidate)

        elif pkt.type == PacketType.PEER_CANDIDATE_DONE:
            if len(pkt.data) >= 16:
                lobby_id, from_id = struct.unpack_from("<QQ", pkt.data)
                cb = self._callbacks.get("peer_candidate_done")
                if cb:
                    cb(lobby_id, from_id)

        elif pkt.type == PacketType.ERROR:
            if len(pkt.data) >= 10:
                err_num, tag = struct.unpack_from("<HQ", pkt.data)
                try:
                    err = ErrorCode(err_num)
                except ValueError:
                    err = ErrorCode.NONE
                cb = self._callbacks.get("error")
                if cb:
                    cb(err, tag)
                else:
                    log.warning("server error %s (tag=%d)", err.name, tag)

        elif pkt.type == PacketType.LOAD_BALANCE:
            # host string + port
            if pkt.strings and len(pkt.data) >= 4:
                port = struct.unpack_from("<I", pkt.data)[0]
                host = pkt.strings[0]
                log.info("load-balance redirect → %s:%d", host, port)
                # caller can decide to reconnect
