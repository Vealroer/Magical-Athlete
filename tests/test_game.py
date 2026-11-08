import json
import random
import unittest
from unittest.mock import patch

from game import (
    ARROWS,
    CARDS,
    FINISH,
    GOLD,
    SILVER,
    Race,
    RuleError,
    lobby,
    player,
    standings,
)


def fixture(names, positions, board="标准地图"):
    s = lobby("甲", board)
    s.update(
        phase="race",
        round=1,
        first=0,
        turn=0,
        leaders=[],
        copy=None,
        order=[],
        moves={},
        eligible=[],
        starts={},
        skip=[],
        queue=[],
    )
    s["players"] = [player(c) for c in names]
    for i, (name, pos) in enumerate(zip(names, positions)):
        s["players"][i]["lineup"] = [name]
        s["pieces"][name] = dict(seat=i, pos=pos, trip=False)
    return Race(s, random.Random(811))


class Abilities(unittest.TestCase):
    def test_hypnosis_optional_target_and_landing(self):
        g = fixture(["催眠师", "教练", "跟班"], [13, 4, 22], "狂热地图")
        g.do_pre("催眠师")
        g.choose(0, "-")
        self.assertEqual(g.pieces["跟班"]["pos"], 22)
        g.do_pre("催眠师")
        g.choose(0, "跟班")
        self.assertEqual(g.pieces["跟班"]["pos"], 13)
        self.assertEqual(g.players[2]["scores"][0], 1)
        self.assertTrue(any("跟班传送" in e for e in g.s["log"]))

    def test_stride_replaces_roll_or_can_use_die(self):
        for option, expected in [("fixed", 5), ("die", 3)]:
            g = fixture(["大长腿", "起哄者", "跟班"], [8, 0, 0])
            g.push(["turn"])
            g.advance()
            g.choose(0, option)
            with patch.object(g.rng, "randint", return_value=3) as die:
                if option == "die":
                    g.choose(0, "roll")
                self.assertEqual(die.call_count, int(option == "die"))
            self.assertEqual(g.pieces["大长腿"]["pos"], 8 + expected)

    def test_coach_self_shared_only_main_move(self):
        g = fixture(["教练", "催眠师", "跟班"], [2, 2, 7])
        g.do_main_move("催眠师", 3)
        self.assertEqual(g.pieces["催眠师"]["pos"], 6)
        g.do_main_move("教练", 2)
        self.assertEqual(g.pieces["教练"]["pos"], 5)
        g.do_main_move("跟班", 2)
        self.assertEqual(g.pieces["跟班"]["pos"], 9)
        g.move("催眠师", -1)
        g.move("催眠师", 2)
        self.assertEqual(g.pieces["催眠师"]["pos"], 7)

    def test_follower_reacts_before_move_and_can_win_silver(self):
        g = fixture(["大长腿", "跟班", "教练"], [25, 28, 30])
        g.s["arrivals"] = ["教练"]
        g.s.update(moves={"大长腿": 6}, eligible=["大长腿"], starts={"大长腿": 25})
        g.push(["run", "大长腿"])
        g.advance()
        self.assertEqual(g.s["arrivals"], ["教练", "跟班"])
        self.assertEqual(g.pieces["大长腿"]["pos"], 25)
        self.assertEqual(g.players[1]["scores"][0], 1)

    def test_follower_not_self_or_modified_six(self):
        g = fixture(["跟班", "教练", "大长腿"], [4, 4, 4])
        for c, value in [("大长腿", 5), ("跟班", 6)]:
            g.s.update(moves={c: value}, eligible=[c], starts={c: 4})
            g.push(["run", c])
            g.advance()
        self.assertEqual(g.pieces["跟班"]["pos"], 11)
        self.assertFalse(any("发动「遵命" in m for m in g.s["log"]))

    def test_heckler_uses_net_distance_including_own_skipped_turn(self):
        for start, end, expected in [
            (4, 4, 2),
            (4, 5, 2),
            (4, 3, 2),
            (4, 6, 0),
            (4, 2, 0),
        ]:
            g = fixture(["催眠师", "起哄者", "跟班"], [end, 0, 0])
            g.s["starts"] = {"催眠师": start}
            g.push(["end_runner", "催眠师"])
            g.advance()
            self.assertEqual(g.pieces["起哄者"]["pos"], expected)
        g.s["skip"] = ["起哄者"]
        g.s["starts"] = {"起哄者": 0}
        g.push(["run", "起哄者"])
        g.advance()
        self.assertEqual(g.pieces["起哄者"]["pos"], 2)

    def test_giant_start_passing_targeting_and_displacement(self):
        g = fixture(["巨婴", "教练", "大长腿"], [0, 3, 3])
        g.land("教练", 0, "传送")
        self.assertEqual(g.pieces["教练"]["pos"], 0)
        g.move("巨婴", 3)
        g.advance()
        self.assertEqual(g.pieces["大长腿"]["pos"], 2)
        g.move("教练", 4)
        self.assertEqual(g.pieces["教练"]["pos"], 4)
        g.land("教练", 3, "传送")
        self.assertEqual(g.pieces["教练"]["pos"], 2)

    def test_giant_places_onto_map_tile(self):
        g = fixture(["巨婴", "跟班", "教练"], [14, 8, 0], "狂热地图")
        g.move("跟班", 6)
        g.advance()
        self.assertEqual(g.pieces["跟班"]["pos"], 13)
        self.assertEqual(g.players[1]["scores"][0], 1)

    def test_copy_ties_new_leader_sole_lead_and_actual_effect(self):
        g = fixture(["模仿猫", "大长腿", "跟班"], [2, 4, 4])
        g.push(["pre", "模仿猫"])
        g.advance()
        self.assertEqual(g.s["prompt"]["kind"], "copy")
        g.choose(0, "大长腿")
        self.assertEqual(g.s["prompt"]["kind"], "stride")
        g.choose(0, "fixed")
        self.assertEqual(g.s["moves"]["模仿猫"], 5)
        g.move("跟班", 1)
        g.advance()
        self.assertEqual(g.ability("模仿猫"), "跟班")
        g.move("模仿猫", 3)
        g.advance()
        self.assertEqual(g.ability("模仿猫"), "跟班")
        g.move("模仿猫", 1)
        g.advance()
        self.assertIsNone(g.ability("模仿猫"))
        g.pieces["跟班"]["pos"] = FINISH
        g.sync_copy()
        self.assertIsNone(g.ability("模仿猫"))

    def test_copied_follower_runs_in_clockwise_order(self):
        g = fixture(["大长腿", "跟班", "模仿猫"], [2, 20, 6])
        g.s.update(moves={"大长腿": 6}, eligible=["大长腿"], starts={"大长腿": 2})
        g.push(["run", "大长腿"])
        g.advance()
        moves = [line.split("移动")[0] for line in g.s["log"] if "移动：" in line]
        self.assertEqual(moves, ["跟班", "模仿猫", "大长腿"])

    def test_giant_displaces_cat_before_copy_is_recalculated(self):
        g = fixture(["巨婴", "模仿猫", "催眠师"], [10, 12, 4], "狂热地图")
        g.sync_copy()
        g.move("巨婴", 2)
        g.advance()
        self.assertEqual(g.pieces["巨婴"]["pos"], 12)
        self.assertEqual(g.pieces["模仿猫"]["pos"], 11)
        self.assertEqual(g.ability("模仿猫"), "巨婴")

    def test_trip_in_current_turn_skips_next_turn(self):
        g = fixture(["教练", "催眠师", "跟班"], [2, 0, 0], "狂热地图")
        g.do_turn()
        g.land("教练", 5, "传送")
        g.advance()
        self.assertEqual(g.s["prompt"]["kind"], "roll")
        self.assertTrue(g.pieces["教练"]["trip"])
        with patch.object(g.rng, "randint", return_value=2):
            g.choose(0, "roll")
        self.assertEqual(g.pieces["教练"]["pos"], 8)
        self.assertTrue(g.pieces["教练"]["trip"])


class BoardAndFormat(unittest.TestCase):
    def test_special_tiles_and_zero(self):
        for pos, delta in ARROWS.items():
            g = fixture(["教练", "起哄者", "大长腿"], [0, 0, 0], "狂热地图")
            g.land("教练", pos, "传送")
            g.advance()
            self.assertEqual(g.pieces["教练"]["pos"], pos + delta)
        for pos in (5, 17, 26):
            g.land("教练", pos, "放置")
            g.advance()
            self.assertTrue(g.pieces["教练"]["trip"])
            g.pieces["教练"]["trip"] = False
        for pos in (1, 13):
            g.land("教练", pos, "传送")
            g.advance()
            g.move("教练", 0)
            g.land("教练", pos, "传送")
            g.advance()
        self.assertEqual(g.players[0]["scores"][0], 2)

    def test_tripped_hypnotist_still_uses_ability(self):
        g = fixture(["催眠师", "教练", "起哄者"], [5, 8, 0])
        g.pieces["催眠师"]["trip"] = True
        g.push(["turn"])
        g.advance()
        g.choose(0, "教练")
        self.assertEqual([g.pieces[c]["pos"] for c in g.pieces], [5, 5, 2])
        self.assertEqual(g.s["prompt"]["seat"], 1)
        self.assertFalse(g.pieces["催眠师"]["trip"])

    def test_dual_dice_choice_runs_in_selected_order(self):
        g = fixture(["教练", "跟班", "大长腿", "巨婴"], [12, 1, 3, 8])
        g.s["players"] = [player("甲"), player("乙")]
        for c, seat in [("教练", 0), ("跟班", 0), ("大长腿", 1), ("巨婴", 1)]:
            g.pieces[c]["seat"] = seat
            g.players[seat]["lineup"].append(c)
        g.push(["turn"])
        g.advance()
        g.choose(0, "跟班")
        with patch.object(g.rng, "randint", side_effect=[1, 4]):
            g.choose(0, "roll")
        g.choose(0, "1")
        self.assertEqual(g.pieces["跟班"]["pos"], 5)
        self.assertEqual(g.pieces["教练"]["pos"], 14)
        logs = [line.split("移动")[0] for line in g.s["log"] if "移动：" in line]
        self.assertEqual(logs, ["跟班", "教练"])

    def test_one_player_wins_both_and_tied_unfinished(self):
        g = fixture(["巨婴", "跟班", "大长腿", "教练"], [28, 29, 5, 5])
        g.s["players"] = [player("甲"), player("乙")]
        for c, p in g.pieces.items():
            p["seat"] = 0 if c in ("巨婴", "跟班") else 1
            g.players[p["seat"]]["lineup"].append(c)
        g.move("跟班", 3)
        g.move("巨婴", 5)
        self.assertEqual(g.players[0]["scores"][0], 4)
        self.assertEqual([p["ranks"] for p in g.players], [[1], [3]])
        self.assertEqual(g.s["phase"], "break")
        g.players[1]["scores"][0] = 4
        self.assertEqual(standings(g.s), [(0, 1), (1, 2)])
        g.players[1]["ranks"] = [1]
        self.assertEqual(standings(g.s), [(0, 1), (1, 1)])

    def test_capacity_and_draft_order(self):
        for n in (2, 3, 4, 8):
            s = lobby("甲", "标准地图")
            s["players"] += [player(str(i)) for i in range(1, n)]
            g = Race(s, random.Random(3))
            if n > 3:
                with self.assertRaisesRegex(RuleError, "角色"):
                    g.start()
                continue
            g.start()
            self.assertEqual(len(set(s["pool"])), 2 * n)
            first = s["first"]
            seats = [(first + i) % n for i in range(n)]
            self.assertEqual(s["draft"], seats + seats[::-1])
            with self.assertRaises(RuleError):
                g.choose((first + 1) % n, g.bot_choice())

    def test_four_round_matches(self):
        observed = set()
        for n in (2, 3):
            for board in ("标准地图", "狂热地图"):
                for seed in range(12):
                    s = lobby("甲", board)
                    s["players"] += [player(str(i)) for i in range(1, n)]
                    rng = random.Random(seed)
                    g = Race(s, rng)
                    g.start()
                    used = {}
                    for step in range(2500):
                        if s["phase"] == "done":
                            break
                        if s["phase"] == "race" and s["round"] not in used:
                            used[s["round"]] = [set(p["lineup"]) for p in g.players]
                            observed.update(s["pieces"])
                        q = s["prompt"]
                        self.assertIsNotNone(q, (n, board, seed, step))
                        # Every pending decision must survive a JSON/SQLite round trip.
                        s = json.loads(json.dumps(s))
                        g = Race(s, rng)
                        g.choose(q["seat"], g.bot_choice())
                    self.assertEqual(s["phase"], "done", (n, board, seed))
                    self.assertEqual(len(s["history"]), 4)
                    for i, h in enumerate(s["history"]):
                        self.assertEqual(len(set(h["podium"])), 2)
                        total = sum(p["scores"][i] for p in g.players)
                        self.assertGreaterEqual(total, GOLD[i] + SILVER[i])
                        if board == "标准地图":
                            self.assertEqual(total, GOLD[i] + SILVER[i])
                    if n == 3:
                        for i in (1, 3):
                            for a, b in zip(used[i], used[i + 1]):
                                self.assertTrue(a.isdisjoint(b))
        self.assertEqual(observed, set(CARDS))
