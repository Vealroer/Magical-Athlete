"""Exercise real HTTP/WebSocket clients against an ephemeral Uvicorn server."""

from contextlib import contextmanager
import json
from pathlib import Path
import random
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import build_opener, ProxyHandler, Request

import uvicorn
from websockets.sync.client import connect

import server
from game import Race


@contextmanager
def running(db):
    with socket.socket() as sock, patch.object(server, "DB_PATH", db):
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        config = uvicorn.Config(server.app, log_level="error", ws="websockets-sansio")
        service = uvicorn.Server(config)
        thread = threading.Thread(
            target=service.run, kwargs={"sockets": [sock]}, daemon=True
        )
        thread.start()
        try:
            for _ in range(500):
                if service.started:
                    break
                time.sleep(0.01)
            if not service.started:
                raise RuntimeError("Test server did not start")
            yield port
        finally:
            service.should_exit = True
            thread.join(8)
            if thread.is_alive():
                raise RuntimeError("Test server did not stop")


class Client:
    def __init__(self, port):
        self.port = port
        self.http = build_opener(ProxyHandler({}))

    def post(self, path, data, token=""):
        req = Request(
            f"http://127.0.0.1:{self.port}/api/rooms" + path,
            data=json.dumps(data).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token,
            },
        )
        with self.http.open(req, timeout=8) as response:
            return json.load(response)

    @contextmanager
    def open_seat(self, seat):
        with connect(
            f"ws://127.0.0.1:{self.port}/ws/{seat['code']}", proxy=None
        ) as sock:
            sock.send(json.dumps({"token": seat["token"]}))
            yield sock

    def action(self, seat, rev, action, value=""):
        return self.post(
            "/" + seat["code"] + "/actions",
            dict(revision=rev, action=action, value=value),
            seat["token"],
        )


class NetworkGame(unittest.TestCase):
    def test_two_clients_four_rounds_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "game.db"
            rng = random.Random(107)
            with patch.object(server, "Race", side_effect=lambda s: Race(s, rng)):
                with running(db) as port:
                    client = Client(port)
                    host = client.post("", dict(name="甲", board="狂热地图"))
                    guest = client.post("/" + host["code"] + "/join", dict(name="乙"))
                    other = client.post("", dict(name="其他房主"))
                    with client.open_seat(host) as a, client.open_seat(guest) as b:
                        state = json.loads(a.recv(5))
                        self.assertEqual(json.loads(b.recv(5))["seat"], 1)
                        rev = state["revision"]
                        for seat in (guest, {**host, "token": other["token"]}):
                            with self.assertRaises(HTTPError) as err:
                                client.action(seat, rev, "start")
                            self.assertIn(err.exception.code, (403, 409))
                        client.action(host, rev, "start")
                        with self.assertRaises(HTTPError) as err:
                            client.action(host, rev, "start")
                        self.assertEqual(err.exception.code, 409)
                        state = json.loads(a.recv(5))
                        self.assertEqual(
                            json.loads(b.recv(5))["revision"], state["revision"]
                        )
                        self.assertNotIn(host["token"], json.dumps(state))
                        # Play into the first dice allocation, then restart the entire service.
                        for _ in range(150):
                            q = state["prompt"]
                            if q["kind"] == "assign":
                                break
                            seat = [host, guest][q["seat"]]
                            client.action(
                                seat,
                                state["revision"],
                                "choose",
                                q["choices"][0]["value"],
                            )
                            state = json.loads(a.recv(5))
                            self.assertEqual(
                                json.loads(b.recv(5))["revision"], state["revision"]
                            )
                        self.assertEqual(state["prompt"]["kind"], "assign")
                with running(db) as port:
                    client = Client(port)
                    with client.open_seat(host) as a, client.open_seat(guest) as b:
                        self.assertEqual(json.loads(a.recv(5)), state)
                        b.recv(5)
                        for _ in range(2000):
                            if state["phase"] == "done":
                                break
                            q = state["prompt"]
                            option = rng.choice(q["choices"])["value"]
                            client.action(
                                [host, guest][q["seat"]],
                                state["revision"],
                                "choose",
                                option,
                            )
                            state = json.loads(a.recv(5))
                            other_state = json.loads(b.recv(5))
                            self.assertEqual(state["players"], other_state["players"])
                        self.assertEqual(state["phase"], "done")
                        self.assertEqual(len(state["history"]), 4)
                        self.assertEqual(len(state["standings"]), 2)
                        print(
                            "联机四轮得分",
                            [(p["name"], p["scores"]) for p in state["players"]],
                        )

    def test_single_human_with_two_server_bots(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(server, "BOT_DELAY", 0.001),
        ):
            rng = random.Random(11)
            with (
                patch.object(server, "Race", side_effect=lambda s: Race(s, rng)),
                running(Path(tmp) / "save.db") as port,
            ):
                client = Client(port)
                host = client.post("", dict(name="练习玩家"))
                with client.open_seat(host) as sock:
                    state = json.loads(sock.recv(5))
                    for action in ("bot", "bot", "start"):
                        client.action(host, state["revision"], action)
                        state = json.loads(sock.recv(5))
                    for _ in range(1800):
                        if state["phase"] == "done":
                            break
                        q = state["prompt"]
                        if q["seat"] == 0:
                            client.action(
                                host,
                                state["revision"],
                                "choose",
                                rng.choice(q["choices"])["value"],
                            )
                        state = json.loads(sock.recv(5))
                    self.assertEqual(state["phase"], "done")
                    self.assertEqual(
                        [
                            sum(p["scores"][i] for p in state["players"])
                            for i in range(4)
                        ],
                        [4, 6, 6, 8],
                    )
