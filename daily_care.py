"""Shared daily-care context for LINE Flex and the member detail page."""
from __future__ import annotations


DEFAULT_CARE = {
    "title": "☀️ 今日生活提醒",
    "summary": "天氣炎熱，外出請記得補充水分，上午十點至下午兩點盡量避免長時間曝曬。",
    "source_name": "每日平安審核內容",
    "source_url": "https://alive-checkin.onrender.com/daily-care.html",
}

DEFAULT_NEWS = {
    "title": "今日政府與生活重要消息",
    "summary": "目前沒有需要特別注意的重大生活消息；外出前仍請留意所在地天氣與官方警特報。",
    "source_name": "交通部中央氣象署",
    "source_url": "https://www.cwa.gov.tw/",
}


HERO_ASSETS = {
    "morning": ("morning-01", "morning-02"),
    "afternoon": ("afternoon-01", "afternoon-02"),
    "evening": ("evening-01", "evening-02", "evening-03"),
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
STREAK_REWARDS = (
    (1, "❤️", "愛心動畫"),
    (3, "✨", "小星光"),
    (7, "🎊", "彩帶驚喜"),
    (14, "🏅", "新徽章"),
    (21, "💌", "鼓勵卡"),
    (30, "🥇", "金色獎章"),
    (60, "🏵️", "進階徽章"),
    (90, "🌟", "星光卡"),
    (100, "🎆", "煙火＋第一支 MP4"),
    (180, "🏆", "高級金色徽章"),
    (270, "🗓️", "年度倒數卡"),
    (365, "🎉", "年度動畫＋第二支 MP4"),
)
STREAK_GAME_BADGES = (
    (1, "初心愛心章"), (3, "星芽徽章"), (7, "七日守護章"),
    (14, "雙週同行章"), (21, "習慣守護章"), (30, "金色夥伴章"),
    (60, "穩定之星章"), (90, "長久陪伴章"), (100, "百日榮耀章"),
    (180, "黃金守護章"), (270, "典範之星章"), (365, "年度傳說勳章"),
)


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
    reward_icon, reward_name = STREAK_REWARDS[0][1:]
    for reward_day, icon, reward in STREAK_REWARDS:
        if highest_streak_days >= reward_day:
            reward_icon, reward_name = icon, reward
    game_badge_name = STREAK_GAME_BADGES[0][1]
    for badge_day, badge_name in STREAK_GAME_BADGES:
        if highest_streak_days >= badge_day:
            game_badge_name = badge_name
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
        "reward_icon": reward_icon,
        "reward_name": reward_name,
        "game_badge_name": game_badge_name,
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


def _calendar_note_text(note):
    if isinstance(note, list):
        return "\n".join(filter(None, (_calendar_note_text(item) for item in note)))
    if isinstance(note, dict):
        return str(note.get("content") or "").strip()
    return str(note or "").strip()


def _today_reminders(profile, today):
    rows = []
    note = (profile.get("calendar_notes") or {}).get(today.isoformat())
    note_text = _calendar_note_text(note)
    if note_text:
        rows.append({"kind": "calendar", "time": "", "text": note_text})
    for reminder in profile.get("smart_reminders") or []:
        if not isinstance(reminder, dict) or not reminder.get("enabled", True):
            continue
        try:
            month, day = int(reminder.get("month") or 0), int(reminder.get("day") or 0)
            year = int(reminder.get("year")) if reminder.get("year") else None
        except (TypeError, ValueError):
            continue
        if month != today.month or day != today.day or (year and year != today.year):
            continue
        remind_time = str(reminder.get("remind_time") or reminder.get("time") or "").strip()
        label = str(reminder.get("category_label") or reminder.get("custom_title") or "提醒").strip()
        target = str(reminder.get("target_name") or "").strip()
        detail = str(reminder.get("note") or "").strip()
        text = "｜".join(part for part in (remind_time, target, label, detail) if part)
        rows.append({"kind": "smart", "time": remind_time, "text": text})
    return rows


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
    news = profile.get("daily_news") if isinstance(profile.get("daily_news"), dict) else {}
    has_important_news = bool(news.get("title") and news.get("summary"))
    news_title = str(news.get("title") or DEFAULT_NEWS["title"]).strip()
    news_summary = str(news.get("summary") or DEFAULT_NEWS["summary"]).strip()
    news_source_name = str(news.get("source_name") or DEFAULT_NEWS["source_name"]).strip()
    news_source_url = str(news.get("source_url") or DEFAULT_NEWS["source_url"]).strip()
    return {
        "greeting": _greeting(now.hour),
        "hero_period": hero_period,
        "hero_url": f"https://alive-checkin.onrender.com/assets/daily-care/{hero_asset}.webp",
        "weather_status": weather_status,
        "weather_line": weather_line,
        "care_title": care_title,
        "care_summary": care_summary,
        "news_title": news_title,
        "news_summary": news_summary,
        "news_source_name": news_source_name,
        "news_source_url": news_source_url,
        "has_important_news": has_important_news,
        "today_reminders": _today_reminders(profile, now.date()),
        "blessing_text": str(
            profile.get("daily_blessing")
            or profile.get("positive_quote")
            or "謝謝認真生活的自己，今天也要平安順心。"
        ).strip(),
        "content_kind": content_kind,
        **level_context,
        "checkin_prompt": "今天一切都還好嗎？點一下「我平安」",
        "habit_value_text": "每天只花 10 秒，看到一個小驚喜，也讓在乎我的人放心。",
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
