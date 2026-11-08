"""Serializable race rules. Only choose() accepts player decisions."""

import random

CARDS = {
    "催眠师": ("催眠术", "主要移动前，可以将任意一名运动员传送到自己的格子。"),
    "大长腿": ("慢跑", "可以跳过主要移动的掷骰，改为移动 5 格。"),
    "教练": ("好苗子", "与自己同格的所有运动员（包括自己）主要移动 +1。"),
    "跟班": ("遵命，先生", "另一名运动员为主要移动掷出 6 时，在其移动前先移动 2 格。"),
    "起哄者": (
        "幸灾乐祸",
        "一名运动员回合结束时，若与回合开始时的位置相差不超过 1 格，自己移动 2 格。",
    ),
    "巨婴": ("真的很大", "起点外独占一格。试图进入该格的角色改放在巨婴后方 1 格。"),
    "模仿猫": ("复制目标", "拥有当前最领先运动员的能力，并列时选择复制目标。"),
}
FINISH = 30
GOLD = (3, 4, 4, 5)
SILVER = (1, 2, 2, 3)
ARROWS = {7: 3, 11: 1, 16: -4, 23: 2, 24: -2}
TRIPS = {5, 17, 26}
STARS = {1, 13}
MAPS = ("标准地图", "狂热地图")


class RuleError(ValueError):
    pass


def player(name, bot=False):
    return dict(name=name, bot=bot, hand=[], lineup=[], scores=[0] * 4, ranks=[])


def lobby(name, board):
    if board not in MAPS:
        raise RuleError("未知地图")
    return dict(
        phase="lobby",
        board=board,
        players=[player(name)],
        round=0,
        prompt=None,
        log=[],
        pieces={},
        arrivals=[],
        dice=[],
        history=[],
        queue=[],
    )


def standings(state):
    def key(i):
        p = state["players"][i]
        return -sum(p["scores"]), sum(p["ranks"])

    order = sorted(range(len(state["players"])), key=key)
    return [(i, 1 + sum(key(other) < key(i) for other in order)) for i in order]


class Race:
    def __init__(self, state, rng=None):
        self.s = state
        self.rng = rng or random.SystemRandom()

    @property
    def players(self):
        return self.s["players"]

    @property
    def pieces(self):
        return self.s["pieces"]

    @property
    def dual(self):
        return len(self.players) == 2

    def log(self, message):
        self.s["log"].append(message)
        self.s["log"] = self.s["log"][-120:]

    def start(self):
        if self.s["phase"] != "lobby":
            raise RuleError("比赛已开始")
        count = len(self.players)
        if not 2 <= count <= 8:
            raise RuleError("需要 2 至 8 名玩家（可添加电脑）")
        if count * 2 > len(CARDS):
            raise RuleError(
                f"暂不支持该人数进行游戏：{count} 人需要 {count * 2} 名角色，目前有 {len(CARDS)} 名"
            )
        self.new_round()
        self.advance()

    def push(self, *events):
        self.s["queue"][0:0] = list(events)

    def ask(self, seat, kind, title, choices):
        self.s["prompt"] = dict(
            seat=seat,
            kind=kind,
            title=title,
            choices=[dict(value=v, label=l) for v, l in choices],
        )

    def new_round(self):
        s = self.s
        s.update(
            round=s["round"] + 1,
            prompt=None,
            queue=[],
            pieces={},
            arrivals=[],
            dice=[],
            copy=None,
            leaders=[],
            turn=0,
            moves={},
        )
        self.log(f"第 {s['round']} 轮 · {s['board']}")
        for p in self.players:
            p["lineup"] = []
        if self.dual or s["round"] in (1, 3):
            n = len(self.players)
            first = self.rng.randrange(n)
            order = [(first + i) % n for i in range(n)]
            s.update(
                phase="draft",
                first=first,
                draft=order + order[::-1],
                pool=self.rng.sample(list(CARDS), 2 * n),
            )
            for p in self.players:
                p["hand"] = []
            self.push(["draft"])
        else:
            for p in self.players:
                p["lineup"] = p["hand"][:]
            self.begin_race()

    def do_draft(self):
        if self.s["draft"]:
            self.ask(
                self.s["draft"][0],
                "draft",
                "选一名角色加入你的队伍",
                [(c, c) for c in self.s["pool"]],
            )
        elif self.dual:
            for p in self.players:
                p["lineup"] = p["hand"][:]
            self.begin_race()
        else:
            self.s["phase"] = "lineup"
            self.push(*[["lineup", i] for i in range(len(self.players))], ["begin"])

    def do_lineup(self, seat):
        self.ask(
            seat,
            "lineup",
            "选择本轮出场角色",
            [(c, c) for c in self.players[seat]["hand"]],
        )

    def begin_race(self):
        s = self.s
        s.update(phase="race", turn=s["first"])
        for i, p in enumerate(self.players):
            for c in p["lineup"]:
                self.pieces[c] = dict(seat=i, pos=0, trip=False)
        self.push(["turn"])

    do_begin = begin_race

    def active(self):
        return [c for c, p in self.pieces.items() if p["pos"] < FINISH]

    def ability(self, c):
        return self.s.get("copy") if c == "模仿猫" else c

    def sync_copy(self):
        live = self.active()
        cat = "模仿猫"
        if cat not in live:
            self.s["copy"] = None
            return
        front = max(self.pieces[c]["pos"] for c in live)
        leaders = [c for c in live if c != cat and self.pieces[c]["pos"] == front]
        if leaders == self.s["leaders"]:
            return
        self.s["leaders"] = leaders
        self.s["copy"] = None
        if len(leaders) == 1:
            self.set_copy(leaders[0])
        elif leaders:
            self.ask(
                self.pieces[cat]["seat"],
                "copy",
                "模仿猫 · 选择一名并列领先者",
                [(c, c) for c in leaders],
            )

    def set_copy(self, c):
        self.s["copy"] = c
        self.log(f"模仿猫复制了{c}的「{CARDS[c][0]}」")
        if c == "巨婴":
            pos = self.pieces["模仿猫"]["pos"]
            if pos:
                self.push(
                    *[
                        ["place", t, pos - 1, []]
                        for t in self.clockwise("模仿猫")
                        if t != "模仿猫" and self.pieces[t]["pos"] == pos
                    ]
                )

    def clockwise(self, runner):
        seat = self.pieces[runner]["seat"]
        return sorted(
            self.active(),
            key=lambda c: (
                (self.pieces[c]["seat"] - seat) % len(self.players),
                c != runner,
            ),
        )

    def do_turn(self):
        s = self.s
        seat = s["turn"]
        runners = [c for c in self.active() if self.pieces[c]["seat"] == seat]
        s.update(
            dice=[],
            order=runners,
            moves={},
            starts={c: self.pieces[c]["pos"] for c in runners},
        )
        s["skip"] = [c for c in runners if self.pieces[c]["trip"]]
        for c in s["skip"]:
            self.pieces[c]["trip"] = False
        if len(runners) == 2:
            self.ask(
                seat,
                "order",
                "选择本回合先结算的角色",
                [(c, f"{c}先行动") for c in runners],
            )
        else:
            self.prepare()

    def prepare(self):
        self.push(*[["pre", c] for c in self.s["order"]], ["roll_step"])

    def do_pre(self, c):
        if c not in self.active():
            return
        seat = self.pieces[c]["seat"]
        if self.ability(c) == "催眠师":
            self.ask(
                seat,
                "hypno",
                f"{c} · 可以传送一名角色",
                [("-", "跳过技能")] + [(t, f"传送{t}") for t in self.active()],
            )
            self.s["prompt"]["runner"] = c
        elif self.ability(c) == "大长腿" and c not in self.s["skip"]:
            self.ask(
                seat,
                "stride",
                f"{c} · 如何进行主要移动？",
                [("fixed", "慢跑 5 格"), ("die", "使用骰子")],
            )
            self.s["prompt"]["runner"] = c

    def do_roll_step(self):
        s = self.s
        eligible = [
            c
            for c in s["order"]
            if c in self.active() and c not in s["skip"] and c not in s["moves"]
        ]
        s["eligible"] = eligible
        if eligible:
            self.ask(s["turn"], "roll", "投掷本回合的骰子", [("roll", "掷骰")])
        else:
            self.schedule_runs()

    def rolled(self):
        s = self.s
        s["dice"] = [self.rng.randint(1, 6) for _ in range(2 if self.dual else 1)]
        self.log(
            f"{self.players[s['turn']]['name']} 掷出 " + "、".join(map(str, s["dice"]))
        )
        if self.dual and s["dice"][0] != s["dice"][1]:
            runner = s["eligible"][0]
            opts = []
            for i, val in enumerate(s["dice"]):
                label = f"{runner}用 {val}"
                if len(s["eligible"]) == 2:
                    label += f"，{s['eligible'][1]}用 {s['dice'][1 - i]}"
                opts.append((str(i), label))
            self.ask(s["turn"], "assign", "分配本回合的骰子", opts)
        else:
            self.assign(0)

    def assign(self, first):
        for idx, c in enumerate(self.s["eligible"]):
            self.s["moves"][c] = self.s["dice"][(first + idx) % len(self.s["dice"])]
        self.schedule_runs()

    def schedule_runs(self):
        self.push(*[["run", c] for c in self.s["order"]], ["next_turn"])

    def do_run(self, c):
        if c not in self.active():
            return
        if c in self.s["skip"]:
            self.log(f"{c}因绊倒跳过主要移动")
            self.push(["end_runner", c])
            return
        value = self.s["moves"][c]
        if value == 6 and c in self.s["eligible"]:
            self.push(
                *[["follower", t, c] for t in self.clockwise(c) if t != c],
                ["main_move", c, value],
                ["end_runner", c],
            )
        else:
            self.push(["main_move", c, value], ["end_runner", c])

    def do_follower(self, t, c):
        if t in self.active() and self.ability(t) == "跟班":
            self.log(f"{c}掷出 6，{t}发动「遵命，先生」")
            self.move(t, 2)

    def do_main_move(self, c, value):
        if c not in self.active():
            return
        bonus = sum(
            self.ability(t) == "教练" and self.pieces[t]["pos"] == self.pieces[c]["pos"]
            for t in self.active()
        )
        if bonus:
            self.log(f"{c}获得教练加成 +{bonus}")
        self.move(c, value + bonus)

    def do_end_runner(self, c):
        if abs(self.pieces[c]["pos"] - self.s["starts"][c]) <= 1:
            self.push(*[["heckle", t] for t in self.clockwise(c)])

    def do_heckle(self, t):
        if t in self.active() and self.ability(t) == "起哄者":
            self.log(f"{t}发动「幸灾乐祸」")
            self.move(t, 2)

    def do_next_turn(self):
        self.s["turn"] = (self.s["turn"] + 1) % len(self.players)
        self.push(["turn"])

    def move(self, c, delta, chain=()):
        if delta:
            self.land(c, self.pieces[c]["pos"] + delta, "移动", chain)

    def land(self, c, destination, method, chain=()):
        if c not in self.active():
            return
        p = self.pieces[c]
        old = p["pos"]
        dest = max(0, min(FINISH, destination))
        if dest == old:
            return
        # Resolve occupied destinations, including adjacent copied Giants.
        while 0 < dest < FINISH and any(
            t != c and self.ability(t) == "巨婴" and self.pieces[t]["pos"] == dest
            for t in self.active()
        ):
            self.log(f"巨婴占格，{c}改放到第 {dest - 1} 格")
            dest -= 1
        if dest == old:
            return
        p["pos"] = dest
        self.log(f"{c}{method}：{old} → {dest}")
        if dest == FINISH:
            self.finish(c)
            return
        events = []
        if dest and self.ability(c) == "巨婴":
            for other in self.clockwise(c):
                if other != c and self.pieces[other]["pos"] == dest:
                    events.append(["place", other, dest - 1, list(chain)])
        # An arrow/giant interaction may lead back to a previously resolved landing.
        marker = f"{c}@{dest}"
        if marker not in chain:
            events.append(["tile", c, dest, [*chain, marker]])
        self.push(*events)

    def do_place(self, c, dest, chain):
        self.land(c, dest, "放置", chain)

    def score(self, seat, delta, reason):
        self.players[seat]["scores"][self.s["round"] - 1] += delta
        self.log(f"{self.players[seat]['name']} · {reason} {delta:+d} 分")

    def do_tile(self, c, pos, chain):
        if self.s["board"] != "狂热地图" or self.pieces[c]["pos"] != pos:
            return
        if pos in STARS:
            self.score(self.pieces[c]["seat"], 1, "星星格")
        elif pos in TRIPS:
            self.pieces[c]["trip"] = True
            self.log(f"{c}绊倒，下次跳过主要移动")
        elif pos in ARROWS:
            self.move(c, ARROWS[pos], chain)

    def finish(self, c):
        s = self.s
        s["arrivals"].append(c)
        first = len(s["arrivals"]) == 1
        points = (GOLD if first else SILVER)[s["round"] - 1]
        self.score(
            self.pieces[c]["seat"], points, c + ("金奖杯" if first else "银奖杯")
        )
        if first:
            return
        ranks = {}
        for t, p in self.pieces.items():
            ranks[t] = (
                s["arrivals"].index(t) + 1
                if t in s["arrivals"]
                else 1 + sum(other["pos"] > p["pos"] for other in self.pieces.values())
            )
        for p in self.players:
            p["ranks"].append(min(ranks[t] for t in p["lineup"]))
        s["history"].append(
            dict(round=s["round"], podium=s["arrivals"][:], ranks=ranks)
        )
        s.update(queue=[], prompt=None, phase="done" if s["round"] == 4 else "break")
        if s["phase"] == "break":
            self.ask(0, "next", f"第 {s['round']} 轮结束", [("next", "进入下一轮")])

    def advance(self):
        while self.s["queue"] and not self.s["prompt"]:
            # Finish a Giant's displacement before checking for a new leader.
            # A briefly overlapping pawn is not sharing its landing square.
            if self.s["phase"] == "race" and self.s["queue"][0][0] != "place":
                self.sync_copy()
                if self.s["prompt"]:
                    break
            kind, *args = self.s["queue"].pop(0)
            getattr(self, "do_" + kind)(*args)

    def choose(self, seat, value):
        s = self.s
        prompt = s["prompt"]
        if not prompt or prompt["seat"] != seat:
            raise RuleError("请等待轮到你行动")
        if value not in [opt["value"] for opt in prompt["choices"]]:
            raise RuleError("这个选择已不可用")
        s["prompt"] = None
        kind = prompt["kind"]
        if kind == "draft":
            self.players[seat]["hand"].append(value)
            s["pool"].remove(value)
            s["draft"].pop(0)
            self.log(f"{self.players[seat]['name']}选了{value}")
            self.push(["draft"])
        elif kind == "lineup":
            self.players[seat]["lineup"] = [value]
            self.players[seat]["hand"].remove(value)
        elif kind == "copy":
            self.set_copy(value)
        elif kind == "order":
            s["order"].remove(value)
            s["order"].insert(0, value)
            self.prepare()
        elif kind == "hypno" and value != "-":
            self.land(value, self.pieces[prompt["runner"]]["pos"], "传送")
        elif kind == "stride" and value == "fixed":
            s["moves"][prompt["runner"]] = 5
        elif kind == "roll":
            self.rolled()
        elif kind == "assign":
            self.assign(int(value))
        elif kind == "next":
            self.new_round()
        self.advance()

    def bot_choice(self):
        s = self.s
        q = s["prompt"]
        opts = [o["value"] for o in q["choices"]]
        # Vary tactics so opposed hypnotists or repeated arrow landings do not
        # keep computer-controlled racers in a deterministic stalemate.
        if q["kind"] in ("stride", "assign", "hypno") and self.rng.random() < 0.18:
            return self.rng.choice(opts)
        if q["kind"] == "stride":
            return "fixed"
        if q["kind"] == "hypno":
            runner = q["runner"]
            rivals = [
                c
                for c in self.active()
                if self.pieces[c]["seat"] != q["seat"]
                and self.pieces[c]["pos"] > self.pieces[runner]["pos"]
            ]
            return max(rivals, key=lambda c: self.pieces[c]["pos"]) if rivals else "-"
        if q["kind"] == "assign":

            def utility(index):
                result = 0
                for j, c in enumerate(s["eligible"]):
                    pos = self.pieces[c]["pos"] + s["dice"][(int(index) + j) % 2]
                    result += 50 if pos >= FINISH else pos
                    if s["board"] == "狂热地图":
                        result += (
                            ARROWS.get(pos, 0) + 5 * (pos in STARS) - 4 * (pos in TRIPS)
                        )
                return result

            return max(opts, key=utility)
        return self.rng.choice(opts)
