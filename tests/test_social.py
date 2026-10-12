"""Version 5 profiles and room-scoped moderation; no external network."""
import unittest
from unittest.mock import patch
from lobby.app import server as S


class SocialTests(unittest.TestCase):
    def setUp(self):
        S.ROOMS.clear()
        S.BUCKETS = S.Buckets()
        self.now = 1000.0
        limits = patch.multiple(S, MAX_SEATS=7, GAME_MAX_PLAYERS=7)
        limits.start()
        S.recompute_dial()
        self.addCleanup(S.recompute_dial)
        self.addCleanup(limits.stop)
        self.log = patch.object(S, "log")
        self.log.start()
        self.addCleanup(self.log.stop)
        self.host = self.create("Host", 1)
        self.code = self.host["room"]

    def call(self, verb, body, who="same-network"):
        self.now += 10
        with S.LOCK:
            return getattr(S, "do_" + verb)(body, who, self.now)

    def create(self, name, identity):
        status, result = self.call("create", {"v": 5, "nick": name, "pre_ok": True,
            "session_type": "party", "player_id": "%032x" % identity,
            "palette": "ff0000:00ff00:0000ff:::::", "character": identity % 4})
        self.assertEqual(status, 200, result)
        return result

    def join(self, name, identity, code=None):
        return self.call("join", {"v": 5, "room": code or self.code, "nick": name,
            "pre_ok": True, "player_id": "%032x" % identity,
            "palette": ":::::::", "character": identity % 4})

    def command(self, member, text, version=5):
        return self.call("chat", {"v": version, "room": self.code,
            "token": member["token"], "text": text})

    def test_permissions_and_protected_host(self):
        _, mod = self.join("Mod", 2)
        _, guest = self.join("Guest", 3)
        self.assertEqual(self.command(guest, "/kick Host")[0], 403)
        self.assertEqual(self.command(self.host, "/mod Mod")[0], 200)
        self.assertEqual(self.command(mod, "/mod Guest")[0], 403)
        self.assertEqual(self.command(mod, "/kick Host")[0], 403)
        self.assertEqual(self.command(mod, "/kick Guest")[0], 200)
        self.assertNotIn(guest["member"], S.ROOMS[self.code].members)
        self.assertEqual(self.command(self.host, "/unmod Mod")[0], 200)
        self.assertEqual(self.command(mod, "/ban Host")[0], 403)

    def test_ban_identity_is_scoped_to_room_and_not_network(self):
        _, victim = self.join("Victim", 2)
        _, other = self.join("Other", 3)
        self.assertEqual(self.command(self.host, "/ban Victim")[0], 200)
        self.assertEqual(self.command(victim, "still here")[0], 403)
        self.assertEqual(self.join("NewName", 2)[0], 403)
        self.assertEqual(self.join("SameNetwork", 4)[0], 200)
        self.assertEqual(self.command(other, "hello")[0], 200)
        fresh = self.create("OtherHost", 5)
        self.assertEqual(self.join("Victim", 2, fresh["room"])[0], 200)
        self.assertEqual(self.command(self.host, "/unban Victim")[0], 200)
        self.assertEqual(self.join("Victim", 2)[0], 200)

    def test_old_chat_stays_literal_and_commands_are_allowlisted(self):
        _, guest = self.join("Guest", 2)
        self.assertEqual(self.command(self.host, "/kick Guest", 4)[0], 200)
        self.assertIn(guest["member"], S.ROOMS[self.code].members)
        self.assertEqual(self.command(self.host, "/exec anything")[0], 400)
        self.assertEqual(self.command(self.host, "/players")[0], 200)
        self.assertIn("[HOST]", S.ROOMS[self.code].events[-1]["text"])

    def test_frozen_palettes_and_seven_player_limit(self):
        guests = []
        for identity in range(2, 8):
            status, guest = self.join("Guest%d" % identity, identity)
            self.assertEqual(status, 200, guest)
            guests.append(guest)
        self.assertNotEqual(self.join("Eighth", 8)[0], 200)
        status, result = self.call("start", {"v": 5, "room": self.code, "token": self.host["token"]})
        self.assertEqual(status, 200, result)
        room = S.ROOMS[self.code]
        self.assertEqual(room.player_palettes.split(",")[0], "ff0000:00ff00:0000ff:::::")
        self.assertEqual(len(room.player_palettes.split(",")), 7)
        self.assertEqual(room.player_characters, "1,2,3,0,1,2,3")
        self.assertEqual(self.command(self.host, "/kick Guest2")[0], 409)
        room.state = "go"
        self.assertEqual(self.command(self.host, "/kick Guest2")[0], 200)
        self.assertEqual(len(room.members), 6)
        self.assertEqual(room.player_characters, "1,2,3,0,1,2,3")

    def test_malformed_preferences_rejected(self):
        valid = {"v": 5, "room": self.code, "nick": "Guest", "player_id": "2" * 32,
                 "palette": ":::::::", "character": 1}
        for field, bad in (("player_id", "x" * 32), ("palette", "::"),
                           ("palette", "ff0000:::::::extra"), ("character", True),
                           ("character", 4)):
            body = dict(valid); body[field] = bad
            self.assertEqual(self.call("join", body)[0], 400, (field, bad))


if __name__ == "__main__":
    unittest.main()
