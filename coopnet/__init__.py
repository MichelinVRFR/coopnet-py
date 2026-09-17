"""
coopnet – Python signaling server & client for ICE/P2P lobbies.
Compatible with the original C++ coopnet protocol (libjuice).
"""

__version__ = "0.1.0"

from .protocol import Packet, PacketType, PROTOCOL_VERSION
from .server import CoopNetServer
from .client import CoopNetClient

__all__ = [
    "Packet",
    "PacketType",
    "PROTOCOL_VERSION",
    "CoopNetServer",
    "CoopNetClient",
]
