# -*- coding: utf-8 -*-
"""生成应用图标 ``assets/CCGauge.ico``（多尺寸，供窗口/托盘/任务栏使用）。

图形：圆角方形渐变底 + 三根柱状条（用量面板意象）+ 高亮数据点。
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(BASE_DIR, "assets", "CCGauge.ico")
SIZES = [16, 24, 32, 48, 64, 128, 256]
SUPERSAMPLE = 4  # 超采样倍数（先画大图再缩小，边缘更平滑）


def _lerp_color(start, end, ratio):
    """按比例插值两个 RGB 颜色。"""
    return tuple(int(s + (e - s) * ratio) for s, e in zip(start, end))


def draw_icon(size: int) -> Image.Image:
    """绘制指定尺寸的图标。"""
    scale = SUPERSAMPLE
    canvas = size * scale
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # 圆角底（左上到右下渐变）
    radius = int(canvas * 0.22)
    top_color, bottom_color = (59, 130, 246), (124, 58, 237)
    for y in range(canvas):
        ratio = y / max(canvas - 1, 1)
        color = _lerp_color(top_color, bottom_color, ratio)
        draw.line([(0, y), (canvas, y)], fill=color + (255,))
    mask = Image.new("L", (canvas, canvas), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, canvas - 1, canvas - 1], radius=radius, fill=255)
    image.putalpha(mask)

    # 三根柱状条（白色，高度递增）
    bar_width = int(canvas * 0.14)
    gap = int(canvas * 0.09)
    base_y = int(canvas * 0.78)
    heights = [0.26, 0.42, 0.58]
    total_width = bar_width * 3 + gap * 2
    start_x = (canvas - total_width) // 2
    for index, height_ratio in enumerate(heights):
        x0 = start_x + index * (bar_width + gap)
        y0 = base_y - int(canvas * height_ratio)
        draw.rounded_rectangle(
            [x0, y0, x0 + bar_width, base_y],
            radius=int(bar_width * 0.28),
            fill=(255, 255, 255, 235),
        )

    # 数据点（最高柱顶部圆点，强调“监控”意象）
    dot_r = int(canvas * 0.055)
    dot_cx = start_x + 2 * (bar_width + gap) + bar_width // 2
    dot_cy = base_y - int(canvas * 0.58) - int(canvas * 0.03)
    draw.ellipse([dot_cx - dot_r, dot_cy - dot_r, dot_cx + dot_r, dot_cy + dot_r], fill=(255, 255, 255, 255))

    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    master = draw_icon(max(SIZES))                                  # 只渲染一次大图
    layers = [master.resize((size, size), Image.LANCZOS) for size in SIZES]
    master.save(OUTPUT, format="ICO", sizes=[(s, s) for s in SIZES], append_images=layers)
    print(f"图标已生成: {OUTPUT} ({os.path.getsize(OUTPUT)} bytes)")


if __name__ == "__main__":
    main()
