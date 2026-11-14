"""Contact sheets from storyboard sprite images: cut the chosen thumbnails, print the time on
each, and write JPEG sheets with a table that says where every frame sits.

Needs Pillow, an optional extra (``pip install "gather-engine[frames]"``). ``available`` says
whether it can be imported; without it the bundle records that the sheets were not cut. The
output depends only on the inputs: the same sprite bytes and plan give byte-identical sheets
and the same table on every run with the same Pillow.

A sheet holds 6 frames to a row and 4 rows, about 2000 pixels wide. A thumbnail narrower than
320 pixels is enlarged by a whole factor so the printed time stays readable; the table and the
manifest keep the real thumbnail size.
"""

from __future__ import annotations

import io
import os

from gather.storyboard import Frame, Level
from gather.video_bundle import clock

COLUMNS = 6
ROWS = 4
CELL_WIDTH = 320
GAP = 8
QUALITY = 88
GROUND = (16, 16, 16)
NEEDS = 'Pillow is not installed (pip install "gather-engine[frames]")'
TABLE_HEAD = "time_s\ttime\tsheet\trow\tcolumn\tx\ty\twidth\theight\tframe\n"


def available() -> bool:
    try:
        import PIL  # noqa: F401
    except ImportError:
        return False
    return True


def cell_size(level: Level) -> tuple[int, int]:
    """The size a thumbnail is drawn at: enlarged by a whole factor up to 320 wide, or reduced
    to 320 wide when the site's thumbnail is wider."""
    if level.width >= CELL_WIDTH:
        return CELL_WIDTH, max(1, round(level.height * CELL_WIDTH / level.width))
    factor = max(1, CELL_WIDTH // level.width)
    return level.width * factor, level.height * factor


def _font(size: int):
    from PIL import ImageFont

    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow before 10.1 has one fixed bitmap font
        return ImageFont.load_default()


def _label(draw, font, x: int, y: int, cell_h: int, text: str) -> None:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    w, h = right - left, bottom - top
    by = y + cell_h - h - 10
    draw.rectangle((x, by, x + w + 10, y + cell_h), fill=(0, 0, 0))
    draw.text((x + 5 - left, by + 5 - top), text, font=font, fill=(255, 255, 255))


def _cut(sprites: dict, frame: Frame, level: Level, blobs: dict[int, bytes]):
    """The thumbnail for ``frame``, or None when its sprite image is missing or too small."""
    from PIL import Image

    if frame.fragment not in sprites:
        blob = blobs.get(frame.fragment)
        try:
            sprites[frame.fragment] = Image.open(io.BytesIO(blob)).convert("RGB") if blob else None
        except (OSError, ValueError):
            sprites[frame.fragment] = None
    sprite = sprites[frame.fragment]
    box = (frame.column * level.width, frame.row * level.height,
           (frame.column + 1) * level.width, (frame.row + 1) * level.height)
    if sprite is None or box[2] > sprite.width or box[3] > sprite.height:
        return None
    return sprite.crop(box)


def write_sheets(out_dir: str, vid: str, level: Level, plan: list[Frame], blobs: dict[int, bytes]) -> dict:
    """Write ``<vid>.frames-NN.jpg`` and ``<vid>.frames.tsv`` into ``out_dir`` and return
    ``{count, missing, sheets, table, sheet_px, cell_px}``. A frame whose sprite image did not
    arrive is left out and counted in ``missing``."""
    from PIL import Image, ImageDraw

    cell_w, cell_h = cell_size(level)
    font = _font(max(12, cell_h // 10))
    sprites: dict = {}
    cut = [(f, img) for f, img in ((f, _cut(sprites, f, level, blobs)) for f in plan) if img is not None]
    sheets: list[str] = []
    rows_out = [TABLE_HEAD]
    width = COLUMNS * cell_w + (COLUMNS + 1) * GAP
    for n in range(0, len(cut), COLUMNS * ROWS):
        part = cut[n:n + COLUMNS * ROWS]
        lines = -(-len(part) // COLUMNS)
        sheet = Image.new("RGB", (width, lines * cell_h + (lines + 1) * GAP), GROUND)
        draw = ImageDraw.Draw(sheet)
        name = f"{vid}.frames-{len(sheets) + 1:02d}.jpg"
        for k, (frame, img) in enumerate(part):
            r, c = divmod(k, COLUMNS)
            x, y = GAP + c * (cell_w + GAP), GAP + r * (cell_h + GAP)
            if img.size != (cell_w, cell_h):
                img = img.resize((cell_w, cell_h), Image.Resampling.BICUBIC)
            sheet.paste(img, (x, y))
            _label(draw, font, x, y, cell_h, clock(frame.time))
            rows_out.append(f"{frame.time:.3f}\t{clock(frame.time)}\t{name}\t{r + 1}\t{c + 1}\t{x}\t{y}\t{cell_w}\t{cell_h}\t{frame.index}\n")
        sheet.save(os.path.join(out_dir, name), "JPEG", quality=QUALITY)
        sheets.append(name)
    table = f"{vid}.frames.tsv"
    with open(os.path.join(out_dir, table), "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(rows_out))
    return {"count": len(cut), "missing": len(plan) - len(cut), "sheets": sheets, "table": table,
            "sheet_px": [width, ROWS * cell_h + (ROWS + 1) * GAP], "cell_px": [cell_w, cell_h]}
