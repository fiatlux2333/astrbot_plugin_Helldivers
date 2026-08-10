from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from astrbot_plugin_Helldivers.campaign_trends import estimate_campaign_result
from astrbot_plugin_Helldivers.i18n import (
    format_dss_action,
    format_faction,
    format_planet,
    format_status,
)
from astrbot_plugin_Helldivers.map_renderer import MapRenderer
from astrbot_plugin_Helldivers.visual_assets import asset_image, asset_sha256
from astrbot_plugin_Helldivers.war_state import faction_cn


class LocalizationAssetTests(unittest.TestCase):
    def test_user_assets_resolve_without_implicit_cropping(self) -> None:
        expected = {
            "emblems/super_earth.png": (235, 294),
            "dss/dss_wireframe.png": (925, 769),
            "user/map.png": (1149, 1149),
            "global_events/super_earth_flag.png": (752, 348),
            "user/map_template.png": (1024, 1024),
            "user/warfront_template.png": (1024, 1002),
            "emblems/terminids.png": (512, 512),
            "emblems/automaton.png": (512, 512),
            "emblems/illuminate.png": (512, 512),
        }
        for key, size in expected.items():
            with self.subTest(asset=key):
                image = asset_image(key)
                self.assertIsNotNone(image)
                assert image is not None
                self.assertEqual(image.size, size)
                self.assertEqual(image.mode, "RGBA")
                self.assertEqual(len(asset_sha256(key)), 64)
                image.close()

    def test_faction_and_status_terms_are_chinese(self) -> None:
        self.assertEqual(format_faction("Terminids"), "终结族")
        self.assertEqual(faction_cn("Terminids"), "终结族")
        self.assertEqual(format_faction("Automaton"), "机器人")
        self.assertEqual(format_faction("Illuminate"), "光能族")
        self.assertEqual(format_status("active"), "活跃")

    def test_official_planets_and_dss_actions_are_localized(self) -> None:
        self.assertEqual(format_planet("Heeth"), "希斯")
        self.assertEqual(format_planet("Klen Dahth II"), "克伦达斯II")
        self.assertEqual(format_planet("Gaellivare", "未知星球"), "耶利瓦勒")
        self.assertEqual(format_planet("Wezen"), "弧矢一")
        self.assertEqual(format_dss_action("Eagle Storm"), "飞鹰风暴")
        self.assertEqual(format_dss_action("Orbital Blockade"), "轨道封锁")
        self.assertEqual(
            format_dss_action("Heavy Ordnance Distribution"), "重型军械分发"
        )

    def test_dss_tactical_icons_resolve(self) -> None:
        for key in (
            "tactical/eagle_storm.png",
            "tactical/orbital_blockade.png",
            "tactical/heavy_ordnance.png",
        ):
            with self.subTest(asset=key):
                image = asset_image(key)
                self.assertIsNotNone(image)
                assert image is not None
                self.assertEqual(image.size, (512, 512))
                image.close()

    def test_campaign_estimates_are_chinese(self) -> None:
        advancing = estimate_campaign_result(
            {"progress": 50, "recent_rate_pph": 5}, now=1_000
        )
        losing = estimate_campaign_result(
            {"progress": 50, "recent_rate_pph": -1}, now=1_000
        )
        waiting = estimate_campaign_result(
            {"progress": 50, "recent_rate_pph": None}, now=1_000
        )
        self.assertIn("后解放", advancing["estimated_result"])
        self.assertEqual(losing["estimated_result"], "正在失守")
        self.assertEqual(waiting["estimated_result"], "等待趋势")

    def test_map_fingerprint_changes_with_reference_asset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            renderer = MapRenderer(Path(tmp))
            first = renderer._fingerprint([], "银河战争地图", "")
            second = renderer._fingerprint([], "银河战争地图", "")
            self.assertEqual(first, second)
            self.assertEqual(len(first), 20)


if __name__ == "__main__":
    unittest.main()
