#!/usr/bin/env python3
"""Build the elderly-friendly check-in walkthrough used by help.html."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "help-checkin-sop.gif"
FONT_PATH = "/System/Library/Fonts/STHeiti Light.ttc"
WIDTH, HEIGHT = 540, 900


def font(size):
    return ImageFont.truetype(FONT_PATH, size=size)


def rounded(draw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def centered(draw, y, text, text_font, fill):
    box = draw.textbbox((0, 0), text, font=text_font)
    draw.text(((WIDTH - (box[2] - box[0])) / 2, y), text, font=text_font, fill=fill)


def header(draw, step, title, subtitle):
    rounded(draw, (18, 18, WIDTH - 18, 104), 24, "#FFF7ED", "#FDBA74", 3)
    rounded(draw, (34, 36, 86, 88), 26, "#E11D48")
    centered_number = font(26)
    draw.text((52, 61), str(step), font=centered_number, fill="white", anchor="mm")
    draw.text((103, 31), title, font=font(28), fill="#5B1535")
    draw.text((103, 67), subtitle, font=font(19), fill="#7C2D12")


def phone(draw, title):
    rounded(draw, (58, 125, WIDTH - 58, HEIGHT - 34), 42, "#F8FAFC", "#334155", 5)
    rounded(draw, (73, 141, WIDTH - 73, HEIGHT - 51), 30, "#FFFFFF")
    rounded(draw, (208, 137, 332, 154), 9, "#334155")
    draw.text((WIDTH / 2, 187), title, font=font(27), fill="#18392D", anchor="mm")
    draw.line((73, 219, WIDTH - 73, 219), fill="#D1D5DB", width=2)


def finger(draw, x, y, touching=False):
    skin = "#F1C6A8"
    outline = "#A9603B"
    draw.ellipse((x - 41, y + 16, x + 45, y + 102), fill=skin, outline=outline, width=3)
    draw.rounded_rectangle((x - 18, y - 56, x + 24, y + 62), radius=20, fill=skin, outline=outline, width=3)
    draw.ellipse((x - 11, y - 48, x + 17, y - 23), fill="#F8D7C0")
    if touching:
        draw.ellipse((x - 38, y - 76, x + 44, y + 6), outline="#FB7185", width=5)
        draw.ellipse((x - 52, y - 90, x + 58, y + 20), outline="#FDA4AF", width=3)


def base_frame(step, title, subtitle, phone_title):
    image = Image.new("RGB", (WIDTH, HEIGHT), "#FFF1F7")
    draw = ImageDraw.Draw(image)
    header(draw, step, title, subtitle)
    phone(draw, phone_title)
    return image, draw


def reminder_frame(touching=False):
    image, draw = base_frame(1, "收到每日提醒", "先看清楚是「每日平安」通知", "LINE")
    draw.rectangle((74, 220, WIDTH - 74, HEIGHT - 52), fill="#E8F5EC")
    rounded(draw, (91, 254, WIDTH - 91, 352), 22, "#FFFFFF", "#86EFAC", 2)
    rounded(draw, (108, 270, 162, 324), 16, "#06C755")
    draw.text((135, 297), "安", font=font(25), fill="white", anchor="mm")
    draw.text((179, 268), "每日平安", font=font(23), fill="#16352C")
    draw.text((179, 305), "早安，該報平安囉！", font=font(20), fill="#334155")
    draw.text((179, 332), "點一下開啟「我平安」", font=font(17), fill="#64748B")
    rounded(draw, (106, 402, 350, 482), 24, "#FFFFFF", "#C7E8D1", 2)
    draw.text((126, 422), "每日平安", font=font(20), fill="#166534")
    draw.text((126, 453), "請點下方按鈕完成回報", font=font(18), fill="#334155")
    rounded(draw, (106, 504, 342, 574), 22, "#06C755")
    draw.text((224, 539), "開啟報平安", font=font(23), fill="white", anchor="mm")
    finger(draw, 385, 530, touching)
    return image


def checkin_frame(touching=False):
    image, draw = base_frame(2, "手指點「我平安」", "只要按一次，不用輸入文字", "每日平安")
    draw.rectangle((74, 220, WIDTH - 74, HEIGHT - 52), fill="#FFF8FB")
    centered(draw, 267, "今天也要讓家人安心", font(24), "#5B1535")
    centered(draw, 308, "每天 10 秒，報個平安", font(19), "#7C2D12")
    rounded(draw, (112, 386, WIDTH - 112, 558), 38, "#EC4899", "#BE185D", 4)
    centered(draw, 416, "我平安", font(48), "white")
    centered(draw, 493, "回報今天平安", font(21), "white")
    draw.text((WIDTH / 2, 620), "按下後會立刻顯示結果", font=font(20), fill="#475569", anchor="mm")
    finger(draw, 402, 493, touching)
    return image


def success_frame():
    image, draw = base_frame(3, "看到成功訊息", "出現時間才代表今天已完成", "每日平安")
    draw.rectangle((74, 220, WIDTH - 74, HEIGHT - 52), fill="#F0FDF4")
    rounded(draw, (102, 273, WIDTH - 102, 502), 30, "#FFFFFF", "#4ADE80", 4)
    draw.ellipse((214, 298, 326, 410), fill="#22C55E")
    draw.line((242, 355, 264, 378), fill="white", width=10)
    draw.line((264, 378, 302, 332), fill="white", width=10)
    centered(draw, 429, "今天已完成報平安", font(28), "#166534")
    centered(draw, 469, "2026/07/29 09:00", font(18), "#64748B")
    rounded(draw, (102, 544, WIDTH - 102, 650), 22, "#DCFCE7", "#86EFAC", 2)
    centered(draw, 563, "系統已記錄成功", font(23), "#14532D")
    centered(draw, 605, "重要的人會看到你的平安狀態", font(18), "#166534")
    return image


def guardian_frame(reply=False):
    image, draw = base_frame(4, "守護人收到對話", "LINE 會顯示姓名、時間與狀態", "LINE｜每日平安")
    draw.rectangle((74, 220, WIDTH - 74, HEIGHT - 52), fill="#E8F5EC")
    draw.ellipse((93, 268, 149, 324), fill="#06C755")
    draw.text((121, 296), "安", font=font(25), fill="white", anchor="mm")
    rounded(draw, (163, 256, 450, 374), 23, "#FFFFFF", "#C7E8D1", 2)
    draw.text((183, 274), "媽媽已完成今日報平安", font=font(20), fill="#16352C")
    draw.text((183, 312), "回報時間：09:00", font=font(18), fill="#475569")
    draw.text((183, 342), "目前狀態：平安", font=font(18), fill="#166534")
    if reply:
        rounded(draw, (204, 432, 445, 508), 22, "#9DE79F", "#5FBF68", 2)
        draw.text((224, 453), "收到，放心了", font=font(21), fill="#16352C")
        draw.text((397, 518), "09:01", font=font(15), fill="#64748B")
        rounded(draw, (98, 578, 442, 674), 22, "#FFFFFF", "#C7E8D1", 2)
        centered(draw, 598, "這就是雙方都看得到的結果", font(21), "#14532D")
        centered(draw, 637, "不是只有一個打勾符號", font(18), "#475569")
    return image


def main():
    frames = [
        reminder_frame(False),
        reminder_frame(True),
        checkin_frame(False),
        checkin_frame(True),
        success_frame(),
        guardian_frame(False),
        guardian_frame(True),
    ]
    durations = [1100, 700, 1000, 700, 1500, 1100, 2400]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        OUTPUT,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=2,
    )
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
