"""生成导演段落实例。需要 Pillow 和一款含中文的字体。"""

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


SIZE = (560, 252)
FRAME_MS = 80
PAPER = "#f5efe4"
INK = "#193932"
TEAL = "#177766"
ORANGE = "#d5653e"
GOLD = "#f1c766"


def ease(t, start, end):
    u = min(1, max(0, (t - start) / (end - start)))
    return u * u * (3 - 2 * u)


def person(draw, x, y, arm):
    draw.ellipse((x - 9, y - 40, x + 9, y - 22), fill=PAPER)
    draw.line((x, y - 20, x, y + 5), fill=PAPER, width=9)
    draw.line((x, y + 3, x - 10, y + 21), fill=PAPER, width=5)
    draw.line((x, y + 3, x + 11, y + 21), fill=PAPER, width=5)
    draw.line((x, y - 15, x + 11, y - 6, *arm), fill=PAPER, width=4)


def decision(t, fonts):
    im = Image.new("RGB", SIZE, "#172a30")
    d = ImageDraw.Draw(im)
    turn = ease(t, 1.3, 2.6)
    walk = ease(t, 2.7, 4.7)
    target = 230 + 226 * turn
    d.polygon([(289, 59), (target + 65, 217), (target - 65, 217)], fill="#685f42")
    d.line((0, 219, 560, 219), fill="#85958a", width=2)
    angle = math.atan2(158, target - 289)
    tip = (289 + 24 * math.cos(angle), 59 + 24 * math.sin(angle))
    d.line((289, 59, *tip), fill=GOLD, width=10)
    d.line((289, 32, 289, 60), fill=PAPER, width=3)
    d.rectangle((435, 120, 508, 217), outline=GOLD if turn > .8 else "#81908a", width=4)
    d.text((472, 107), "出口", font=fonts[0], anchor="mm", fill=GOLD if turn > .8 else PAPER)
    person(d, 96, 196, (119 + 16 * turn, 172 - 14 * turn))
    d.line((127, 192, 128 + 10 * turn, 164), fill=ORANGE, width=5)
    x = 355 + 148 * walk
    person(d, x, 197, (x + 7, 186))
    title = "出口还暗着" if t < 1.3 else ("把备用灯调过去" if t < 2.7 else "路亮了，人能走出去")
    d.text((24, 17), title, font=fonts[1], fill=PAPER)
    return im


def caption_only(t, fonts):
    """同一委托的反例：只推进人物与标题，出口处没有后续行动。"""
    im = Image.new("RGB", SIZE, "#172a30")
    d = ImageDraw.Draw(im)
    d.line((0, 219, 560, 219), fill="#85958a", width=2)
    d.rectangle((435, 120, 508, 217), outline="#81908a", width=4)
    d.text((472, 107), "出口", font=fonts[0], anchor="mm", fill=PAPER)
    person(d, 204, 196, (225, 182))
    d.text((35, 39), "值班人安排了照明", font=fonts[1], fill=PAPER)
    inset = round(14 * ease(t, 0, 4.6))
    return im.resize(SIZE, Image.Resampling.BILINEAR,
                     box=(inset, inset / 2, SIZE[0] - inset, SIZE[1] - inset / 2))


def section(t, fonts):
    im = Image.new("RGB", SIZE, PAPER)
    d = ImageDraw.Draw(im)
    bump = ease(t, .3, .9) - ease(t, 1.1, 1.5)
    lift = ease(t, 2.6, 3.5)
    close = ease(t, 3.7, 4.7)
    x = 102 + 8 * bump + 90 * close
    d.rectangle((197, 80, 487, 212), fill="#c3cec0", outline=INK, width=3)
    d.rectangle((205, 93, 474, 198), fill="#344c46")
    d.rectangle((x, 132, x + 259, 184), fill="#c79562", outline=INK, width=3)
    d.line((x + 15, 148, x + 56, 148), fill=INK, width=5)
    if t > 1.5:
        d.rectangle((203, 96, 467, 130), fill=PAPER)
        py = 125 - 50 * lift
        d.line((239, py + 12, 310, py - 19), fill=ORANGE, width=7)
        d.polygon([(307, py - 22), (320, py - 23), (310, py - 15)], fill=INK)
    title = "抽屉合不上" if t < 1.5 else ("沿原位看进去" if t < 2.6 else "移开铅笔，再合上")
    d.text((24, 17), title, font=fonts[1], fill=INK)
    return im


def paths(t, fonts):
    im = Image.new("RGB", SIZE, PAPER)
    d = ImageDraw.Draw(im)
    d.text((24, 14), "同一本书，两种办理方式", font=fonts[1], fill=INK)
    lanes = [
        ("借阅", 95, ((206, "找书"), (335, "登记"), (469, "已借出")), .3, 2.6, TEAL),
        ("续借", 181, ((206, "改还期"), (335, "已续借")), 2.6, 4.1, ORANGE),
    ]
    for label, y, stops, a, b, color in lanes:
        d.text((29, y), label, font=fonts[1], fill=INK, anchor="lm")
        head = 133 + (stops[-1][0] - 133) * ease(t, a, b)
        d.line((133, y, stops[-1][0], y), fill="#c8c7b9", width=3)
        d.line((133, y, head, y), fill=color, width=5)
        for x, word in stops:
            d.ellipse((x - 4, y - 4, x + 4, y + 4), fill=color if head >= x else INK)
            d.text((x, y + 22), word, font=fonts[0], fill=INK, anchor="mm")
        d.rounded_rectangle((head - 10, y - 19, head + 9, y - 1), radius=2, fill=color)
        d.line((head - 6, y - 16, head - 6, y - 4), fill=PAPER, width=2)
    return im


STUDIES = {"decision": decision, "caption-only": caption_only, "section": section, "paths": paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="写入 GIF 的目录")
    parser.add_argument("--font", required=True, type=Path, help="含中文的字体文件")
    parser.add_argument("--font-index", type=int, default=0, help="字体集合中的字面序号")
    args = parser.parse_args()
    fonts = [ImageFont.truetype(str(args.font), size, index=args.font_index) for size in (17, 25)]
    args.output.mkdir(parents=True, exist_ok=True)
    for name, paint in STUDIES.items():
        frames = [paint(i * FRAME_MS / 1000, fonts) for i in range(68)]
        frames[0].save(args.output / f"{name}.gif", save_all=True, append_images=frames[1:],
                       duration=FRAME_MS, loop=0, optimize=True)


if __name__ == "__main__":
    main()
