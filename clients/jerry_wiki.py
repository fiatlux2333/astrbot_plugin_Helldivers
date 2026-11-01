"""Chinese static Wiki lookup. No MediaWiki or model requests."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import aiohttp

from ..core.plugin_info import USER_AGENT
from ..core.diagnostics import HEALTH


DEFAULT_BASE = "https://jerry114514.github.io/HD2_Wiki/"
SOURCE = "Jerry 中文资料站（CC BY-NC-SA 4.0）"
CATALOGS = {
    "weapon.html": ("weapons.json", "weapons"),
    "stratagem.html": ("stratagems_full.json", "stratagems"),
    "enemy.html": ("enemies.json", "enemies"),
    "booster.html": ("boosters.json", "boosters"),
    "warbond.html": ("warbonds.json", "warbonds"),
    "mission.html": ("missions.json", "categories"),
}
LABELS = {
    "name": "名称", "title": "标题", "heading": "小节", "text": "内容",
    "description": "说明", "overview": "概述", "intro": "介绍", "content": "正文",
    "category": "类别", "subcategory_name": "子类", "category_label": "类别",
    "unlock": "解锁", "traits": "特性", "tips": "提示", "lore": "背景",
    "stats_short": "基础参数", "stats_full": "完整参数", "detailed_stats": "详细参数",
    "damage": "伤害", "capacity": "容量", "penetration": "穿透",
    "fire_rate": "射速", "recoil": "后坐力", "reserve_ammo": "备用弹匣",
    "fire_modes": "射击模式", "ergonomics": "操控", "reload_time": "换弹时间",
    "dps": "每秒伤害", "code": "呼叫代码", "cooldown": "冷却",
    "uses": "使用次数", "call_in_time": "呼叫时间", "health_total": "总生命值",
    "health": "生命值", "armor_level": "护甲", "body_parts": "部位",
    "weak_points": "弱点", "behavior": "行为", "spawn": "出现条件",
    "difficulty": "难度", "minimum_difficulty": "最低难度", "faction": "阵营",
    "faction_label": "阵营", "steps": "步骤", "tactical_info": "战术信息",
    "time_limit": "时限", "price": "价格", "warbond": "战争债券",
    "release_date": "发布日期", "credit_claim": "可领超级货币",
    "sections": "章节", "subsections": "子章节", "items": "条目",
    "tables": "表格", "headers": "列名", "rows": "数据行", "note": "备注",
    "attacks": "攻击", "projectile": "弹丸", "damage_standard": "标准伤害",
    "damage_durable": "耐久伤害", "damage_type": "伤害类型",
    "stagger_threshold": "踉跄阈值", "fire_damage_multiplier": "火焰伤害倍率",
    "recoil_horizontal": "水平后坐力", "recoil_vertical": "垂直后坐力",
    "spread": "散布", "sway": "晃动", "spare_magazines": "备用弹匣",
    "starting_magazines": "初始弹匣", "mags_from_supply": "补给弹匣",
    "mags_from_ammo_box": "弹药箱补充", "type": "类型", "mass": "质量",
    "initial_velocity": "初速", "drag_factor": "阻力系数",
    "gravity_factor": "重力系数", "penetration_slowdown": "穿透减速",
    "pen_direct": "正面穿透", "pen_slight_angle": "小角度穿透",
    "pen_large_angle": "大角度穿透", "pen_extreme_angle": "极限角度穿透",
    "special_effects": "特殊效果", "demolition_force": "拆毁力",
    "stagger_force": "踉跄力", "push_force": "推力", "lifetime": "持续时间",
    "bombs": "每轮弹数", "salvos": "轮数", "bombardment_area": "轰炸范围",
    "location": "位置", "durable": "耐久度", "percent_to_main": "传导至主体",
    "overflow_cap": "溢出上限", "constitution": "体质", "fatal": "致命部位",
    "is_weak_point": "弱点", "count": "数量", "warbond_page": "债券页码",
    "pages": "总页数", "subcategory": "子类", "status_effects": "状态效果",
    "status": "状态", "status_strength": "状态强度", "area_of_effect": "作用范围",
}
SKIP_FIELDS = {
    "id", "part_id", "source", "source_url", "source_page", "wiki_url", "blog_url",
    "image", "image_thumb", "image_local", "icon", "cover_wiki", "files", "links",
    "figures", "guides", "related", "reward_refs", "updated_at", "total",
    "name_en", "title_en", "aliases", "aliases_zh", "fully_translated", "mt",
    "release_status", "name_zh_tbd", "previous", "next", "toc", "level", "depth",
    "warbond_color", "kind",
}
MODEL = re.compile(r"\b[A-Z]+(?:/[A-Z]+)*-?\d+[A-Z0-9]*(?:-[A-Z0-9]+)*\b", re.I)


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"br", "p", "li", "tr", "td", "th", "div"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def clean(value: Any) -> str:
    parser = _Text()
    parser.feed(str(value))
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\s\"'“”‘’!?！？，,。·_-]+", "", value)


def names(row: dict) -> set[str]:
    result: set[str] = set()
    for key in ("name", "name_zh", "name_en", "title", "title_zh", "aliases", "aliases_zh"):
        values = row.get(key) or []
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            continue
        for name in values:
            if not isinstance(name, str):
                continue
            result.add(normalize(name))
            # Keep model suffixes and combination prefixes; never fuzzy-correct models.
            if match := MODEL.match(name):
                result.add(normalize(match.group()))
                if rest := name[match.end():].strip():
                    result.add(normalize(rest))
    return result - {""}


def section_tree(value: Any):
    if isinstance(value, list):
        for node in value:
            yield from section_tree(node)
    elif isinstance(value, dict):
        yield value
        for key in ("sections", "subsections", "sections_zh", "subsections_zh"):
            yield from section_tree(value.get(key))


def merge_chinese(base: dict, overlay: dict) -> dict:
    """Section translations are identities, not parallel array positions."""
    result = copy.deepcopy(base)
    lookup = {str(n["id"]): n for n in section_tree(overlay) if n.get("id")}
    for node in section_tree(result):
        translated = lookup.get(str(node.get("id")), {})
        for key, value in translated.items():
            if key.endswith("_zh") and key not in {"sections_zh", "subsections_zh"}:
                if key == "items_zh" and (
                    not isinstance(value, list)
                    or not isinstance(node.get("items", []), list)
                    or len(value) != len(node.get("items", []))
                ):
                    continue
                node[key] = copy.deepcopy(value)
    for key, value in overlay.items():
        if key.endswith("_zh") and key not in {"sections_zh", "subsections_zh"}:
            result[key] = copy.deepcopy(value)
    return result


def render_detail(row: dict) -> str:
    lines: list[str] = []
    original = False

    def walk(node: Any, prefix: str = "", depth: int = 0):
        nonlocal original
        if depth > 10:
            return
        if isinstance(node, dict):
            headers = node.get("headers_zh") or node.get("headers")
            rows = node.get("rows_zh") or node.get("rows")
            if isinstance(headers, list) and isinstance(rows, list):
                title = node.get("title_zh") or node.get("title") or prefix
                lines.append(clean(title))
                for row in rows:
                    if not isinstance(row, list):
                        continue
                    for i, cell in enumerate(row):
                        label = clean(headers[i]) if i < len(headers) else f"列{i + 1}"
                        walk(cell, label, depth + 1)
                if node.get("note"):
                    walk(node["note"], "备注", depth + 1)
                return
            keys = list(node)
            # Present prose before large parameter tables.
            priority = ("name", "title", "heading", "description", "overview", "intro", "content")
            keys.sort(key=lambda k: priority.index(k.removesuffix("_zh")) if k.removesuffix("_zh") in priority else 99)
            used = set()
            for key in keys:
                root = key.removesuffix("_zh")
                if root in used or root in SKIP_FIELDS or root.endswith(("_url", "_en")):
                    continue
                used.add(root)
                if root == "stats_short" and node.get("stats_full"):
                    continue
                if root == "category" and node.get("category_label"):
                    continue
                if root == "subcategory" and node.get("subcategory_name"):
                    continue
                if root == "html" and isinstance(node[key], str) and "<table" in node[key].lower():
                    lines.append("源站 HTML 表格未展开，请查看词条出处；正文和结构化参数不受影响。")
                    continue
                value = node.get(root + "_zh")
                if value is None or value == "" or value == []:
                    value = node.get(root)
                if value is None or value == "" or value == [] or value == {}:
                    continue
                label = LABELS.get(root, root.replace("_", " "))
                walk(value, f"{prefix} / {label}" if prefix else label, depth + 1)
        elif isinstance(node, list):
            for number, item in enumerate(node, 1):
                walk(item, f"{prefix} {number}", depth + 1)
        else:
            text = clean(node)
            if text:
                if re.search(r"[a-zA-Z]{3}", text) and not re.search(r"[\u3400-\u9fff]", text):
                    original = True
                lines.append(f"{prefix}: {text}" if prefix else text)
    walk(row)
    if original:
        lines.insert(0, "部分字段暂无中文，保留源站原文。")
    return "\n".join(lines)


@dataclass
class QueryState:
    notes: set[str] = field(default_factory=set)


class JerryWikiClient:
    def __init__(
        self, data_dir: Path, *, base_url: str = DEFAULT_BASE,
        page_ttl: int = 21600, search_ttl: int = 1800, timeout: float = 30,
        proxy_url: str = "", search_limit: int = 5,
        extract_chars: int = 900, full_extract_chars: int = 3000,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        parsed = urlsplit(self.base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Jerry Wiki base must be an HTTPS directory URL")
        digest = hashlib.sha256(self.base_url.encode()).hexdigest()[:16]
        self.cache_dir = Path(data_dir) / "jerry_wiki" / digest
        self.page_ttl, self.search_ttl = max(0, page_ttl), max(0, search_ttl)
        self.timeout = max(1, float(timeout))
        self.proxy_url = proxy_url or None
        self.search_limit = max(1, min(10, search_limit))
        self.extract_chars = max(200, min(2000, extract_chars))
        self.full_extract_chars = max(500, min(6000, full_extract_chars))
        self._session = None
        self._tasks: dict[str, asyncio.Task] = {}
        self._waiters: dict[str, int] = {}
        self._memory: dict[str, dict] = {}
        self._backoff: dict[str, float] = {}
        self._semaphore = asyncio.Semaphore(3)
        self._closed = False

    async def close(self) -> None:
        self._closed = True
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._session is not None:
            await self._session.close()

    @staticmethod
    def _validate(file: str, data: Any) -> None:
        if not isinstance(data, dict):
            raise ValueError("Invalid Wiki object")
        if file.startswith("search_"):
            width = 5 if file == "search_index.json" else 4
            docs = data.get("docs")
            if data.get("v") != 1 or not isinstance(data.get("digest"), str) or not isinstance(docs, list) or not docs:
                raise ValueError("Invalid Wiki search index")
            if data.get("count") != len(docs) or len(docs) > 20000:
                raise ValueError("Invalid Wiki index count")
            if any(not isinstance(d, list) or len(d) != width or not all(isinstance(v, str) for v in d) for d in docs):
                raise ValueError("Invalid Wiki index row")
            if any(not d[0].strip() or not d[1].strip() for d in docs):
                raise ValueError("Missing Wiki index identity")
        else:
            keys = {v[0]: v[1] for v in CATALOGS.values()}
            key = keys.get(file)
            if file == "patchnotes.json":
                key = "versions"
            elif file == "patchnotes_zh.json":
                key = "versions_zh"
            elif file.startswith("mechanics/"):
                key = "sections_zh" if file.endswith("_zh.json") else "sections"
            if not key or not isinstance(data.get(key), list):
                raise ValueError("Invalid Wiki category")
            if any(not isinstance(item, dict) for item in data[key]):
                raise ValueError("Invalid Wiki detail row")
            rows = data[key]
            if file == "missions.json":
                if any(not isinstance(c.get("tasks"), list) for c in rows):
                    raise ValueError("Invalid mission category")
                rows = [r for c in rows for r in c["tasks"]]
            if any(not isinstance(r, dict) or not isinstance(r.get("id"), str) or not r["id"] for r in rows):
                raise ValueError("Missing Wiki detail identity")
            if file != "missions.json" and len({r["id"] for r in rows}) != len(rows):
                raise ValueError("Duplicate Wiki detail identity")
            if file.startswith("mechanics/") or file.startswith("patchnotes"):
                for node in section_tree(data[key]):
                    for child_key in ("sections", "subsections", "sections_zh", "subsections_zh"):
                        if child_key in node:
                            children = node[child_key]
                            if not isinstance(children, list) or any(
                                not isinstance(c, dict) or not isinstance(c.get("id"), str) or not c["id"]
                                for c in children
                            ):
                                raise ValueError("Invalid section identity")

    async def _download(self, file: str) -> dict:
        if self._session is None:
            self._session = aiohttp.ClientSession(headers={"User-Agent": USER_AGENT})
        async with self._semaphore:
            async with self._session.get(
                urljoin(self.base_url, "data/wiki/zh/" + file),
                proxy=self.proxy_url, timeout=aiohttp.ClientTimeout(total=min(15, self.timeout)),
                allow_redirects=False,
            ) as response:
                response.raise_for_status()
                if response.status != 200:
                    raise ValueError("Wiki redirects are not accepted")
                content = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    content.extend(chunk)
                    if len(content) > 8 * 1024 * 1024:
                        raise ValueError("Wiki file is too large")
                data = json.loads(content)
                self._validate(file, data)
                return data

    async def _load(self, file: str) -> tuple[dict, bool]:
        if not re.fullmatch(r"(?:mechanics/)?[a-z0-9_]+\.json", file):
            raise ValueError("Invalid static Wiki path")
        key = hashlib.sha256(file.encode()).hexdigest()
        path = self.cache_dir / (key + ".json")
        cached = self._memory.get(file)
        try:
            if cached is None:
                cached = json.loads(path.read_text("utf-8"))
            self._validate(file, cached["data"])
            age = time.time() - float(cached["saved_at"])
            if not 0 <= age <= 7 * 86400:
                cached = None
        except (OSError, ValueError, KeyError, TypeError):
            cached = None
        ttl = self.search_ttl if file.startswith("search_") else self.page_ttl
        if cached is not None:
            self._memory[file] = cached
            if age < ttl:
                return cached["data"], False
        if time.monotonic() < self._backoff.get(file, 0):
            if cached is not None:
                return cached["data"], True
            raise RuntimeError("Wiki source in retry backoff")
        try:
            data = await self._download(file)
        except (aiohttp.ClientError, OSError, ValueError, RuntimeError, TimeoutError) as exc:
            HEALTH.record_fail("wiki", detail=f"Jerry {file}: {type(exc).__name__}")
            self._backoff[file] = time.monotonic() + 60
            if cached is not None:
                return cached["data"], True
            raise
        entry = {"saved_at": time.time(), "data": data}
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        self._memory[file] = entry
        HEALTH.record_ok("wiki", detail=f"Jerry {file}")
        return data, False

    async def _get(self, file: str, state: QueryState) -> dict:
        if self._closed:
            raise RuntimeError("Wiki client is closed")
        task = self._tasks.get(file)
        if task is None:
            task = self._tasks[file] = asyncio.create_task(self._load(file))
        self._waiters[file] = self._waiters.get(file, 0) + 1
        try:
            data, stale = await asyncio.shield(task)
            if stale:
                state.notes.add("源站暂不可用，使用七天内保存的缓存。")
            return data
        finally:
            self._waiters[file] -= 1
            if self._waiters[file] == 0:
                self._waiters.pop(file, None)
                self._tasks.pop(file, None)
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    def _url(self, relative: str) -> str:
        url = urljoin(self.base_url, relative)
        parsed, base = urlsplit(url), urlsplit(self.base_url)
        if parsed.scheme != base.scheme or parsed.netloc != base.netloc or not parsed.path.startswith(base.path):
            raise ValueError("Wiki result is outside configured source")
        return url

    async def _detail(self, doc: list[str], state: QueryState) -> dict:
        parsed = urlsplit(self._url(doc[0]))
        page = parsed.path.rsplit("/", 1)[-1]
        ident = parse_qs(parsed.query).get("id", [""])[0]
        if page in CATALOGS:
            file, key = CATALOGS[page]
            data = await self._get(file, state)
            rows = data[key]
            if page == "mission.html":
                rows = [r for category in rows for r in category.get("tasks", [])]
                # mission.html overwrites the selected task on each ID match.
                rows = list(reversed(rows))
            row = next((r for r in rows if r.get("id") == ident), None)
        elif page in {"mechanic.html", "patchnote.html"}:
            if page == "mechanic.html":
                if not re.fullmatch(r"[a-z0-9_]+", ident):
                    raise ValueError("Invalid mechanic ID")
                file = f"mechanics/{ident}"
                row = await self._get(file + ".json", state)
                overlay_file = file + "_zh.json"
            else:
                data = await self._get("patchnotes.json", state)
                row = next((r for r in data["versions"] if r.get("id") == ident), None)
                overlay_file = "patchnotes_zh.json"
            if row is None:
                raise ValueError("Wiki entry is missing")
            try:
                overlay = await self._get(overlay_file, state)
                if page == "patchnote.html":
                    overlay = next((r for r in overlay["versions_zh"] if r.get("id") == ident), {})
                row = merge_chinese(row, overlay)
                if overlay.get("mt"):
                    state.notes.add("源站中文覆盖标注为机翻，待人工校对。")
            except (aiohttp.ClientError, OSError, ValueError, RuntimeError, TimeoutError):
                state.notes.add("中文覆盖暂不可用，保留源站原文。")
            if parsed.fragment:
                row = next((r for r in section_tree(row) if r.get("id") == unquote(parsed.fragment)), None)
        else:
            raise ValueError("Unsupported Wiki detail type")
        if not isinstance(row, dict):
            raise ValueError("Wiki detail is missing")
        return row

    async def query(self, query: str, *, full: bool = False) -> str:
        state = QueryState()
        try:
            async with asyncio.timeout(self.timeout):
                return await self._query(query.strip(), full, state)
        except (aiohttp.ClientError, OSError, ValueError, RuntimeError, TimeoutError):
            return "Wiki 中文源暂不可用，请稍后重试；未查询其他数据源。"

    async def _query(self, query: str, full: bool, state: QueryState) -> str:
        if not normalize(query) or len(query) > 160 or "\x00" in query:
            return "请输入 1–160 字的 Wiki 关键词。"
        results = await asyncio.gather(
            self._get("search_entries.json", state),
            self._get("search_index.json", state),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result
        entries, index = results
        # A deployment may expose mismatched versions briefly. Never mix their rows.
        if entries["digest"] != index["digest"]:
            state.notes.add("索引版本暂不一致，本次仅使用完整正文索引。")
        docs = index["docs"]
        allowed = []
        for doc in docs:
            try:
                self._url(doc[0])
            except ValueError:
                continue
            if doc[2] not in {"文档", "首页"}:
                allowed.append(doc)
        titles: dict[str, int] = {}
        for doc in allowed:
            titles[doc[1]] = titles.get(doc[1], 0) + 1

        def selection(doc: list[str]) -> str:
            if titles[doc[1]] == 1:
                return doc[1]
            parsed = urlsplit(doc[0])
            ident = parse_qs(parsed.query).get("id", [""])[0]
            location = ident + ("#" + unquote(parsed.fragment) if parsed.fragment else "")
            return f"{doc[1]}（{doc[3]}；{location}）"

        q = normalize(query)
        exact: dict[str, list[str]] = {}
        candidates: dict[str, list[str]] = {}
        for doc in allowed:
            identity = doc[0] + "\n" + doc[1]
            if q in {normalize(selection(doc)), normalize(doc[1]), normalize(doc[1].split("›")[-1])}:
                exact[identity] = doc
            if q in normalize(" ".join(doc[1:])):
                candidates[identity] = doc
        # Category names/aliases are authoritative; the index concatenates both languages.
        catalog_results = await asyncio.gather(
            *(self._get(file, state) for file, _ in CATALOGS.values()),
            return_exceptions=True,
        )
        for (page, (_, key)), data in zip(CATALOGS.items(), catalog_results):
            if isinstance(data, BaseException):
                if isinstance(data, asyncio.CancelledError):
                    raise data
                state.notes.add("部分分类暂不可用，搜索结果可能不完整。")
                continue
            rows = data[key]
            if page == "mission.html":
                rows = [r for category in rows for r in category.get("tasks", [])]
            by_id = {str(r.get("id")): r for r in rows if isinstance(r, dict)}
            for doc in allowed:
                parsed = urlsplit(doc[0])
                if parsed.path.rsplit("/", 1)[-1] != page:
                    continue
                row = by_id.get(parse_qs(parsed.query).get("id", [""])[0])
                if row is not None and q in names(row):
                    exact[doc[0] + "\n" + doc[1]] = doc
        if len(exact) == 1:
            doc = next(iter(exact.values()))
            try:
                body = render_detail(await self._detail(doc, state))
                if not body:
                    raise ValueError("Empty detail")
            except (aiohttp.ClientError, OSError, ValueError, RuntimeError, TimeoutError):
                body = "索引摘录（详情暂不可用或尚不支持，不是完整正文）：\n" + doc[4]
            limit = self.full_extract_chars if full else self.extract_chars
            if len(body) > limit:
                body = body[:limit - 12].rstrip() + "\n（内容已截断）"
            lines = [
                f"Wiki {'详细内容' if full else '摘要'} | {doc[1]}", body,
                *sorted(state.notes), f"出处：{self._url(doc[0])}", f"来源：{SOURCE}",
            ]
            if not full:
                lines.append("加 -f 查看详细内容。")
            return "\n".join(lines)
        matches = list(exact.values()) if exact else sorted(
            candidates.values(),
            key=lambda d: (q not in normalize(d[1]), len(d[1]), d[1]),
        )
        lines = [f"Wiki 搜索 | {query}"]
        if matches:
            lines.append("找到多个或相关条目，请使用完整标题选择：")
            for doc in matches[:self.search_limit]:
                lines.append(f"/wiki {selection(doc)}")
            if len(matches) > self.search_limit:
                lines.append(f"另有 {len(matches) - self.search_limit} 条，请缩小关键词范围。")
        else:
            lines.append("未找到相关词条。" if not state.notes else "当前可用数据中未找到匹配，不能确认全站无结果。")
        lines.extend(sorted(state.notes))
        lines.append(f"来源：{SOURCE}")
        return "\n".join(lines)
