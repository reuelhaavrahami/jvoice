"""Authenticated, bounded WebSocket transport for nodes and agent controllers."""
import argparse
import asyncio
import contextlib
import hmac
import json
import logging
import os
import ssl
from pathlib import Path

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from .protocol import MAX_AUDIO_BYTES, identifier, message, parse, words
from .session import Session
from .speech import Profiles, SpeechModels

log = logging.getLogger("jvoice")


class Peer:
    def __init__(self, socket):
        self.socket = socket
        self.queue = asyncio.Queue(maxsize=64)
        self.writer = asyncio.create_task(self.write())

    def emit(self, event):
        try:
            self.queue.put_nowait(json.dumps(event))
        except asyncio.QueueFull:
            asyncio.create_task(self.socket.close(1013, "Consumer too slow; reconnect"))

    async def write(self):
        try:
            while True:
                await asyncio.wait_for(self.socket.send(await self.queue.get()), 5)
        except (ConnectionClosed, TimeoutError):
            await self.socket.close(1013, "Send timeout")

    async def close(self):
        self.writer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.writer


class Host:
    def __init__(self, token, models, profiles, threshold=0.6):
        self.token, self.models, self.profiles, self.threshold = token, models, profiles, threshold
        self.nodes = {}
        self.agents = {}
        self.speaking = {}

    def broadcast(self, node, event):
        for peer in (self.nodes.get(node), self.agents.get(node)):
            if peer:
                peer.emit(event)

    def cancel(self, node):
        current = self.speaking.pop(node, None)
        if current and node in self.nodes:
            self.nodes[node].emit(message("speak.cancel", speech_id=current[0]))

    async def handler(self, socket):
        auth = socket.request.headers.get("Authorization", "")
        if not hmac.compare_digest(auth, f"Bearer {self.token}"):
            await socket.close(1008, "Authentication required")
            return
        peer = Peer(socket)
        node = None
        role = None
        try:
            hello = parse(await asyncio.wait_for(socket.recv(), 5))
            if hello["type"] != "hello":
                raise ValueError("First message must be hello")
            node = identifier(hello.get("node_id"))
            if socket.request.path == "/v1/node":
                role = self.nodes
                if node in role:
                    raise ValueError("Node already connected")
                keyword = hello.get("keyword", "hey jarvis")
                if not isinstance(keyword, str) or not 1 <= len(words(keyword)) <= 8 or len(keyword) > 128:
                    raise ValueError("Wake phrase must contain 1–8 words")
                if hello.get("sample_rate") != 16000:
                    raise ValueError("Audio must be mono PCM16 little endian at 16000 Hz")
                role[node] = peer  # Reserve before model initialization yields to another connection.
                session = await asyncio.to_thread(Session, self.models, self.profiles, node, keyword, self.threshold)
                peer.emit(message("ready", node_id=node, enrolled=session.profile is not None))
                if node in self.agents:
                    self.agents[node].emit(message("node.connected", node_id=node))
                await self.read_node(peer, node, session)
            elif socket.request.path == "/v1/agent":
                role = self.agents
                if node in role:
                    raise ValueError("Node already has an agent controller")
                role[node] = peer
                peer.emit(message("ready", node_id=node, connected=node in self.nodes))
                await self.read_agent(peer, node)
            else:
                raise ValueError("Unknown endpoint")
        except (ValueError, TypeError, KeyError, TimeoutError) as exc:
            log.info("Protocol error: %s", exc)
            await socket.close(1008, str(exc)[:100])
        except ConnectionClosed:
            pass
        except Exception:
            log.exception("Session failed")
            await socket.close(1011, "Host processing failed; see host log")
        finally:
            if role is not None and role.get(node) is peer:
                role.pop(node)
                self.cancel(node)
                if role is self.nodes and node in self.agents:
                    self.agents[node].emit(message("node.disconnected", node_id=node))
            await peer.close()

    async def read_node(self, peer, node, session):
        async for raw in peer.socket:
            if isinstance(raw, bytes):
                if not raw or len(raw) > MAX_AUDIO_BYTES or len(raw) % 2:
                    raise ValueError("Invalid audio frame")
                for event in await asyncio.to_thread(session.feed, raw):
                    if event["type"] == "session.activated":
                        self.cancel(node)  # Verified barge-in, before any new words.
                    self.broadcast(node, event)
            else:
                event = parse(raw)
                if event["type"] == "enroll.start":
                    self.cancel(node)
                    self.broadcast(node, await asyncio.to_thread(session.enroll))
                elif event["type"] in ("playback.started", "playback.done", "playback.stopped", "playback.error"):
                    sid = identifier(event.get("speech_id"))
                    current = self.speaking.get(node)
                    if current and current[0] == sid:
                        if event["type"] != "playback.started":
                            self.speaking.pop(node, None)
                        if node in self.agents:
                            self.agents[node].emit(message(event["type"], speech_id=sid))
                else:
                    raise ValueError("Unknown node message")

    async def read_agent(self, peer, node):
        async for raw in peer.socket:
            if not isinstance(raw, str):
                raise ValueError("Agents send JSON, not audio")
            event = parse(raw)
            kind = event["type"]
            sid = identifier(event.get("speech_id"))
            if node not in self.nodes:
                peer.emit(message("error", code="node_offline", detail="Node is not connected"))
                continue
            if kind == "speak.start":
                self.cancel(node)
                self.speaking[node] = (sid, 0, False)
                outgoing = message(kind, speech_id=sid)
            elif kind in ("speak.text", "speak.end", "speak.cancel"):
                current = self.speaking.get(node)
                if current is None or current[0] != sid:
                    continue  # Late chunks from cancelled work must never become speech.
                if kind == "speak.cancel":
                    self.cancel(node)
                    continue
                if current[2]:
                    raise ValueError("Speech already ended")
                if kind == "speak.text":
                    text = event.get("text")
                    if not isinstance(text, str) or not 1 <= len(text) <= 2048:
                        raise ValueError("Speech text must have 1–2048 characters")
                    if type(event.get("seq")) is not int or event["seq"] != current[1]:
                        raise ValueError("Out-of-order speech text")
                    self.speaking[node] = (sid, current[1] + 1, False)
                    outgoing = message(kind, speech_id=sid, seq=event["seq"], text=text)
                else:
                    self.speaking[node] = (sid, current[1], True)
                    outgoing = message(kind, speech_id=sid)
            else:
                raise ValueError("Unknown agent message")
            self.nodes[node].emit(outgoing)


async def run(args):
    token = os.environ.get("JVOICE_TOKEN", "")
    if len(token) < 16:
        raise SystemExit("Set JVOICE_TOKEN to a random shared secret of at least 16 characters")
    models = await asyncio.to_thread(SpeechModels, Path(args.models))
    host = Host(token, models, Profiles(Path(args.profiles)), args.threshold)
    tls = None
    if args.cert or args.key:
        if not (args.cert and args.key):
            raise SystemExit("Provide both --cert and --key")
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(args.cert, args.key)
    async with serve(host.handler, args.bind, args.port, ssl=tls,
                     max_size=8192, max_queue=16, ping_interval=20, ping_timeout=20):
        log.info("JVoice listening on %s:%d", args.bind, args.port)
        await asyncio.Future()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--models", default="models")
    parser.add_argument("--profiles", default="profiles")
    parser.add_argument("--threshold", type=float, default=0.6)
    parser.add_argument("--cert")
    parser.add_argument("--key")
    args = parser.parse_args()
    if not 0 < args.threshold <= 1:
        parser.error("--threshold must be in (0, 1]")
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
