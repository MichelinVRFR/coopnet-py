# coopnet-py

Python reimplementation of [coop-deluxe/coopnet](https://github.com/coop-deluxe/coopnet) – a signaling server and client library for establishing P2P connections via ICE.

The original is written in C++ and uses [libjuice](https://github.com/paullouisageneau/libjuice). This port keeps the same binary packet protocol so it can interoperate with the C++ clients, while providing a clean `asyncio` API.

## Features

- Full lobby system (create / join / leave / list / update)
- Binary packet framing compatible with the original protocol (version 4)
- SDP + ICE candidate relay
- Keep-alive, error reporting, basic load-balance support
- Ready for `aioice` (or `aiortc`) on the client side for actual P2P

## Quick start

```bash
# Install
pip install -e .

# Run the signaling server (default port 34197)
python -m coopnet.server
# or
coopnet-server

# In another terminal – minimal client example
python examples/simple_client.py
```

## STUN / TURN

The server automatically sends STUN (and optional TURN) configuration to every connecting client:

| Client type                  | STUN server used               |
|------------------------------|--------------------------------|
| Normal clients               | `stun.l.google.com:19302`      |
| Radmin VPN (IP `26.x.x.x`)   | `stun.cloudflare.com:3478`     |

### Optional TURN servers

Create a file named `turn-servers.cfg` next to the server (or pass `--turn-cfg path`):

```
# host:username:password:port
turn.example.com:myuser:mypass:3478
```

See `turn-servers.cfg.example` for a template.

### Included Go TURN server

A minimal TURN server written in Go (using Pion) is included in the `turn/` folder.

```bash
cd turn
go mod tidy
go run . --public-ip YOUR_PUBLIC_IP --user coopnet --pass coopnetpass
```

Then put this line in `turn-servers.cfg`:

```
YOUR_PUBLIC_IP:coopnet:coopnetpass:3478
```

See `turn/README.md` for more details.

## Project layout

```
coopnet-py/
├── coopnet/
│   ├── __init__.py
│   ├── protocol.py      # Packet types + binary encode/decode
│   ├── server.py        # asyncio signaling + lobby server
│   └── client.py        # High-level async client
└── examples/
    ├── run_server.py
    └── simple_client.py
```

## Protocol notes

The wire format is identical to the C++ version:

```
struct Header {
    uint16_t packetType;
    uint16_t dataSize;
    uint16_t stringSize;
};
// followed by `dataSize` bytes of packed data
// followed by `stringSize` bytes of length-prefixed UTF-8 strings
```

See `coopnet/protocol.py` for the complete list of packet types.

## License

AGPL-3.0-or-later (same as the original project).
