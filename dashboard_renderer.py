"""GWW / Helldivers Companion style galactic overview renderer."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageDraw
except Exception:  # pragma: no cover
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore

try:
    from .hud_theme import (
        BG,
        CYAN,
        FACTION,
        MUTED,
        TEXT,
        glass_panel,
        paste_emblem,
        progress_bar,
        vertical_gradient,
        add_stars,
        circuit_header,
    )
    from .i18n import format_planet
    from .visual_assets import font, text_width, ellipsize
except Exception:  # pragma: no cover
    format_planet = lambda value, default=None: default or str(value)  # type: ignore

    def font(size: int, *, bold: bool = False):
        from PIL import ImageFont

        return ImageFont.load_default()

    def text_width(draw, text, fnt):
        try:
            return draw.textlength(text, font=fnt)
        except Exception:
            return len(text) * 8

    def ellipsize(draw, text, fnt, max_width):
        out = str(text)
        while out and text_width(draw, out + "…", fnt) > max_width:
            out = out[:-1]
        return out + "…" if out != text else out


class DashboardRenderer:
    VERSION = "hud3"

    def __init__(self, output_dir: Path, *, width: int = 980) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.width = max(900, int(width))

    @property
    def available(self) -> bool:
        return Image is not None

    @staticmethod
    def _remaining(value: Any) -> str:
        if not value:
            return ""
        try:
            from datetime import datetime, timezone

            s = str(value).replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            seconds = int((dt - datetime.now(timezone.utc)).total_seconds())
            if seconds <= 0:
                return "已结束"
            days, seconds = divmod(seconds, 86400)
            hours, seconds = divmod(seconds, 3600)
            minutes = seconds // 60
            if days:
                return f"{days}天{hours}小时"
            if hours:
                return f"{hours}小时{minutes}分"
            return f"{minutes}分钟"
        except Exception:
            return ""

    def _section_height(self, rows: list[dict[str, Any]], low: list | None = None) -> int:
        shown = max(1, len(rows))
        return 92 + shown * 62 + (36 if low else 0)

    def _draw_header(self, image, draw, subtitle: str) -> int:
        w = self.width
        circuit_header(image, (18, 16, w - 18, 92), CYAN)
        paste_emblem(image, "emblems/super_earth.png", (34, 28, 52, 52))
        draw.text((100, 30), "银河总览", font=font(30, bold=True), fill=TEXT)
        draw.text(
            (102, 66),
            subtitle or "银河战争总览",
            font=font(14),
            fill=MUTED,
        )
        return 110

    def _draw_panel(
        self,
        image,
        draw,
        y: int,
        *,
        title: str,
        color: tuple[int, int, int],
        emblem_key: str,
        rows: list[dict[str, Any]],
        low: list[dict[str, Any]] | None = None,
        subtitle: str = "",
    ) -> int:
        h = self._section_height(rows, low)
        x, w = 18, self.width - 36
        glass_panel(image, (x, y, x + w, y + h), accent=color)
        draw = ImageDraw.Draw(image, "RGBA")
        draw.text((x + 22, y + 14), title, font=font(22, bold=True), fill=TEXT)
        if subtitle:
            draw.text((x + 24, y + 44), subtitle, font=font(13), fill=MUTED)
        paste_emblem(image, emblem_key, (x + w - 86, y + 10, 68, 68), opacity=0.92)

        row_y = y + 78
        usable = w - 48
        for row in rows:
            name = format_planet(row.get("name"), "未知星球")
            players = int(row.get("players") or 0)
            pct = max(0.0, min(100.0, float(row.get("progress") or 0.0)))
            ends = self._remaining(row.get("ends"))
            rate = row.get("recent_rate")
            result = str(row.get("estimated_result") or "")
            meta = f"在线 {players:,}"
            if ends:
                meta += f"  ·  {ends}"
            if rate is not None:
                try:
                    meta += f"  ·  {float(rate):+.2f}%/小时"
                except (TypeError, ValueError):
                    pass
            if result:
                meta += f"  ·  {result}"
            draw.text(
                (x + 24, row_y),
                ellipsize(draw, name, font(17, bold=True), 420),
                font=font(17, bold=True),
                fill=TEXT,
            )
            pct_text = f"{pct:.2f}%"
            pw = text_width(draw, pct_text, font(16, bold=True))
            draw.text((x + w - 24 - pw, row_y), pct_text, font=font(16, bold=True), fill=color)
            draw.text((x + 24, row_y + 24), meta, font=font(12), fill=MUTED)
            progress_bar(draw, (x + 24, row_y + 44, x + usable, row_y + 44), pct, accent=color, height=8)
            row_y += 62

        if not rows:
            draw.text((x + 24, row_y), "当前没有相关战役", font=font(14), fill=MUTED)

        if low:
            names = " · ".join(
                f"{format_planet(r.get('name'), '?')} {int(r.get('players') or 0):,}"
                for r in low[:8]
            )
            draw.text(
                (x + 24, y + h - 28),
                ellipsize(draw, f"低影响战役  {names}", font(12), w - 50),
                font=font(12),
                fill=DIM if (DIM := (90, 115, 135)) else MUTED,
            )
        return y + h + 12

    def _dss_panel(self, image, draw, y: int, sections: dict[str, Any]) -> int:
        dss = sections.get("dss") or {}
        planet = sections.get("dss_planet") or {}
        actions = [a for a in dss.get("tacticalActions") or [] if isinstance(a, dict)]
        active = []
        for action in actions:
            try:
                if int(action.get("status") or 0) == 2:
                    active.append(
                        str(action.get("display_name") or action.get("name") or "战术行动")
                    )
            except (TypeError, ValueError):
                continue
        election = self._remaining(dss.get("electionEnd"))
        rows = [
            {
                "name": format_planet(
                    planet.get("name") or dss.get("planetName"), "未知位置"
                ),
                "players": ((planet.get("statistics") or {}).get("playerCount") or 0),
                "progress": 100,
                "estimated_result": "、".join(active) if active else "无进行中战术",
                "ends": dss.get("electionEnd"),
            }
        ]
        subtitle = f"民主空间站 · 下次跃迁 {election or '未知'}"
        return self._draw_panel(
            image,
            draw,
            y,
            title="民主空间站",
            color=FACTION["DSS"],
            emblem_key="emblems/dss.png",
            rows=rows,
            subtitle=subtitle,
        )

    def render(self, sections: dict[str, Any], *, subtitle: str = "") -> Path | None:
        if not self.available:
            return None
        urgent = list(sections.get("urgent") or [])[:5]
        defending = list(sections.get("defending") or [])[:5]
        attacking = sections.get("attacking") or {}

        specs: list[tuple[str, tuple[int, int, int], str, list, list]] = []
        if urgent:
            specs.append(("紧急解放行动", FACTION["Urgent"], "emblems/defense.png", urgent, []))
        if defending:
            specs.append(("防御中", FACTION["Defense"], "emblems/defense.png", defending, []))
        for faction, title, key in (
            ("Automaton", "进攻中 · 机器人", "emblems/automaton.png"),
            ("Terminids", "进攻中 · 终结族", "emblems/terminids.png"),
            ("Illuminate", "进攻中 · 光能族", "emblems/illuminate.png"),
        ):
            block = attacking.get(faction) or {}
            main = list(block.get("main") or [])[:8]
            low = list(block.get("low") or [])
            if main or low:
                specs.append((title, FACTION[faction], key, main, low))

        height = 130
        if sections.get("dss"):
            height += self._section_height([{}]) + 12
        height += sum(self._section_height(rows, low) + 12 for _, _, _, rows, low in specs)
        height += 70

        image = vertical_gradient((self.width, height), (8, 16, 28), (3, 6, 12)).convert("RGBA")
        add_stars(image, 160, seed=11)
        draw = ImageDraw.Draw(image, "RGBA")
        y = self._draw_header(image, draw, subtitle)
        if sections.get("dss"):
            y = self._dss_panel(image, draw, y, sections)
        for title, color, emblem, rows, low in specs:
            total_players = sum(int(r.get("players") or 0) for r in rows + low)
            total = max(1, int(sections.get("total_players") or total_players))
            sub = f"{total_players:,} 名绝地潜兵 · 占活跃兵力 {total_players / total * 100:.1f}%"
            y = self._draw_panel(
                image,
                draw,
                y,
                title=title,
                color=color,
                emblem_key=emblem,
                rows=rows,
                low=low,
                subtitle=sub,
            )

        total = int(sections.get("total_players") or 0)
        footer = f"活跃绝地潜兵总数  {total:,}   ·   api.helldivers2.dev"
        draw.line((28, y + 8, self.width - 28, y + 8), fill=(50, 72, 92, 180), width=1)
        draw.text((30, y + 24), footer, font=font(14), fill=MUTED)

        out = self.output_dir / (
            f"dashboard_{self.VERSION}_{int(time.time())}_{uuid.uuid4().hex[:8]}.png"
        )
        tmp = out.with_suffix(".tmp.png")
        image.convert("RGB").save(tmp, format="PNG", optimize=True)
        tmp.replace(out)
        return out
