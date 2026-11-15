from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).parent
W, H = 1280, 720
font_path = r"C:\Windows\Fonts\msyh.ttc"
title_font = ImageFont.truetype(font_path, 48)
body_font = ImageFont.truetype(font_path, 30)
small_font = ImageFont.truetype(font_path, 24)
mono = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 24)

def slide(name, title, lines, table=False):
    im = Image.new("RGB", (W, H), (250, 249, 246))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 8], fill=(47, 93, 80))
    d.text((70, 55), title, font=title_font, fill=(31, 31, 28))
    y = 160
    for line in lines:
        d.text((74, y), line, font=body_font, fill=(55, 55, 52))
        y += 52
    if table:
        x0, y0 = 74, 330
        rows = [("方法", "准确率", "备注"), ("RNN", "72%", "慢"), ("LSTM", "78%", "长依赖"), ("Transformer", "85%", "并行")]
        widths = [300, 220, 360]
        for r, row in enumerate(rows):
            yy = y0 + r * 64
            d.rectangle([x0, yy, x0 + sum(widths), yy + 64], outline=(180, 176, 166), width=2)
            x = x0
            for c, cell in enumerate(row):
                d.rectangle([x, yy, x + widths[c], yy + 64], outline=(200, 196, 186), width=1)
                d.text((x + 18, yy + 15), cell, font=body_font, fill=(31, 31, 28))
                x += widths[c]
    im.save(root / name, "PNG")

slide("slide1.png", "注意力机制：为什么有效", [
    "Transformer 用注意力直接建模长距离依赖。",
    "关键：Query、Key、Value 三组向量。",
    "问题：长视频里，表格和公式常常只在画面上。",
])
slide("slide2.png", "实验结果：三种模型对比", [
    "数据集：LongVideoBench 子集，指标：准确率。",
], table=True)
slide("slide3.png", "结论与限制", [
    "注意力不是万能：数据质量、采样、时间戳都会影响结果。",
    "下一步：把证据和时间戳一起交给模型。",
])
print("slides ready")
