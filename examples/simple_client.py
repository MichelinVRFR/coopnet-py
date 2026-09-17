#!/usr/bin/env python3
"""
Minimal interactive client demo.

Usage:
    python examples/simple_client.py [host] [port]
"""

import asyncio
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coopnet import CoopNetClient, ErrorCode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("demo")


async def main(host: str = "127.0.0.1", port: int = 34197) -> None:
    client = CoopNetClient()

    def on_connected(user_id: int):
        log.info("Connected! My user id = %016x", user_id)

    def on_lobby_created(lobby_id, game, version, hostname, mode, max_conn):
        log.info(
            "Lobby created: %016x  game=%s  mode=%s  max=%d",
            lobby_id, game, mode, max_conn,
        )

    def on_lobby_joined(lobby_id, user_id, owner_id, dest_id):
        log.info(
            "User %016x joined lobby %016x (owner %016x)",
            user_id, lobby_id, owner_id,
        )

    def on_lobby_left(lobby_id, user_id):
        log.info("User %016x left lobby %016x", user_id, lobby_id)

    def on_list_got(lobby_id, owner_id, players, max_p, game, ver, hostn, mode, desc):
        log.info(
            "  [%016x] %s/%s  %d/%d  host=%s  mode=%s  %s",
            lobby_id, game, ver, players, max_p, hostn, mode, desc,
        )

    def on_list_finish():
        log.info("--- end of lobby list ---")

    def on_error(err: ErrorCode, tag: int):
        log.error("Server error: %s (tag=%d)", err.name, tag)

    def on_disconnected(intentional: bool):
        log.info("Disconnected (intentional=%s)", intentional)

    client.on("connected", on_connected)
    client.on("lobby_created", on_lobby_created)
    client.on("lobby_joined", on_lobby_joined)
    client.on("lobby_left", on_lobby_left)
    client.on("lobby_list_got", on_list_got)
    client.on("lobby_list_finish", on_list_finish)
    client.on("error", on_error)
    client.on("disconnected", on_disconnected)

    log.info("Connecting to %s:%d ...", host, port)
    await client.connect(host, port, name="PythonDemo")

    # Demo sequence
    await client.lobby_list()
    await asyncio.sleep(0.5)

    await client.lobby_create(
        game="sm64",
        version="1.0",
        hostname="PythonHost",
        mode="normal",
        max_connections=8,
        description="Created by the Python port",
    )
    await asyncio.sleep(1.0)

    await client.lobby_list()
    await asyncio.sleep(0.5)

    log.info("Demo finished – press Ctrl+C to quit or wait 30s")
    try:
        await asyncio.sleep(30)
    except asyncio.CancelledError:
        pass
    finally:
        await client.disconnect()


if __name__ == "__main__":
    h = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    p = int(sys.argv[2]) if len(sys.argv) > 2 else 34197
    try:
        asyncio.run(main(h, p))
    except KeyboardInterrupt:
        print("\nbye")
