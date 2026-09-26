from __future__ import annotations

import os
import time
import unittest
from contextlib import contextmanager

from astrbot_plugin_Helldivers.core.text_utils import format_iso_time


@contextmanager
def _utc_timezone():
    """固定为 UTC 时区，保证断言与运行环境无关（仅限 POSIX）。"""
    old_tz = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    try:
        yield
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()


class FormatIsoTimeTests(unittest.TestCase):
    def test_unix_epoch_seconds(self) -> None:
        with _utc_timezone():
            self.assertEqual(format_iso_time(1756291200), "2025-08-27 10:40:00")

    def test_unix_epoch_milliseconds(self) -> None:
        with _utc_timezone():
            self.assertEqual(format_iso_time(1756291200000), "2025-08-27 10:40:00")

    def test_unix_epoch_as_numeric_string(self) -> None:
        # DSS electionEnd 等字段会以 str(election) 形式传入
        with _utc_timezone():
            self.assertEqual(format_iso_time("1756291200"), "2025-08-27 10:40:00")

    def test_iso_string_unchanged(self) -> None:
        with _utc_timezone():
            self.assertEqual(
                format_iso_time("2025-08-27T10:40:00Z"), "2025-08-27 10:40:00"
            )
            self.assertEqual(
                format_iso_time("2025-08-27 10:40:00"), "2025-08-27 10:40:00"
            )

    def test_invalid_inputs_return_unknown(self) -> None:
        for value in (None, "", "   ", "abc", "12", 12345, "not-a-time"):
            with self.subTest(value=value):
                self.assertEqual(format_iso_time(value), "未知时间")

    def test_extreme_epoch_returns_unknown(self) -> None:
        self.assertEqual(format_iso_time(10**18), "未知时间")

    def test_unconvertibly_large_int_returns_unknown(self) -> None:
        # float(10**400) 会抛 OverflowError，必须兜住而不是崩溃
        self.assertEqual(format_iso_time(10**400), "未知时间")


if __name__ == "__main__":
    unittest.main()
