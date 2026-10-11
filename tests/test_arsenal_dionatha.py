"""dionatha 补充目录（wiki.gg）转换与索引合并的单元测试。"""

from __future__ import annotations

import asyncio
import unittest

from astrbot_plugin_Helldivers.clients.arsenal_client import (
    ArsenalClient,
    _DIONATHA_PEN_MAP,
)


def _weapon() -> dict:
    return {
        "id": "ar-11-arbitrator",
        "slug": "ar-11-arbitrator",
        "name": "AR-11 Arbitrator",
        "upcoming": False,
        "aliases": ["arbiter"],
        "description": "Primary assault rifle with underslung shotgun.",
        "wiki": {"url": "https://helldivers.wiki.gg/wiki/AR-11_Arbitrator"},
        "category": "primary",
        "subcategory": "assault_rifle",
        "firearm": {
            "fireRateRpm": [1200],
            "capacity": 45,
            "spareMagazines": 7,
            "recoil": 13.25,
            "firingModes": ["auto", "burst"],
            "reloadTimeS": 3.75,
        },
        "attacks": [
            {
                "name": "AR-11 P",
                "kind": "projectile",
                "damage": {"standard": 70, "durable": 20, "type": "Ballistic"},
                "penetration": {"direct": "light"},
                "forces": {"demolition": 10, "stagger": 15, "push": 12},
            }
        ],
    }


def _convert(collection: str, raw: dict) -> dict:
    return ArsenalClient._dionatha_to_item(collection, raw, "2026-10-04.1", {})


class DionathaConvertTests(unittest.TestCase):
    def test_weapon_converts_to_hd2tool_shape(self) -> None:
        item = _convert("weapons", _weapon())
        self.assertEqual(item["id"], "dionatha:ar-11-arbitrator")
        self.assertEqual(item["productKind"], "primary-weapon")
        self.assertEqual(item["nameZh"], "")
        self.assertEqual(item["model"], "AR-11")
        self.assertEqual(item["weaponType"], "Assault Rifle")
        self.assertEqual(item["alternateNames"], ["arbiter"])
        self.assertIn("dionatha", item["_footer"])
        combat = item["combat"]
        fields = combat["components"][0]["fields"]
        self.assertEqual(fields["standardDamage"], 70)
        self.assertEqual(fields["durableDamage"], 20)
        # light → 护甲等级 2（轻型）
        self.assertEqual(fields["armorPenetration"]["value"], 2)
        self.assertEqual(fields["armorPenetration"]["labelZh"], "轻型")
        self.assertEqual(fields["demolitionForce"], 10)
        handling = item["handling"]
        self.assertEqual(handling["magazine"], 45)
        self.assertEqual(handling["fireRate"], 1200)
        self.assertEqual(handling["firingModes"], ["Auto", "Burst"])
        self.assertEqual(handling["reloadSeconds"], 3.75)

    def test_pen_map_covers_game_tiers(self) -> None:
        self.assertEqual(_DIONATHA_PEN_MAP["unarmored"], 0)
        self.assertEqual(_DIONATHA_PEN_MAP["very_light"], 1)
        self.assertEqual(_DIONATHA_PEN_MAP["medium"], 3)
        self.assertEqual(_DIONATHA_PEN_MAP["heavy"], 4)
        self.assertEqual(_DIONATHA_PEN_MAP["anti_tank_iii"], 7)

    def test_unknown_penetration_keeps_raw_label(self) -> None:
        raw = _weapon()
        raw["attacks"][0]["penetration"] = {"direct": "weird_future_tier"}
        item = _convert("weapons", raw)
        pen = item["combat"]["components"][0]["fields"]["armorPenetration"]
        self.assertIsNone(pen["value"])
        self.assertEqual(pen["labelZh"], "weird_future_tier")

    def test_stratagem_maps_deployment(self) -> None:
        raw = {
            "id": "40-k-meltagun",
            "slug": "40-k-meltagun",
            "name": "40-K Meltagun",
            "kind": "support_weapon",
            "code": ["down", "left", "up"],
            "cooldownS": 480,
            "callInTimeS": 7.75,
            "attacks": [
                {
                    "kind": "beam",
                    "damage": {"standard": 2600, "type": "Laser"},
                    "penetration": {"direct": "anti_tank_iii"},
                    "forces": {},
                }
            ],
        }
        item = _convert("stratagems", raw)
        self.assertEqual(item["productKind"], "support-weapon")
        deployment = item["deployment"]
        self.assertEqual(deployment["cooldownSeconds"], 480)
        self.assertEqual(deployment["code"], ["down", "left", "up"])
        fields = item["combat"]["components"][0]["fields"]
        self.assertEqual(fields["armorPenetration"]["value"], 7)
        self.assertEqual(fields["armorPenetration"]["labelZh"], "坦克 III")

    def test_armor_resolves_passive_name(self) -> None:
        raw = {
            "id": "a-35-recon",
            "slug": "a-35-recon",
            "name": "A-35 Recon",
            "armorRating": 100,
            "speed": 500,
            "staminaRegen": 100,
            "passiveId": "scout",
        }
        item = ArsenalClient._dionatha_to_item(
            "armors", raw, "v1", {"scout": "侦察兵"}
        )
        self.assertEqual(item["productKind"], "body-armor")
        self.assertEqual(item["armor"]["rating"], 100)
        self.assertEqual(item["armor"]["passive"], "侦察兵")

    def test_explosion_area_radii_are_mapped(self) -> None:
        raw = {
            "id": "ac-8-autocannon-sentry",
            "slug": "ac-8-autocannon-sentry",
            "name": "A/AC-8 Autocannon Sentry",
            "kind": "sentry",
            "attacks": [
                {
                    "kind": "projectile",
                    "damage": {"standard": 70, "type": "Ballistic"},
                    "penetration": {"direct": "medium"},
                    "area": {"innerRadiusM": 2, "outerRadiusM": 6, "shockwaveRadiusM": 8},
                    "forces": {},
                }
            ],
        }
        item = _convert("stratagems", raw)
        fields = item["combat"]["components"][0]["fields"]
        self.assertEqual(fields["innerRadius"], 2)
        self.assertEqual(fields["outerRadius"], 6)
        # shockwaveRadiusM 无对应 HD2Tool 字段，不进卡片
        self.assertNotIn("shockwaveRadiusM", fields)

    def test_invalid_rows_return_none(self) -> None:
        self.assertIsNone(_convert("weapons", {"name": "", "slug": "x"}))
        self.assertIsNone(_convert("weapons", {"name": "X", "slug": ""}))


class DionathaIndexTests(unittest.TestCase):
    def _client(self) -> ArsenalClient:
        client = ArsenalClient.__new__(ArsenalClient)
        client._items = []
        client._aliases = {}
        client._dionatha_items = [
            _convert("weapons", _weapon()),
            _convert(
                "armors",
                {
                    "id": "a-35-recon",
                    "slug": "a-35-recon",
                    "name": "A-35 Recon",
                    "passiveId": "scout",
                },
            ),
        ]
        client._index = {}
        client._build_index()
        return client

    def test_search_hits_supplemental_items(self) -> None:
        client = self._client()
        # 完整名 / 规范化 / 前缀 / 俗称 多路都应命中补充条目
        for query in ("AR-11 Arbitrator", "ar11arbitrator", "AR-11", "arbiter"):
            with self.subTest(query=query):
                results = client.search(query)
                self.assertTrue(results)
                self.assertEqual(results[0]["id"], "dionatha:ar-11-arbitrator")

    def test_hd2tool_items_win_key_collisions(self) -> None:
        client = self._client()
        hd2 = {"id": "ar-11-arbitrator", "nameEn": "AR-11 Arbitrator",
               "nameZh": "仲裁者", "productKind": "primary-weapon"}
        client._items = [hd2]
        client._build_index()
        results = client.search("AR-11 Arbitrator")
        self.assertEqual(results[0], hd2)


if __name__ == "__main__":
    unittest.main()
