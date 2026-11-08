"""One process serves the web interface, rooms and resumable SQLite games."""

import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import secrets
import sqlite3
from urllib.parse import urlsplit

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from game import CARDS, Race, RuleError, lobby, player, standings


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("ATHLETE_DB", ROOT / "data" / "game.db"))
BOT_DELAY = 0.4


class Rooms:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS rooms (
            code TEXT PRIMARY KEY, revision INTEGER, state TEXT, tokens TEXT)""")
        self.db.commit()
        self.signals = {}
        self.bots = {}

    def read(self, code):
        row = self.db.execute(
            "SELECT revision,state,tokens FROM rooms WHERE code=?", (code,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "找不到这个房间")
        rev, state, tokens = row
        return rev, json.loads(state), json.loads(tokens)

    def create(self, name, board):
        token = secrets.token_urlsafe(32)
        state = lobby(name, board)
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        while True:
            code = "".join(secrets.choice(alphabet) for _ in range(6))
            try:
                with self.db:
                    self.db.execute(
                        "INSERT INTO rooms VALUES (?,0,?,?)",
                        (code, json.dumps(state), json.dumps([token])),
                    )
                return dict(code=code, token=token, seat=0)
            except sqlite3.IntegrityError:
                continue

    def save(self, code, rev, state, tokens):
        with self.db:
            changed = self.db.execute(
                "UPDATE rooms SET revision=revision+1,state=?,tokens=? WHERE code=? AND revision=?",
                (json.dumps(state, ensure_ascii=False), json.dumps(tokens), code, rev),
            )
            if not changed.rowcount:
                raise HTTPException(409, "房间已更新，请按最新状态操作")
        signal = self.signals.pop(code, None)
        if signal:
            signal.set()

    def signal(self, code):
        return self.signals.setdefault(code, asyncio.Event())

    def run_bots(self, code):
        if code not in self.bots:
            self.bots[code] = asyncio.create_task(self.bot_loop(code))

    async def bot_loop(self, code):
        try:
            while True:
                rev, state, tokens = self.read(code)
                q = state["prompt"]
                if not q or not state["players"][q["seat"]]["bot"]:
                    return
                await asyncio.sleep(BOT_DELAY)
                # Read again because a room action can arrive during the delay.
                now, state, tokens = self.read(code)
                if now != rev:
                    continue
                race = Race(state)
                race.choose(q["seat"], race.bot_choice())
                self.save(code, now, state, tokens)
        finally:
            self.bots.pop(code, None)

    async def close(self):
        tasks = list(self.bots.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.db.close()


@asynccontextmanager
async def lifespan(app):
    app.state.rooms = Rooms(DB_PATH)
    yield
    await app.state.rooms.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)


class Entry(BaseModel):
    name: str = Field(min_length=1, max_length=20)
    board: str = "标准地图"


class Action(BaseModel):
    revision: int = Field(ge=0)
    action: str
    value: str = ""


def clean_name(name):
    if not name.strip():
        raise HTTPException(422, "请输入昵称")
    return name.strip()


def authorize(tokens, token):
    if isinstance(token, str) and token.isascii():
        for i, value in enumerate(tokens):
            if value and secrets.compare_digest(value, token):
                return i
    raise HTTPException(403, "座位凭证无效")


def public(code, rev, s, seat):
    keys = (
        "phase",
        "board",
        "players",
        "round",
        "log",
        "pieces",
        "arrivals",
        "dice",
        "history",
        "prompt",
        "copy",
        "pool",
        "turn",
    )
    return dict(
        code=code,
        revision=rev,
        seat=seat,
        standings=standings(s),
        **{k: s[k] for k in keys if k in s},
    )


@app.get("/api/cards")
async def cards():
    return CARDS


@app.post("/api/rooms")
async def create(body: Entry):
    if body.board not in ("标准地图", "狂热地图"):
        raise HTTPException(422, "未知地图")
    return app.state.rooms.create(clean_name(body.name), body.board)


@app.post("/api/rooms/{code}/join")
async def join(code: str, body: Entry):
    store = app.state.rooms
    rev, s, tokens = store.read(code)
    if s["phase"] != "lobby" or len(tokens) >= 8:
        raise HTTPException(409, "房间已开赛或已满")
    name = clean_name(body.name)
    if any(p["name"] == name for p in s["players"]):
        raise HTTPException(409, "房间中已有这个昵称")
    token = secrets.token_urlsafe(32)
    tokens.append(token)
    s["players"].append(player(name))
    store.save(code, rev, s, tokens)
    return dict(code=code, token=token, seat=len(tokens) - 1)


@app.post("/api/rooms/{code}/actions")
async def action(code: str, body: Action, authorization: str = Header(default="")):
    store = app.state.rooms
    rev, s, tokens = store.read(code)
    seat = authorize(tokens, authorization.removeprefix("Bearer "))
    if rev != body.revision:
        raise HTTPException(409, "此操作已过期，已同步最新房间状态")
    game = Race(s)
    try:
        if body.action == "choose":
            game.choose(seat, body.value)
        else:
            if seat != 0 or s["phase"] != "lobby":
                raise RuleError("只有房主可以在开赛前设置房间")
            if body.action == "start":
                game.start()
            elif body.action == "bot" and len(tokens) < 8:
                taken = {p["name"] for p in s["players"]}
                i = 1
                while f"电脑 {i}" in taken:
                    i += 1
                s["players"].append(player(f"电脑 {i}", True))
                tokens.append(None)
            elif body.action == "remove_bot" and any(p["bot"] for p in s["players"]):
                # Keep human seat numbers stable by offering removal only for trailing bots.
                if not s["players"][-1]["bot"]:
                    raise RuleError("只能移除末位电脑，以保留其他玩家的座位")
                s["players"].pop()
                tokens.pop()
            else:
                raise RuleError("当前无法执行此操作")
    except RuleError as exc:
        raise HTTPException(409, str(exc)) from exc
    store.save(code, rev, s, tokens)
    store.run_bots(code)
    return {"revision": rev + 1}


@app.websocket("/ws/{code}")
async def updates(ws: WebSocket, code: str):
    origin = ws.headers.get("origin")
    if origin and urlsplit(origin).netloc.lower() != ws.headers.get("host", "").lower():
        await ws.close(code=1008)
        return
    await ws.accept()
    store = app.state.rooms
    try:
        auth = await asyncio.wait_for(ws.receive_json(), timeout=10)
        _, _, tokens = store.read(code)
        seat = authorize(tokens, auth.get("token") if isinstance(auth, dict) else None)
        store.run_bots(code)
        # A disconnect receiver also releases a quiet room's pending subscription.
        closed = asyncio.create_task(ws.receive())
        try:
            while True:
                rev, state, _ = store.read(code)
                signal = store.signal(code)
                await ws.send_json(public(code, rev, state, seat))
                changed = asyncio.create_task(signal.wait())
                try:
                    ready, _ = await asyncio.wait(
                        (changed, closed), return_when=asyncio.FIRST_COMPLETED
                    )
                    if closed in ready:
                        break
                finally:
                    changed.cancel()
                    await asyncio.gather(changed, return_exceptions=True)
        finally:
            closed.cancel()
            await asyncio.gather(closed, return_exceptions=True)
    except (HTTPException, TimeoutError, ValueError, TypeError, AttributeError):
        await ws.close(code=1008)
    except (WebSocketDisconnect, OSError):
        pass


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="web")
