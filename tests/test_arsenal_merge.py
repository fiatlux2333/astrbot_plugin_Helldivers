"""Equipment identities, numerical meaning and user-visible search behavior."""

from __future__ import annotations

import asyncio
import copy
import tempfile
import unittest
from unittest.mock import AsyncMock

from astrbot_plugin_Helldivers.clients.arsenal_client import ArsenalClient
from astrbot_plugin_Helldivers.core.arsenal_merge import merge_equipment
from astrbot_plugin_Helldivers.renderers.card_specs import build_arsenal_card


def converted(collection, **raw):
    return ArsenalClient._dionatha_to_item(collection, raw, "2026-11-06.test", {})


class MergeTests(unittest.TestCase):
    def test_names_and_aliases_resolve_to_one_record_with_updated_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = ArsenalClient(tmp)
            client._data_version = "2026.08.14.1"
            old = {
                "id": "ar-11",
                "nameEn": "AR-11 Test",
                "nameZh": "测试步枪",
                "model": "AR-11",
                "productKind": "primary-weapon",
                "handling": {"recoil": 5},
            }
            client._items = [old]
            client._aliases = {"ar-11": ["测试俗称"]}
            client._dionatha_items = [
                converted(
                    "weapons",
                    id="ar-11",
                    name="AR-11 Test",
                    category="primary",
                    firearm={"recoil": 0},
                )
            ]
            client._build_index()
            entries = [
                client.search(q)[0]
                for q in ("测试步枪", "AR-11 Test", "AR-11", "测试俗称")
            ]
            self.assertTrue(all(entry is entries[0] for entry in entries))
            self.assertEqual(entries[0]["handling"]["recoil"], 0)
            self.assertEqual(old["handling"]["recoil"], 5)
            self.assertIn("dionatha", entries[0]["_field_sources"]["handling.recoil"])

    def test_armor_helmet_twins_are_separate_and_selectable(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = ArsenalClient(tmp)
            client._items = [
                {
                    "id": "a-35",
                    "nameZh": "侦察者",
                    "nameEn": "A-35 Recon",
                    "productKind": "body-armor",
                }
            ]
            client._dionatha_items = [
                converted(c, id="a-35", name="A-35 Recon")
                for c in ("armors", "helmets")
            ]
            client._build_index()
            results = client.search("A-35 Recon")
            self.assertEqual(
                {r["productKind"] for r in results}, {"body-armor", "helmet"}
            )
            self.assertEqual(
                client.search("A-35 Recon 头盔")[0]["productKind"], "helmet"
            )
            self.assertEqual(
                client.search("侦察者 护甲")[0]["productKind"], "body-armor"
            )
            self.assertEqual(len(client._merged_items), 2)

    def test_upgraded_duration_is_not_mistaken_for_base_duration(self):
        old = {
            "id": "meltagun",
            "productKind": "support-weapon",
            "deployment": {"cooldownSeconds": 410},
        }
        fresh = converted(
            "stratagems",
            id="meltagun",
            name="40-K Meltagun",
            kind="support_weapon",
            cooldownS=480,
            callInTimeS=0,
            statsRaw={"General › Cooldown › With All Upgrades": "410.4 seconds"},
        )
        result = merge_equipment([old], [fresh], "2026.08.14.1")[0]
        self.assertEqual(result["deployment"]["cooldownSeconds"], 480)
        self.assertEqual(result["deployment"]["upgradedCooldownSeconds"], 410.4)
        self.assertTrue(result["_conflicts"][0]["resolved_upgrade"])
        card = build_arsenal_card(result)
        pairs = dict(
            pair for e in card.elements if e["type"] == "grid" for pair in e["pairs"]
        )
        self.assertEqual(pairs["基础冷却"], "480s")
        self.assertEqual(pairs["全升级冷却"], "410.4s")
        self.assertEqual(pairs["基础呼叫"], "0s")

    def test_null_is_not_missing_and_zero_is_not_empty(self):
        old = {
            "id": "gun",
            "productKind": "primary-weapon",
            "handling": {"magazine": 7, "recoil": 3, "spareMagazines": 4},
        }
        new = converted(
            "weapons",
            id="gun",
            name="Gun",
            category="primary",
            firearm={"capacity": None, "recoil": 0},
        )
        result = merge_equipment([old], [new], "2026.08.14.1")[0]
        self.assertIsNone(result["handling"]["magazine"])
        self.assertEqual(result["handling"]["recoil"], 0)
        self.assertEqual(result["handling"]["spareMagazines"], 4)
        pairs = dict(
            pair
            for e in build_arsenal_card(result).elements
            if e["type"] == "grid"
            for pair in e["pairs"]
        )
        self.assertEqual(pairs["后坐力"], "0")
        self.assertNotIn("弹匣", pairs)

    def test_heat_capacity_quality_flags_and_multiple_fire_rates_survive(self):
        raw = {
            "id": "gun",
            "name": "Gun",
            "category": "primary",
            "firearm": {"capacity": None, "fireRateRpm": [450, 900]},
            "statsRaw": {"Traits": "Light Armor Penetrating • Heat"},
            "wiki": {"flags": ["potentially_outdated"]},
        }
        item = converted("weapons", **raw)
        self.assertEqual(item["handling"]["fireRate"], [450, 900])
        self.assertIsNone(item["handling"]["magazine"])
        card = build_arsenal_card(item)
        self.assertTrue(any("可能尚未更新" in e.get("text", "") for e in card.elements))
        pairs = dict(
            pair for e in card.elements if e["type"] == "grid" for pair in e["pairs"]
        )
        self.assertIn("热量武器", pairs["弹药机制"])
        self.assertEqual(pairs["射速"], "450/900 RPM")

    def test_older_supplement_does_not_roll_back_newer_primary_stats(self):
        old = {"id": "gun", "productKind": "primary-weapon", "handling": {"recoil": 1}}
        new = converted(
            "weapons",
            id="gun",
            name="Gun",
            category="primary",
            firearm={"recoil": 5, "capacity": 30},
        )
        result = merge_equipment([old], [new], "2026.11.07.1")[0]
        self.assertEqual(result["handling"], {"recoil": 1, "magazine": 30})
        self.assertIn("缺项补充", result["_footer"])

    def test_ambiguous_same_category_ids_are_not_silently_merged(self):
        old = {"id": "gun", "productKind": "primary-weapon"}
        first = converted("weapons", id="gun", name="Variant A", category="primary")
        second = copy.deepcopy(first)
        second["nameEn"] = "Variant B"
        self.assertEqual(
            len(merge_equipment([old], [first, second], "2026.08.14.1")), 3
        )


class RefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_admin_refresh_is_coalesced(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = ArsenalClient(tmp)
            gate = asyncio.Event()

            async def refresh():
                await gate.wait()
                return ["done"]

            client._refresh_sources = AsyncMock(side_effect=refresh)
            first = asyncio.create_task(client.refresh_all())
            second = asyncio.create_task(client.refresh_all())
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            gate.set()
            self.assertEqual(await first, ["done"])
            self.assertEqual(await second, ["done"])
            client._refresh_sources.assert_awaited_once()
            await client.stop()


class NumericalConditionsTests(unittest.TestCase):
    def test_filling_callin_does_not_relabel_old_cooldown_as_base(self):
        old = {
            "id": "test",
            "productKind": "other-stratagem",
            "deployment": {"cooldownSeconds": 410},
        }
        new = converted(
            "stratagems", id="test", name="Test", kind="orbital", callInTimeS=0
        )
        result = merge_equipment([old], [new], "2026.08.14.1")[0]
        pairs = dict(
            pair
            for e in build_arsenal_card(result).elements
            if e["type"] == "grid"
            for pair in e["pairs"]
        )
        self.assertEqual(pairs["冷却（条件未注明）"], "410s")
        self.assertEqual(pairs["基础呼叫"], "0s")

    def test_beam_and_pellet_damage_units_are_not_lost(self):
        for kind, extra, expected in (
            ("beam", {"statsRaw": {"Standard Damage": "2,600 DPS"}}, " /秒"),
            ("projectile", {}, "每发 9 弹丸"),
        ):
            with self.subTest(kind=kind):
                item = converted(
                    "weapons",
                    id="gun",
                    name="Gun",
                    category="primary",
                    attacks=[
                        {
                            "kind": kind,
                            "damage": {"standard": 2600},
                            "projectile": {"pellets": 9}
                            if kind == "projectile"
                            else None,
                        }
                    ],
                    **extra,
                )
                card = build_arsenal_card(item)
                self.assertIn(expected, str(card.elements))
