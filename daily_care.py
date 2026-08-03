"""Shared daily-care context for LINE Flex and the member detail page."""
from __future__ import annotations


DEFAULT_CARE = {
    "title": "☀️ 今日生活提醒",
    "summary": "天氣炎熱，外出請記得補充水分，上午十點至下午兩點盡量避免長時間曝曬。",
    "source_name": "每日平安審核內容",
    "source_url": "https://alive-checkin.onrender.com/daily-care.html",
}


HERO_ASSETS = {
    "morning": ("morning-01", "morning-02"),
    "afternoon": ("afternoon-01", "afternoon-02"),
    "evening": ("evening-01", "evening-02"),
}

STREAK_LEVELS = (
    (1, "安心啟程", "#16A34A"),
    (3, "平安萌芽", "#0D9488"),
    (7, "初心守護", "#2563EB"),
    (14, "安心同行", "#7C3AED"),
    (21, "守護習慣", "#C026D3"),
    (30, "安心夥伴", "#D97706"),
    (60, "穩定守護", "#EA580C"),
    (90, "長久陪伴", "#DB2777"),
    (100, "百日之星", "#CA8A04"),
    (180, "金色守護", "#A16207"),
    (270, "安心典範", "#9333EA"),
    (365, "年度守護者", "#B45309"),
)
STREAK_MILESTONES = tuple(day for day, _name, _color in STREAK_LEVELS)


def streak_level_context(streak_days, highest_streak_days=0):
    """Return the permanent earned badge and current streak progress."""
    streak_days = max(0, int(streak_days or 0))
    highest_streak_days = max(streak_days, int(highest_streak_days or 0))
    earned_index = 0
    for index, (day, _name, _color) in enumerate(STREAK_LEVELS):
        if highest_streak_days >= day:
            earned_index = index
    day, name, color = STREAK_LEVELS[earned_index]
    next_level = next((item for item in STREAK_LEVELS if item[0] > highest_streak_days), None)
    if next_level:
        next_day, next_name, _next_color = next_level
        days_to_next = next_day - streak_days
        progress_text = (
            f"Lv.{earned_index + 1} {name}｜連續第 {streak_days} 天｜"
            f"距離下一級「{next_name}」還差 {days_to_next} 天"
        )
    else:
        next_day = None
        next_name = ""
        days_to_next = 0
        progress_text = f"Lv.{earned_index + 1} {name}｜連續第 {streak_days} 天｜已達最高等級"
    return {
        "level": earned_index + 1,
        "level_name": name,
        "level_day": day,
        "level_color": color,
        "next_level_day": next_day,
        "next_level_name": next_name,
        "days_to_next_level": days_to_next,
        "is_upgrade_day": streak_days in STREAK_MILESTONES,
        "progress_percent": min(100, round(streak_days / (next_day or 365) * 100)),
        "level_progress_text": progress_text,
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
    level_context = streak_level_context(streak_days, profile.get("highest_streak_days") or 0)
    if streak_days in STREAK_MILESTONES:
        care_title = (
            f"🎉 連續第 {streak_days} 天｜升級為 "
            f"Lv.{level_context['level']}「{level_context['level_name']}」"
        )
        care_summary = f"你已連續報平安 {streak_days} 天，登入每日平安網頁，有一份升級驚喜等著你"
        content_kind = "milestone"
    else:
        care_title = DEFAULT_CARE["title"]
        care_summary = DEFAULT_CARE["summary"]
        content_kind = "daily"
    milestone_day = streak_days if streak_days in STREAK_MILESTONES else None
    hero_period = _hero_period(now.hour)
    hero_pool = HERO_ASSETS[hero_period]
    hero_asset = hero_pool[now.date().toordinal() % len(hero_pool)]
    return {
        "greeting": _greeting(now.hour),
        "hero_period": hero_period,
        "hero_url": f"https://alive-checkin.onrender.com/assets/daily-care/{hero_asset}.webp",
        "weather_status": weather_status,
        "weather_line": weather_line,
        "care_title": care_title,
        "care_summary": care_summary,
        "content_kind": content_kind,
        **level_context,
        "checkin_prompt": "今天一切都還好嗎？點一下「我平安」",
        "streak_status_text": "重新開始連續守護" if profile.get("streak_restarted") else "持續連續守護",
        "milestone_day": milestone_day,
        "achievement_url": (
            f"https://alive-checkin.onrender.com/?milestone={milestone_day}"
            if milestone_day else ""
        ),
        "source_name": DEFAULT_CARE["source_name"],
        "source_url": DEFAULT_CARE["source_url"],
        "updated_at": now.isoformat(timespec="minutes"),
    }
