"""Validate persistent push subscriptions against the connected QQ account."""

from __future__ import annotations

import asyncio
from typing import Any

from astrbot.api import logger
from astrbot.core.platform.message_session import MessageSesion
from astrbot.core.platform.message_type import MessageType


def normalize_sessions(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(
        dict.fromkeys(x.strip() for x in value if isinstance(x, str) and x.strip())
    )


def group_session(origin: str) -> tuple[str, str] | None:
    """Resolve a group UMO, including OneBot's sender_group unique sessions."""
    try:
        session = MessageSesion.from_str(origin)
    except (TypeError, ValueError):
        return None
    if session.message_type != MessageType.GROUP_MESSAGE:
        return None
    group_id = session.session_id
    sender, separator, suffix = group_id.rpartition("_")
    if (
        separator
        and sender.isascii()
        and sender.isdigit()
        and suffix.isascii()
        and suffix.isdigit()
    ):
        group_id = suffix
    return session.platform_name, group_id


def has_group_subscription(sessions: list[str], origin: str) -> bool:
    """Group pushes share one subscription across OneBot's per-user sessions."""
    key = group_session(origin)
    return origin in sessions or (
        key is not None and any(group_session(value) == key for value in sessions)
    )


def subscription_targets(
    sessions: list[str], target: str, current_origin: str
) -> list[str]:
    """Match a full group UMO or a group number on the caller's platform."""
    value = target.strip()
    if ":" in value:
        if group_session(value) is None:
            raise ValueError("请填写完整群会话标识（平台ID:GroupMessage:会话ID）。")
        return [value] if value in sessions else []
    if not value.isascii() or not value.isdigit() or int(value) <= 0:
        raise ValueError("请填写群号或完整群会话标识。")
    try:
        platform_id = MessageSesion.from_str(current_origin).platform_name
    except (TypeError, ValueError) as exc:
        raise ValueError("无法识别当前平台，请使用完整群会话标识。") from exc
    return [
        origin for origin in sessions if group_session(origin) == (platform_id, value)
    ]


class QQGroupSubscriptionChecker:
    """Reconcile OneBot v11 groups only after fresh data and online confirmation."""

    def __init__(self, context: Any, timeout: float = 10.0) -> None:
        self.context = context
        self.timeout = timeout
        self._warned_platforms: set[str] = set()

    async def removed_sessions(self, sessions: list[str]) -> set[str]:
        get_platform = getattr(self.context, "get_platform_inst", None)
        if not callable(get_platform):
            return set()
        by_platform: dict[str, list[tuple[str, str]]] = {}
        for origin in sessions:
            parsed = group_session(origin)
            if parsed is not None:
                platform_id, group_id = parsed
                by_platform.setdefault(platform_id, []).append((origin, group_id))

        removed: set[str] = set()
        for platform_id, targets in by_platform.items():
            try:
                platform = get_platform(platform_id)
                # A missing/disabled platform is not proof that the bot left a group.
                if platform is None or platform.meta().name != "aiocqhttp":
                    continue
                client = platform.get_client()
                raw = await asyncio.wait_for(
                    client.call_action(action="get_group_list", no_cache=True),
                    timeout=self.timeout,
                )
                if not isinstance(raw, list):
                    raise TypeError("get_group_list did not return a list")
                group_ids: set[str] = set()
                for item in raw:
                    if not isinstance(item, dict):
                        raise TypeError("get_group_list contains an invalid entry")
                    group_id = str(item.get("group_id", ""))
                    if (
                        not group_id.isascii()
                        or not group_id.isdigit()
                        or int(group_id) <= 0
                    ):
                        raise ValueError("get_group_list contains an invalid group_id")
                    group_ids.add(group_id)
                status = await asyncio.wait_for(
                    client.call_action(action="get_status"), timeout=self.timeout
                )
                if (
                    not isinstance(status, dict)
                    or status.get("online") is not True
                    or status.get("good") is False
                ):
                    raise RuntimeError("QQ account online status is not confirmed")
            except Exception as exc:  # noqa: BLE001 - OneBot errors must retain subscriptions
                if platform_id not in self._warned_platforms:
                    logger.warning(
                        "[HD2] QQ 群列表查询失败，保留订阅: platform=%s error=%s: %s",
                        platform_id,
                        type(exc).__name__,
                        exc,
                    )
                    self._warned_platforms.add(platform_id)
                continue
            self._warned_platforms.discard(platform_id)
            removed.update(
                origin for origin, group_id in targets if group_id not in group_ids
            )
        return removed
