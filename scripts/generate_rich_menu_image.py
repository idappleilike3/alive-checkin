from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "line-rich-menu.png"
WIDTH = 2500
HEIGHT = 1686
CELL_W = [833, 834, 833]
CELL_H = 843

ITEMS = [
    ("報平安", "check", "點一下報平安"),
    ("綁定守護人", "heart", "邀請家人守護"),
    ("我的狀態", "info", "今天是否平安"),
    ("查看方案", "price", "月費年費說明"),
    ("問與答", "faq", "常見問題快速看"),
    ("聯絡客服", "support", "需要協助找我們"),
]


def font(size, bold=False):
    candidates = [
        "C:/Windows/Fonts/msjhbd.ttc" if bold else "C:/Windows/Fonts/msjh.ttc",
        "C:/Windows/Fonts/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def centered_text(draw, box, text, text_font, fill):
    left, top, right, bottom = box
    bbox = draw.textbbox((0, 0), text, font=text_font)
    x = left + (right - left - (bbox[2] - bbox[0])) / 2
    y = top + (bottom - top - (bbox[3] - bbox[1])) / 2
    draw.text((x, y), text, font=text_font, fill=fill)


def draw_icon(draw, cx, cy, kind, color):
    r = 118
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill="#ffffff", outline=color, width=10)
    if kind == "check":
        draw.line((cx - 58, cy + 6, cx - 18, cy + 48, cx + 72, cy - 58), fill=color, width=26, joint="curve")
    elif kind == "heart":
        draw.ellipse((cx - 68, cy - 48, cx + 4, cy + 24), outline=color, width=16)
        draw.ellipse((cx - 4, cy - 48, cx + 68, cy + 24), outline=color, width=16)
        draw.line((cx - 66, cy + 4, cx, cy + 76, cx + 66, cy + 4), fill=color, width=16, joint="curve")
    elif kind == "info":
        centered_text(draw, (cx - 72, cy - 84, cx + 72, cy + 94), "i", font(146, bold=True), color)
    elif kind == "price":
        centered_text(draw, (cx - 84, cy - 90, cx + 84, cy + 100), "$", font(146, bold=True), color)
    elif kind == "faq":
        centered_text(draw, (cx - 84, cy - 90, cx + 84, cy + 100), "?", font(146, bold=True), color)
    elif kind == "support":
        draw.arc((cx - 74, cy - 54, cx + 74, cy + 88), 200, 340, fill=color, width=16)
        draw.arc((cx - 88, cy - 78, cx + 88, cy + 64), 200, 340, fill=color, width=16)
        draw.rounded_rectangle((cx - 100, cy - 10, cx - 64, cy + 54), radius=12, outline=color, width=13)
        draw.rounded_rectangle((cx + 64, cy - 10, cx + 100, cy + 54), radius=12, outline=color, width=13)
        draw.line((cx + 52, cy + 72, cx + 14, cy + 88), fill=color, width=13)


def main():
    bg = Image.new("RGB", (WIDTH, HEIGHT), "#fff7e8")
    draw = ImageDraw.Draw(bg)

    title_font = font(112, bold=True)
    subtitle_font = font(58, bold=True)

    x_positions = [0, CELL_W[0], CELL_W[0] + CELL_W[1]]
    colors = ["#c9f5dc", "#ffe8ad", "#cde2ff", "#eadcff", "#cef6ff", "#ffd5df"]
    accent = ["#0c9a53", "#e99b00", "#246de8", "#6f48da", "#00899d", "#d93561"]
    text_colors = ["#06351e", "#3e2a00", "#0b2857", "#271659", "#053a44", "#541228"]
    desc_colors = ["#0f6a40", "#885800", "#28599d", "#5941a7", "#087486", "#a52b4d"]

    for index, (label, icon, desc) in enumerate(ITEMS):
        row = index // 3
        col = index % 3
        x = x_positions[col]
        y = row * CELL_H
        w = CELL_W[col]
        color = colors[index]
        line = accent[index]
        text_color = text_colors[index]
        desc_color = desc_colors[index]
        draw.rounded_rectangle((x + 24, y + 24, x + w - 24, y + CELL_H - 24), radius=72, fill=color, outline="#fffdf8", width=10)
        draw.ellipse((x + 62, y + 54, x + 280, y + 172), fill="#fff8ea")
        draw.ellipse((x + w - 260, y + CELL_H - 170, x + w - 62, y + CELL_H - 56), fill="#ffffff")
        draw.rounded_rectangle((x + 52, y + 52, x + w - 52, y + CELL_H - 52), radius=58, outline=line, width=5)
        draw_icon(draw, x + w / 2, y + 210, icon, line)
        centered_text(draw, (x, y + 370, x + w, y + 500), label, title_font, text_color)
        centered_text(draw, (x + 34, y + 540, x + w - 34, y + 660), desc, subtitle_font, desc_color)

    draw.line((833, 0, 833, HEIGHT), fill="#ead6b8", width=7)
    draw.line((1667, 0, 1667, HEIGHT), fill="#ead6b8", width=7)
    draw.line((0, 843, WIDTH, 843), fill="#ead6b8", width=7)
    bg.save(OUTPUT, quality=95)
    print(OUTPUT)


if __name__ == "__main__":
    main()
