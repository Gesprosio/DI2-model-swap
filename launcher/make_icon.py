"""Draws the launcher icon (icon.ico + icon_preview.png): a stylized nod to Dead Island 2 - LA sunset,
palm silhouette, a big blood-dripping "2" - not the game's logo. Run once; PyInstaller uses icon.ico."""
import math
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

S = 1024  # drawn large, scaled down for every icon size
HERE = os.path.dirname(os.path.abspath(__file__))


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size - 1, size - 1), radius, fill=255)
    return m


def draw():
    img = Image.new("RGB", (S, S))
    d = ImageDraw.Draw(img)
    # sunset sky: deep purple -> magenta -> orange
    stops = [(0.0, (38, 14, 58)), (0.45, (170, 38, 92)), (0.75, (238, 102, 48)), (1.0, (252, 170, 60))]
    for y in range(S):
        t = y / (S - 1)
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t0 <= t <= t1:
                d.line((0, y, S, y), fill=lerp(c0, c1, (t - t0) / (t1 - t0)))
                break
    # sun with horizontal stripes (retro LA sunset)
    cx, cy, r = S * 0.5, S * 0.64, S * 0.30
    sun = Image.new("L", (S, S), 0)
    sd = ImageDraw.Draw(sun)
    sd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    for i in range(5):
        y = cy + r * (0.12 + i * 0.17)
        sd.rectangle((0, y, S, y + S * (0.012 + i * 0.006)), fill=0)
    img.paste((255, 214, 120), (0, 0), sun)
    # ground / sea line
    d.rectangle((0, S * 0.80, S, S), fill=(28, 10, 34))

    dark = (24, 8, 28)
    # palm tree: curved trunk + fronds
    trunk = []
    for i in range(41):
        t = i / 40
        x = S * 0.20 + math.sin(t * 1.3) * S * 0.10
        y = S * 0.82 - t * S * 0.56
        w = S * (0.030 - 0.012 * t)
        trunk.append((x, y, w))
    left = [(x - w, y) for x, y, w in trunk]
    right = [(x + w, y) for x, y, w in reversed(trunk)]
    d.polygon(left + right, fill=dark)
    top = trunk[-1][:2]
    for ang, length in ((-160, 0.30), (-125, 0.26), (-60, 0.30), (-20, 0.27), (15, 0.22), (-95, 0.20)):
        a = math.radians(ang)
        pts = []
        for i in range(21):
            t = i / 20
            droop = S * 0.10 * t * t
            px = top[0] + math.cos(a) * S * length * t
            py = top[1] + math.sin(a) * S * length * t + droop
            half = S * 0.035 * math.sin(math.pi * t)
            pts.append((px, py, half))
        up = [(x, y - h) for x, y, h in pts]
        down = [(x, y + h) for x, y, h in reversed(pts)]
        d.polygon(up + down, fill=dark)

    # big "2" with a dark outline and blood drips
    font = None
    for name in ("impact.ttf", "ariblk.ttf", "arialbd.ttf"):
        try:
            font = ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name), int(S * 0.78))
            break
        except OSError:
            continue
    text_layer = Image.new("L", (S, S), 0)
    td = ImageDraw.Draw(text_layer)
    box = td.textbbox((0, 0), "2", font=font)
    tx = S * 0.60 - (box[0] + box[2]) / 2
    ty = S * 0.44 - (box[1] + box[3]) / 2
    td.text((tx, ty), "2", font=font, fill=255)
    outline = text_layer.filter(ImageFilter.MaxFilter(41))
    img.paste(dark, (0, 0), outline)
    blood = (196, 18, 30)
    img.paste(blood, (0, 0), text_layer)
    # drips under the bottom stroke of the 2
    bd = ImageDraw.Draw(img)
    base_y = ty + box[3] - S * 0.02
    for x_rel, length, w in ((0.47, 0.13, 0.030), (0.58, 0.20, 0.036), (0.69, 0.10, 0.026), (0.76, 0.16, 0.030)):
        x = S * x_rel
        bd.rectangle((x - S * w / 2, base_y - S * 0.02, x + S * w / 2, base_y + S * length), fill=blood)
        bd.ellipse((x - S * w * 0.8, base_y + S * length - S * w * 0.8,
                    x + S * w * 0.8, base_y + S * length + S * w * 0.8), fill=blood)
    # highlight on the 2
    shine = text_layer.point(lambda v: v)
    shine_mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(shine_mask).rectangle((0, 0, S, ty + (box[1] + box[3]) / 2 - S * 0.06), fill=70)
    img.paste((255, 120, 110), (0, 0), Image.composite(shine_mask, Image.new("L", (S, S), 0), shine))

    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(img, (0, 0), rounded_mask(S, int(S * 0.20)))
    return out


if __name__ == "__main__":
    icon = draw()
    icon.resize((256, 256), Image.LANCZOS).save(os.path.join(HERE, "icon_preview.png"))
    icon.save(os.path.join(HERE, "icon.ico"), sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)])
    # small sizes side by side, to check readability
    strip = Image.new("RGBA", (256 + 128 + 64 + 32 + 16 + 50, 256), (22, 24, 29, 255))
    x = 0
    for s in (256, 128, 64, 32, 16):
        strip.paste(icon.resize((s, s), Image.LANCZOS), (x, 256 - s), icon.resize((s, s), Image.LANCZOS))
        x += s + 10
    strip.save(os.path.join(HERE, "icon_sizes.png"))
    print("ok")
