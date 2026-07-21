from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path

if "astrbot.api" not in sys.modules:
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")

    class _Logger:
        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    api.logger = _Logger()
    astrbot.api = api
    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api

from astrbot_plugin_Helldivers.api_client import HD2Client
from astrbot_plugin_Helldivers.campaign_trends import CampaignTrendStore
from astrbot_plugin_Helldivers.stats_model import build_stats_view_model
from astrbot_plugin_Helldivers.steam_parser import parse_steam_content
from astrbot_plugin_Helldivers.war_state import WarState, campaign_faction


class ModelTests(unittest.TestCase):
    def test_assignment_normalization_predicate(self) -> None:
        self.assertFalse(HD2Client._looks_like_assignment({}))
        self.assertFalse(HD2Client._looks_like_assignment({"data": []}))
        self.assertTrue(HD2Client._looks_like_assignment({"id": 12}))
        self.assertTrue(HD2Client._looks_like_assignment({"setting": {}}))

    def test_campaign_faction_uses_planet_owner_before_human_campaign(self) -> None:
        campaign = {
            "faction": "Humans",
            "planet": {"currentOwner": "Automaton"},
        }
        self.assertEqual(campaign_faction(campaign), "Automaton")

    def test_defense_progress_uses_event_health(self) -> None:
        campaign = {
            "id": 9,
            "faction": "Humans",
            "planet": {
                "index": 7,
                "name": "Defense",
                "currentOwner": "Humans",
                "health": 1_000,
                "maxHealth": 1_000,
                "event": {
                    "id": 88,
                    "faction": "Terminids",
                    "health": 250,
                    "maxHealth": 1_000,
                },
            },
        }
        row = WarState(campaigns=[campaign]).campaign_rows()[0]
        self.assertTrue(row["is_defense"])
        self.assertAlmostEqual(row["progress"], 75.0)
        self.assertEqual(row["faction"], "Terminids")

    def test_stats_model_uses_mission_time_and_api_accuracy(self) -> None:
        summary = {
            "galaxy_stats": {
                "missionsWon": 9,
                "missionsLost": 1,
                "missionTime": 3_600,
                "timePlayed": 99_999,
                "bulletsFired": 10,
                "bulletsHit": 20,
                "accurracy": 55.5,
                "bugKills": 100,
                "deaths": 10,
            }
        }
        model = build_stats_view_model(summary, status={"time": 86_400})
        stats = model["stats"]
        self.assertEqual(stats["mission_time"], 3_600)
        self.assertEqual(stats["api_accuracy"], 55.5)
        self.assertEqual(model["meta"]["war_day"], 2)

    def test_trend_identity_reset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignTrendStore(
                Path(tmp) / "history.json", min_sample_age_seconds=1
            )
            first = {
                "planet_index": 1,
                "campaign_id": 10,
                "progress": 10,
            }
            store.record_rows([first], timestamp=1_000)
            later = dict(first, progress=13)
            attached = store.attach([later], timestamp=1_600)
            self.assertAlmostEqual(attached[0]["recent_rate_pph"], 18.0)
            changed = dict(later, campaign_id=11, progress=1)
            attached = store.attach([changed], timestamp=2_200)
            self.assertIsNone(attached[0]["recent_rate_pph"])

    def test_steam_parser_extracts_only_official_images(self) -> None:
        parsed = parse_steam_content(
            "[h1]Update[/h1][p]Hello &amp; democracy[/p]"
            "[img]https://clan.steamstatic.com/images/44156989/a.png[/img]"
            "[img]https://example.com/b.png[/img]"
        )
        self.assertIn("Hello & democracy", parsed.plain_text)
        self.assertEqual(len(parsed.image_candidates), 1)
        self.assertIn("steamstatic.com", parsed.image_candidates[0])


if __name__ == "__main__":
    unittest.main()
