"""Taiwan-relevant festival / holiday helpers for daily check-in push.

Solar festivals use recurring MM-DD.
Lunar festivals: maintain year-keyed YMD table (at least 2026+); document sources
in comments so future years can be extended without guessing.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

# Recurring solar / fixed civil dates (MM-DD → name, blessing)
SOLAR_HOLIDAYS: dict[str, tuple[str, str]] = {
    "01-01": ("元旦", "元旦快樂！願新的一年天天平安、事事順心。"),
    "02-14": ("情人節", "情人節快樂，願你被溫柔對待、也被好好珍惜。"),
    "04-04": ("兒童節", "兒童節快樂！願家中小朋友健康快樂、笑口常開。"),
    "05-01": ("勞動節", "勞動節快樂，辛苦了！記得照顧自己、平安回家。"),
    "08-08": ("父親節", "父親節快樂！謝謝每位爸爸與長輩的守護。"),
    "10-10": ("國慶／雙十", "雙十國慶快樂，祝大家平安喜樂、國泰民安。"),
    "12-24": ("耶誕夜", "耶誕夜快樂，願今夜溫暖平安、心裡有光。"),
    "12-25": ("耶誕節", "耶誕快樂！願你被祝福圍繞、日子充滿善意。"),
    "12-31": ("跨年", "跨年快樂！謝謝你今年的堅持，明年也一起平安。"),
}

# Lunar / movable festivals by concrete solar date.
# 2026 lunar mapping (approx. civil calendar):
#   春節 2026-02-17（農曆正月初一）
#   元宵 2026-03-03（正月十五）
#   清明 2026-04-05（節氣，固定陽曆）
#   端午 2026-06-19（五月初五）
#   七夕 2026-08-19（七月初七）
#   中元 2026-08-28（七月十五）
#   中秋 2026-09-25（八月十五）
#   重陽 2026-10-18（九月初九）
#   冬至 2026-12-22（節氣）
# Extend future years in the same shape: "YYYY-MM-DD": (name, blessing)
LUNAR_AND_MOVABLE: dict[str, tuple[str, str]] = {
    "2026-02-17": ("春節", "新春如意、龍馬精神！願你闔家平安、歲歲安康。"),
    "2026-03-03": ("元宵節", "元宵快樂，願團圓溫暖、心願慢慢實現。"),
    "2026-04-05": ("清明節", "清明時節，願先人安息、生者平安健康。"),
    "2026-05-10": ("母親節", "母親節快樂！謝謝每一位媽媽與照顧者的付出。"),
    "2026-06-19": ("端午節", "端午安康！記得保重身體、平安度過每一天。"),
    "2026-08-19": ("七夕", "七夕快樂，願有情人互相守護、平安相伴。"),
    "2026-08-28": ("中元節", "中元平安，願家宅安寧、出入順利。"),
    "2026-09-25": ("中秋節", "中秋快樂！願月圓人圓、家人心裡都踏實。"),
    "2026-10-18": ("重陽節", "重陽敬老，願長輩健康長壽、晚輩常伴左右。"),
    "2026-12-22": ("冬至", "冬至快樂，願溫暖入心、平安過冬。"),
    # 2027 placeholders (major lunar) — update blessings as needed
    "2027-02-06": ("春節", "新春如意！願你闔家平安、歲歲安康。"),
    "2027-02-20": ("元宵節", "元宵快樂，願團圓溫暖、心願慢慢實現。"),
    "2027-04-05": ("清明節", "清明時節，願先人安息、生者平安健康。"),
    "2027-05-09": ("母親節", "母親節快樂！謝謝每一位媽媽與照顧者的付出。"),
    "2027-06-09": ("端午節", "端午安康！記得保重身體、平安度過每一天。"),
    "2027-08-08": ("七夕", "七夕快樂，願有情人互相守護、平安相伴。"),
    "2027-08-16": ("中元節", "中元平安，願家宅安寧、出入順利。"),
    "2027-09-15": ("中秋節", "中秋快樂！願月圓人圓、家人心裡都踏實。"),
    "2027-10-08": ("重陽節", "重陽敬老，願長輩健康長壽、晚輩常伴左右。"),
    "2027-12-22": ("冬至", "冬至快樂，願溫暖入心、平安過冬。"),
}

POSITIVE_QUOTES: list[str] = [
    "每一天的平安，都是給家人最好的禮物。",
    "慢慢來也沒關係，重要的是你今天還在、還好。",
    "照顧好自己，就是愛家人最直接的方式。",
    "有些日子平凡，平凡就是福氣。",
    "你願意報個平安，就已經很勇敢了。",
    "世界很大，但有人在意你今天好不好。",
    "深呼吸一次，把今天過得安穩一點。",
    "小步驟也算前進，平安就是進度。",
    "別忘了，你值得被好好對待。",
    "陽光會來，風雨也會過；先顧好自己。",
    "一句「我平安」，能讓牽掛變成安心。",
    "今天也請對自己溫柔一點。",
    "你不是一個人，守護網正在你身邊。",
    "把焦慮放小聲，把平安放大聲。",
    "身體健康、心情平穩，就是最好的成績。",
    "再忙也記得喝水、吃飯、回報平安。",
    "願你被世界溫柔以待，也溫柔對待自己。",
    "今天的你，已經足夠好了。",
    "平安無事，其實是最大的喜事。",
    "給自己一個微笑，然後告訴家人：我很好。",
    "心裡有光，路就不怕黑。",
    "慢一點、穩一點，日子會更踏實。",
    "你報平安的瞬間，家就鬆了一口氣。",
    "把關心傳出去，也把溫暖留給自己。",
    "無論多忙，健康永遠排第一。",
    "今天也謝謝你，願意被愛、願意報到。",
    "小事做好，大事自然少擔心。",
    "願你出門順利、回家平安。",
    "累了就休息，休息也是一種負責。",
    "正能量不是喊口號，是願意好好過今天。",
]


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError("expected date or datetime")


def nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """weekday: Mon=0 … Sun=6; n: 1=first, 2=second, …"""
    d = date(year, month, 1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d + timedelta(weeks=n - 1)


def mothers_day(year: int) -> date:
    """Taiwan Mother's Day = second Sunday of May."""
    return nth_weekday_of_month(year, 5, 6, 2)


def holiday_for(day) -> Optional[dict]:
    """Return {key, name, blessing} if `day` is a known festival, else None."""
    d = _as_date(day)
    ymd = d.strftime("%Y-%m-%d")
    md = d.strftime("%m-%d")

    if ymd in LUNAR_AND_MOVABLE:
        name, blessing = LUNAR_AND_MOVABLE[ymd]
        return {"key": ymd, "name": name, "blessing": blessing, "kind": "lunar_or_movable"}

    # Dynamic Mother's Day fallback when year table missing
    if d == mothers_day(d.year):
        return {
            "key": ymd,
            "name": "母親節",
            "blessing": "母親節快樂！謝謝每一位媽媽與照顧者的付出。",
            "kind": "movable",
        }

    if md in SOLAR_HOLIDAYS:
        name, blessing = SOLAR_HOLIDAYS[md]
        return {"key": md, "name": name, "blessing": blessing, "kind": "solar"}

    return None


def positive_quote_for(day) -> str:
    """Stable rotating affirmation by day-of-year."""
    d = _as_date(day)
    idx = (d.timetuple().tm_yday - 1) % len(POSITIVE_QUOTES)
    return POSITIVE_QUOTES[idx]


def daily_push_copy(day) -> dict:
    """Greeting + optional holiday blessing + positive quote for Flex/text."""
    d = _as_date(day)
    holiday = holiday_for(d)
    quote = positive_quote_for(d)
    greeting = "❤️ 今天一切都好嗎？"
    return {
        "greeting": greeting,
        "holiday": holiday,
        "holiday_name": (holiday or {}).get("name") or "",
        "holiday_blessing": (holiday or {}).get("blessing") or "",
        "positive_quote": quote,
        "instruction": "點「我平安」立刻完成報到（不用再開網頁）",
    }
