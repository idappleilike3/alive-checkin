"""Shared daily-care context for LINE Flex and the member detail page."""
from __future__ import annotations


DEFAULT_CARE = {
    "title": "☀️ 今日生活提醒",
    "summary": "天氣炎熱，外出請記得補充水分，上午十點至下午兩點盡量避免長時間曝曬。",
    "source_name": "每日平安審核內容",
    "source_url": "https://alive-checkin.onrender.com/daily-care.html",
}


def _greeting(hour):
    if hour < 11:
        return "早安"
    if hour < 18:
        return "午安"
    return "晚安"


def _hero_period(hour):
    if hour < 11:
        return "morning"
    if hour < 18:
        return "afternoon"
    return "evening"


def build_daily_care_context(profile, now):
    profile = profile or {}
    location = profile.get("location") or {}
    city = str(location.get("city") or profile.get("city") or "").strip()
    district = str(location.get("district") or profile.get("district") or "").strip()
    weather = profile.get("weather") or {}
    if not city or not district:
        weather_status = "missing_location"
        weather_line = "請設定所在地區"
    elif all(weather.get(key) is not None for key in ("description", "min_c", "max_c", "rain_probability")):
        weather_status = "available"
        weather_line = (
            f"{city}｜{weather['description']}｜{weather['min_c']}～{weather['max_c']}°C｜"
            f"降雨機率 {weather['rain_probability']}%"
        )
    else:
        weather_status = "unavailable"
        weather_line = f"{city}｜天氣資料暫時無法更新"
    streak_days = int(profile.get("streak_days") or 0)
    if streak_days in (100, 365):
        care_title = f"🎉 平安第 {streak_days} 天"
        care_summary = f"謝謝你持續完成每日平安，這 {streak_days} 天的每一次回應，都讓關心你的人多一份安心。"
        content_kind = "milestone"
    else:
        care_title = DEFAULT_CARE["title"]
        care_summary = DEFAULT_CARE["summary"]
        content_kind = "daily"
    hero_period = _hero_period(now.hour)
    return {
        "greeting": _greeting(now.hour),
        "hero_period": hero_period,
        "hero_url": f"https://alive-checkin.onrender.com/assets/daily-care/{hero_period}.webp",
        "weather_status": weather_status,
        "weather_line": weather_line,
        "care_title": care_title,
        "care_summary": care_summary,
        "content_kind": content_kind,
        "source_name": DEFAULT_CARE["source_name"],
        "source_url": DEFAULT_CARE["source_url"],
        "updated_at": now.isoformat(timespec="minutes"),
    }
