"""
Asyncio signaling + lobby server.
Compatible with the original C++ coopnet clients.

Includes STUN/TURN advertisement:
- Default STUN: stun.l.google.com:19302
- Separate STUN for Radmin VPN clients (IP starting with 26.): stun.cloudflare.com:3478
- Optional TURN servers loaded from turn-servers.cfg
"""

from __future__ import annotations

import asyncio
import struct
import random
import logging
import os
from pathlib import Path
from typing import Dict, Optional, Set, List, Tuple
from dataclasses import dataclass, field

from .protocol import Packet, PacketType, PROTOCOL_VERSION, ErrorCode

log = logging.getLogger("coopnet.server")


# ---------------------------------------------------------------------------
# STUN / TURN configuration
# ---------------------------------------------------------------------------

@dataclass
class StunTurnServer:
    host: str
    port: int
    username: str = ""
    password: str = ""
    is_stun: bool = True  # True = STUN, False = TURN


# Default public STUN (same as original C++ coopnet)
DEFAULT_STUN = StunTurnServer(
    host="stun.l.google.com",
    port=19302,
    is_stun=True,
)

# Alternative STUN used for Radmin VPN clients (26.0.0.0/8)
RADMIN_STUN = StunTurnServer(
    host="stun.cloudflare.com",
    port=3478,
    is_stun=True,
)


def is_radmin_ip(ip: str) -> bool:
    """Return True if the IP belongs to Radmin VPN (26.0.0.0/8)."""
    return ip.startswith("26.")


def load_turn_servers(cfg_path: str = "turn-servers.cfg") -> List[StunTurnServer]:
    """
    Load TURN servers from a config file.
    Format (same as original):
        host:username:password:port
    Lines starting with # are comments.
    """
    servers: List[StunTurnServer] = []
    path = Path(cfg_path)
    if not path.is_file():
        log.info("No %s found – running without TURN servers", cfg_path)
        return servers

    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(":")
            if len(parts) != 4:
                log.warning("Invalid TURN line %d in %s: %r", line_no, cfg_path, line)
                continue
            host, username, password, port_str = parts
            try:
                port = int(port_str)
            except ValueError:
                log.warning("Invalid port on line %d in %s", line_no, cfg_path)
                continue
            servers.append(
                StunTurnServer(
                    host=host,
                    port=port,
                    username=username,
                    password=password,
                    is_stun=False,
                )
            )
            log.info("Loaded TURN server: %s:%d", host, port)

    return servers


# ---------------------------------------------------------------------------
# Lobby
# ---------------------------------------------------------------------------

@dataclass
class Lobby:
    id: int
    owner_id: int
    game: str
    version: str
    hostname: str
    mode: str
    description: str
    password: str
    max_connections: int
    members: Set[int] = field(default_factory=set)

    @property
    def player_count(self) -> int:
        return len(self.members)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class CoopNetServer:
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 34197,
        turn_cfg: str = "turn-servers.cfg",
    ):
        self.host = host
        self.port = port
        self.connections: Dict[int, asyncio.StreamWriter] = {}
        self.user_info: Dict[int, dict] = {}
        self.lobbies: Dict[int, Lobby] = {}
        self.turn_servers: List[StunTurnServer] = load_turn_servers(turn_cfg)
        self._server: Optional[asyncio.Server] = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _gen_id(self) -> int:
        while True:
            i = random.getrandbits(64) or 1
            if i not in self.connections and i not in self.lobbies:
                return i

    async def send(self, user_id: int, pkt: Packet) -> None:
        writer = self.connections.get(user_id)
        if writer is None or writer.is_closing():
            return
        try:
            writer.write(pkt.encode())
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError, OSError):
            await self.disconnect(user_id)

    async def broadcast_lobby(
        self, lobby_id: int, pkt: Packet, exclude: Optional[int] = None
    ) -> None:
        lobby = self.lobbies.get(lobby_id)
        if not lobby:
            return
        for uid in list(lobby.members):
            if uid != exclude:
                await self.send(uid, pkt)

    async def send_error(self, user_id: int, err: ErrorCode, tag: int = 0) -> None:
        data = struct.pack("<HQ", int(err), tag)
        await self.send(user_id, Packet(PacketType.ERROR, data))

    # ------------------------------------------------------------------
    # STUN / TURN advertisement
    # ------------------------------------------------------------------

    async def send_stun_turn(self, user_id: int, peer_ip: str) -> None:
        """
        Send STUN (and any configured TURN) servers to the client.
        Uses a different STUN server for Radmin VPN clients (26.x.x.x).
        """
        # Choose STUN based on client IP
        if is_radmin_ip(peer_ip):
            stun = RADMIN_STUN
            log.info(
                "Client %016x is Radmin VPN (%s) → using STUN %s:%d",
                user_id, peer_ip, stun.host, stun.port,
            )
        else:
            stun = DEFAULT_STUN
            log.debug(
                "Client %016x (%s) → using default STUN %s:%d",
                user_id, peer_ip, stun.host, stun.port,
            )

        # Packet format (matches original MPacketStunTurn):
        #   data: uint8 isStun + uint16 port
        #   strings: [host, username, password]
        async def _send_one(server: StunTurnServer) -> None:
            data = struct.pack("<BH", 1 if server.is_stun else 0, server.port)
            await self.send(
                user_id,
                Packet(
                    PacketType.STUN_TURN,
                    data,
                    [server.host, server.username, server.password],
                ),
            )

        # Always send the chosen STUN first
        await _send_one(stun)

        # Then any configured TURN servers (shuffled like the original)
        turns = list(self.turn_servers)
        random.shuffle(turns)
        for turn in turns:
            await _send_one(turn)

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        user_id = self._gen_id()
        self.connections[user_id] = writer

        peername = writer.get_extra_info("peername")
        peer_ip = peername[0] if peername else "0.0.0.0"

        self.user_info[user_id] = {
            "name": "",
            "dest_id": 0,
            "lobby": None,
            "ip": peer_ip,
        }

        log.info("connected %016x from %s", user_id, peername)

        # 1. Send JOINED
        joined_data = struct.pack("<QI", user_id, PROTOCOL_VERSION)
        await self.send(user_id, Packet(PacketType.JOINED, joined_data))

        # 2. Send STUN / TURN configuration (important for ICE)
        await self.send_stun_turn(user_id, peer_ip)

        try:
            while True:
                header = await reader.readexactly(6)
                _, data_size, string_size = struct.unpack("<HHH", header)
                body = await reader.readexactly(data_size + string_size)
                pkt = Packet.decode(header + body)
                await self.dispatch(user_id, pkt)
        except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            await self.disconnect(user_id)

    async def disconnect(self, user_id: int) -> None:
        info = self.user_info.pop(user_id, None)
        writer = self.connections.pop(user_id, None)
        if writer is not None:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

        if info and info.get("lobby") is not None:
            await self.leave_lobby(user_id, info["lobby"])

        log.info("disconnected %016x", user_id)

    # ------------------------------------------------------------------
    # Packet dispatch
    # ------------------------------------------------------------------

    async def dispatch(self, user_id: int, pkt: Packet) -> None:
        handlers = {
            PacketType.LOBBY_CREATE: self._on_lobby_create,
            PacketType.LOBBY_UPDATE: self._on_lobby_update,
            PacketType.LOBBY_JOIN: self._on_lobby_join,
            PacketType.LOBBY_LEAVE: self._on_lobby_leave,
            PacketType.LOBBY_LIST_GET: self._on_lobby_list_get,
            PacketType.PEER_SDP: self._on_peer_relay,
            PacketType.PEER_CANDIDATE: self._on_peer_relay,
            PacketType.PEER_CANDIDATE_DONE: self._on_peer_relay,
            PacketType.PEER_FAILED: self._on_peer_failed,
            PacketType.KEEP_ALIVE: self._on_keep_alive,
            PacketType.INFO: self._on_info,
        }
        handler = handlers.get(pkt.type)
        if handler:
            await handler(user_id, pkt)
        else:
            log.debug("unhandled packet %s from %016x", pkt.type.name, user_id)

    async def _on_lobby_create(self, user_id: int, pkt: Packet) -> None:
        max_conn = 16
        if len(pkt.data) >= 2:
            max_conn = struct.unpack_from("<H", pkt.data)[0]
        strings = (pkt.strings + [""] * 6)[:6]
        game, version, hostname, mode, password, description = strings
        await self.create_lobby(
            user_id, game, version, hostname, mode, max_conn, password, description
        )

    async def _on_lobby_update(self, user_id: int, pkt: Packet) -> None:
        if len(pkt.data) < 8:
            return
        lobby_id = struct.unpack_from("<Q", pkt.data)[0]
        strings = (pkt.strings + [""] * 5)[:5]
        game, version, hostname, mode, description = strings
        await self.update_lobby(user_id, lobby_id, game, version, hostname, mode, description)

    async def _on_lobby_join(self, user_id: int, pkt: Packet) -> None:
        if len(pkt.data) < 8:
            return
        lobby_id = struct.unpack_from("<Q", pkt.data)[0]
        password = pkt.strings[0] if pkt.strings else ""
        await self.join_lobby(user_id, lobby_id, password)

    async def _on_lobby_leave(self, user_id: int, pkt: Packet) -> None:
        if len(pkt.data) < 8:
            return
        lobby_id = struct.unpack_from("<Q", pkt.data)[0]
        await self.leave_lobby(user_id, lobby_id)

    async def _on_lobby_list_get(self, user_id: int, pkt: Packet) -> None:
        game = pkt.strings[0] if pkt.strings else ""
        password = pkt.strings[1] if len(pkt.strings) > 1 else ""
        await self.list_lobbies(user_id, game, password)

    async def _on_peer_relay(self, user_id: int, pkt: Packet) -> None:
        if len(pkt.data) < 16:
            return
        lobby_id, target_id = struct.unpack_from("<QQ", pkt.data)
        await self.relay_peer_msg(user_id, lobby_id, target_id, pkt)

    async def _on_peer_failed(self, user_id: int, pkt: Packet) -> None:
        if len(pkt.data) >= 16:
            lobby_id, peer_id = struct.unpack_from("<QQ", pkt.data)
            log.info("peer failed: %016x -> %016x (lobby %016x)", user_id, peer_id, lobby_id)

    async def _on_keep_alive(self, user_id: int, pkt: Packet) -> None:
        pass

    async def _on_info(self, user_id: int, pkt: Packet) -> None:
        if len(pkt.data) < 16:
            return
        dest_id, info_bits = struct.unpack_from("<QQ", pkt.data)
        name = pkt.strings[0] if pkt.strings else ""
        self.user_info[user_id]["dest_id"] = dest_id
        self.user_info[user_id]["name"] = name
        log.debug("info from %016x: dest=%016x name=%r", user_id, dest_id, name)

    # ------------------------------------------------------------------
    # Lobby operations
    # ------------------------------------------------------------------

    async def create_lobby(
        self,
        owner_id: int,
        game: str,
        version: str,
        hostname: str,
        mode: str,
        max_conn: int,
        password: str,
        description: str,
    ) -> None:
        old = self.user_info[owner_id].get("lobby")
        if old is not None:
            await self.leave_lobby(owner_id, old)

        lobby_id = self._gen_id()
        lobby = Lobby(
            id=lobby_id,
            owner_id=owner_id,
            game=game,
            version=version,
            hostname=hostname,
            mode=mode,
            description=description,
            password=password,
            max_connections=max(1, min(max_conn, 32)),
        )
        lobby.members.add(owner_id)
        self.lobbies[lobby_id] = lobby
        self.user_info[owner_id]["lobby"] = lobby_id

        data = struct.pack("<QQ", lobby_id, lobby.max_connections)
        await self.send(
            owner_id,
            Packet(
                PacketType.LOBBY_CREATED,
                data,
                [game, version, hostname, mode],
            ),
        )
        log.info(
            "lobby created %016x by %016x (%s / %s)",
            lobby_id, owner_id, game, mode,
        )

    async def update_lobby(
        self,
        user_id: int,
        lobby_id: int,
        game: str,
        version: str,
        hostname: str,
        mode: str,
        description: str,
    ) -> None:
        lobby = self.lobbies.get(lobby_id)
        if not lobby or lobby.owner_id != user_id:
            return
        lobby.game = game
        lobby.version = version
        lobby.hostname = hostname
        lobby.mode = mode
        lobby.description = description
        log.info("lobby updated %016x", lobby_id)

    async def join_lobby(self, user_id: int, lobby_id: int, password: str) -> None:
        lobby = self.lobbies.get(lobby_id)
        if lobby is None:
            await self.send_error(user_id, ErrorCode.LOBBY_NOT_FOUND)
            return
        if lobby.password and lobby.password != password:
            await self.send_error(user_id, ErrorCode.LOBBY_PASSWORD_INCORRECT)
            return
        if len(lobby.members) >= lobby.max_connections:
            await self.send_error(user_id, ErrorCode.LOBBY_JOIN_FULL)
            return

        old = self.user_info[user_id].get("lobby")
        if old is not None and old != lobby_id:
            await self.leave_lobby(user_id, old)

        lobby.members.add(user_id)
        self.user_info[user_id]["lobby"] = lobby_id

        data = struct.pack(
            "<QQQQI",
            lobby_id,
            user_id,
            lobby.owner_id,
            self.user_info[user_id].get("dest_id", 0),
            0,
        )
        await self.broadcast_lobby(lobby_id, Packet(PacketType.LOBBY_JOINED, data))
        log.info("user %016x joined lobby %016x", user_id, lobby_id)

    async def leave_lobby(self, user_id: int, lobby_id: int) -> None:
        lobby = self.lobbies.get(lobby_id)
        if lobby is None or user_id not in lobby.members:
            return

        lobby.members.discard(user_id)
        if self.user_info.get(user_id):
            self.user_info[user_id]["lobby"] = None

        data = struct.pack("<QQ", lobby_id, user_id)
        await self.broadcast_lobby(lobby_id, Packet(PacketType.LOBBY_LEFT, data))

        if not lobby.members:
            del self.lobbies[lobby_id]
            log.info("lobby destroyed %016x", lobby_id)
        else:
            if lobby.owner_id == user_id:
                lobby.owner_id = next(iter(lobby.members))
                log.info("lobby %016x ownership transferred to %016x", lobby_id, lobby.owner_id)

    async def list_lobbies(self, user_id: int, game_filter: str, password: str) -> None:
        for lobby in list(self.lobbies.values()):
            if game_filter and lobby.game != game_filter:
                continue
            if lobby.password and lobby.password != password:
                continue

            data = struct.pack(
                "<QQHH",
                lobby.id,
                lobby.owner_id,
                lobby.player_count,
                lobby.max_connections,
            )
            await self.send(
                user_id,
                Packet(
                    PacketType.LOBBY_LIST_GOT,
                    data,
                    [
                        lobby.game,
                        lobby.version,
                        lobby.hostname,
                        lobby.mode,
                        lobby.description,
                    ],
                ),
            )
        await self.send(user_id, Packet(PacketType.LOBBY_LIST_FINISH, b"\x00"))

    async def relay_peer_msg(
        self, from_id: int, lobby_id: int, target_id: int, pkt: Packet
    ) -> None:
        lobby = self.lobbies.get(lobby_id)
        if (
            lobby is None
            or from_id not in lobby.members
            or target_id not in lobby.members
        ):
            return
        await self.send(target_id, pkt)

    # ------------------------------------------------------------------
    # Stats / run
    # ------------------------------------------------------------------

    @property
    def player_count(self) -> int:
        return len(self.connections)

    @property
    def lobby_count(self) -> int:
        return len(self.lobbies)

    async def run(self) -> None:
        self._server = await asyncio.start_server(
            self.handle_client, self.host, self.port
        )
        addrs = ", ".join(str(s.getsockname()) for s in self._server.sockets or [])
        log.info("CoopNet Python server listening on %s", addrs)
        log.info("Default STUN : %s:%d", DEFAULT_STUN.host, DEFAULT_STUN.port)
        log.info("Radmin STUN  : %s:%d (for 26.x.x.x clients)", RADMIN_STUN.host, RADMIN_STUN.port)
        if self.turn_servers:
            log.info("TURN servers : %d loaded", len(self.turn_servers))
        else:
            log.info("TURN servers : none (create turn-servers.cfg to add some)")
        async with self._server:
            await self._server.serve_forever()


def main() -> None:
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="CoopNet signaling server (Python)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=34197)
    parser.add_argument(
        "--turn-cfg",
        default="turn-servers.cfg",
        help="Path to TURN servers config file (default: turn-servers.cfg)",
    )
    args = parser.parse_args()

    server = CoopNetServer(host=args.host, port=args.port, turn_cfg=args.turn_cfg)
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        log.info("shutting down")


if __name__ == "__main__":
    main()
