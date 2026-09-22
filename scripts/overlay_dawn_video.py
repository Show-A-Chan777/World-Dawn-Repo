#!/usr/bin/env python3
"""
World Dawn × Bible Verses — text overlay tool

Notion「World Dawn × Bible Verses 制作ルーティーン」の定型テンプレート
(参考画像: IMG_2805)に従い、Artlistで生成した夜明け動画に6要素の
テキストオーバーレイを焼き込む。

レイアウト:
  - 上下に黒帯(レターボックス)
  - 白文字・セリフ体(Noto Serif CJK JP)・影付き
  - 画面中央やや下寄りに、以下の順で中央揃え配置:
      1. 日本語聖句(中サイズ)
      2. 英語聖句 NIV(やや小さめ、2行まで可)
      3. 日本語聖書箇所(大きめ)
      4. 英語聖書箇所(大きめ・太字)
      5. ロケーション名(英語 / 国名)
      6. ブランド名「World Dawn」(ロケーション名のすぐ下)
  - 全要素フェードイン
  - 動画終端は映像(音声・BGMがあればそれらも)がフェードアウトして終わる
  - --bgm を渡すと、BGMをクリップの長さにループ/トリムし、環境音があれば
    その下にミックスする(既定で環境音より音量を落とす)。BGMは冒頭で
    フェードイン、終端で他の音声と一緒にフェードアウトする。

Usage:
    python3 overlay_dawn_video.py \\
        --input source.mp4 --output final.mp4 \\
        --jp-verse "夜には泣きながら過ごしても、朝には喜びの歌がある" \\
        --en-verse "weeping may stay for the night, but rejoicing comes in the morning" \\
        --jp-ref "詩篇 30:5" --en-ref "Psalm 30:5" \\
        --location "Zhangjiajie / China" \\
        --bgm bgm/world_dawn_theme.mp3

Requires: ffmpeg (with libfreetype/libfontconfig), Pillow, and the
"Noto Serif CJK JP" font installed (fonts-noto-cjk).
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import ImageFont

CJK_FONT_TTC = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"
# Use direct fontfile= paths rather than fontconfig font='...:style=Bold'
# lookups: ffmpeg's drawtext + fontconfig style matching was observed to
# silently fall back to a CJK-incapable face for some strings (tofu glyphs)
# even though `fc-match` resolves the same query correctly. Face index 0 in
# both TTCs is the Japanese ("JP") face (verified via `fc-query`).
FONT_REGULAR_FILE = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"
FONT_BOLD_FILE = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"

FADE_START = 0.2  # text fade-in start (seconds into the clip)
FADE_DUR = 0.8  # text fade-in duration
FADE_OUT_DUR = 0.6  # whole-frame (and audio, if present) fade-to-black at the end


def ffprobe_dimensions(path: str) -> tuple[int, int]:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json", path,
        ],
        check=True, capture_output=True, text=True,
    )
    info = json.loads(out.stdout)["streams"][0]
    return int(info["width"]), int(info["height"])


def ffprobe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
        check=True, capture_output=True, text=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def has_audio_stream(path: str) -> bool:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a",
            "-show_entries", "stream=index", "-of", "json", path,
        ],
        check=True, capture_output=True, text=True,
    )
    return bool(json.loads(out.stdout).get("streams"))


def _measure(font: ImageFont.FreeTypeFont, text: str) -> float:
    bbox = font.getbbox(text)
    return bbox[2] - bbox[0]


def wrap_text(text: str, size_px: int, max_width: float, lang: str, max_lines: int = 2) -> list[str]:
    """Greedy-wrap text to fit max_width, capped at max_lines by shrinking font size."""
    font = ImageFont.truetype(CJK_FONT_TTC, size_px, index=0)

    if lang == "en":
        tokens = text.split(" ")
        sep = " "
    else:
        # Wrap by character; keep trailing 、 。 attached to the previous char.
        tokens = []
        for ch in text:
            if tokens and ch in "、。,.":
                tokens[-1] += ch
            else:
                tokens.append(ch)
        sep = ""

    def do_wrap(font):
        lines, cur = [], ""
        for tok in tokens:
            cand = (cur + sep + tok) if cur else tok
            if _measure(font, cand) <= max_width or not cur:
                cur = cand
            else:
                lines.append(cur)
                cur = tok
        if cur:
            lines.append(cur)
        return lines

    lines = do_wrap(font)
    return lines


def fit_single_line(text: str, size_px: int, max_width: float) -> int:
    """Shrink font size until the single line fits within max_width."""
    size = size_px
    while size > 10:
        font = ImageFont.truetype(CJK_FONT_TTC, size, index=0)
        if _measure(font, text) <= max_width:
            return size
        size -= 2
    return size


def esc_path(p: str) -> str:
    # ffmpeg filter argument escaping for textfile= paths on Linux.
    return p.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def build_overlay(input_path, output_path, jp_verse, en_verse, jp_ref, en_ref, location, brand, tmpdir, bgm_path=None, bgm_volume=0.25):
    w, h = ffprobe_dimensions(input_path)

    top_bar = round(h * 0.09)
    bottom_bar = round(h * 0.10)
    max_w = w * 0.86

    # Nominal font sizes as a fraction of width, then auto-fit.
    jp_verse_size = round(w * 0.075)
    en_verse_size = round(w * 0.045)
    jp_ref_size = round(w * 0.095)
    en_ref_size = round(w * 0.085)
    loc_size = round(w * 0.06)
    brand_size = round(w * 0.045)

    # Shrink verse font sizes until they wrap into <=2 lines.
    def fit_wrap(text, size, lang):
        s = size
        while s > 12:
            lines = wrap_text(text, s, max_w, lang)
            if len(lines) <= 2:
                return s, lines
            s -= 2
        return s, wrap_text(text, s, max_w, lang)

    jp_verse_size, jp_verse_lines = fit_wrap(jp_verse, jp_verse_size, "ja")
    en_verse_size, en_verse_lines = fit_wrap(en_verse, en_verse_size, "en")
    jp_ref_size = fit_single_line(jp_ref, jp_ref_size, max_w)
    en_ref_size = fit_single_line(en_ref, en_ref_size, max_w)
    loc_size = fit_single_line(location, loc_size, max_w)
    brand_size = fit_single_line(brand, brand_size, max_w)

    # --- Vertical layout: items 1-5 centered as a block, slightly below screen center ---
    def line_h(size):
        return round(size * 1.35)

    group_lines = (
        [(l, jp_verse_size, FONT_REGULAR_FILE) for l in jp_verse_lines]
        + [(l, en_verse_size, FONT_REGULAR_FILE) for l in en_verse_lines]
        + [(jp_ref, jp_ref_size, FONT_BOLD_FILE)]
        + [(en_ref, en_ref_size, FONT_BOLD_FILE)]
        + [(location, loc_size, FONT_REGULAR_FILE)]
        + [(brand, brand_size, FONT_BOLD_FILE)]
    )
    gap_after_group = {
        len(jp_verse_lines) - 1: round(jp_verse_size * 0.55),  # after verse block
        len(jp_verse_lines) + len(en_verse_lines) - 1: round(en_verse_size * 0.75),  # after en verse
        len(jp_verse_lines) + len(en_verse_lines): round(jp_ref_size * 0.35),  # after jp ref
        len(jp_verse_lines) + len(en_verse_lines) + 1: round(en_ref_size * 0.55),  # after en ref
        len(jp_verse_lines) + len(en_verse_lines) + 2: round(loc_size * 0.45),  # after location
    }

    heights = [line_h(sz) for _, sz, _ in group_lines]
    total_h = sum(heights) + sum(gap_after_group.values())

    avail_top = top_bar
    avail_bottom = h - bottom_bar
    center_y = avail_top + (avail_bottom - avail_top) * 0.56  # slightly below center
    y = round(center_y - total_h / 2)

    drawtext_filters = []
    for idx, (text, size, fontfile) in enumerate(group_lines):
        txt_file = Path(tmpdir) / f"line_{idx}.txt"
        txt_file.write_text(text, encoding="utf-8")
        drawtext_filters.append(
            f"drawtext=fontfile='{esc_path(fontfile)}':"
            f"textfile='{esc_path(str(txt_file))}':fontsize={size}:fontcolor=white:"
            f"x=(w-text_w)/2:y={y}:shadowcolor=black@0.85:shadowx=2:shadowy=2:"
            f"alpha='min(1,max(0,(t-{FADE_START})/{FADE_DUR}))'"
        )
        y += heights[idx] + gap_after_group.get(idx, 0)

    letterbox = [
        f"drawbox=x=0:y=0:w=iw:h={top_bar}:color=black@1.0:t=fill",
        f"drawbox=x=0:y=ih-{bottom_bar}:w=iw:h={bottom_bar}:color=black@1.0:t=fill",
    ]

    # Whole-frame fade to black at the very end of the clip (applied after the
    # letterbox/text so it fades everything together).
    duration = ffprobe_duration(input_path)
    fade_out_dur = min(FADE_OUT_DUR, duration / 2)
    fade_out_start = max(0.0, duration - fade_out_dur)
    fade_filter = [f"fade=t=out:st={fade_out_start:.3f}:d={fade_out_dur:.3f}"]

    vf = ",".join(letterbox + drawtext_filters + fade_filter)

    has_ambient = has_audio_stream(input_path)
    fade_in_dur = min(1.0, duration / 4)

    cmd = ["ffmpeg", "-y", "-i", input_path]
    if bgm_path:
        # Loop the BGM indefinitely; it gets trimmed to the clip's duration below.
        cmd += ["-stream_loop", "-1", "-i", bgm_path]

    filter_complex = [f"[0:v]{vf}[vout]"]

    audio_out = None
    if bgm_path:
        filter_complex.append(
            f"[1:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,"
            f"volume={bgm_volume},"
            f"afade=t=in:st=0:d={fade_in_dur:.3f},"
            f"afade=t=out:st={fade_out_start:.3f}:d={fade_out_dur:.3f}[bgm]"
        )
        if has_ambient:
            filter_complex.append(
                f"[0:a]afade=t=out:st={fade_out_start:.3f}:d={fade_out_dur:.3f}[amb]"
            )
            # `amix ... duration=first` has been observed to mis-estimate the
            # mixed stream's length when run in the same graph as a video
            # encode, so force an explicit trim to the known clip duration
            # afterwards rather than trusting it.
            filter_complex.append(
                f"[amb][bgm]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,"
                f"atrim=0:{duration:.3f},asetpts=PTS-STARTPTS[aout]"
            )
        else:
            filter_complex.append(f"[bgm]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS[aout]")
        audio_out = "aout"
    elif has_ambient:
        filter_complex.append(
            f"[0:a]afade=t=out:st={fade_out_start:.3f}:d={fade_out_dur:.3f}[aout]"
        )
        audio_out = "aout"

    cmd += ["-filter_complex", ";".join(filter_complex), "-map", "[vout]"]
    if audio_out:
        cmd += ["-map", f"[{audio_out}]", "-c:a", "aac"]
    else:
        cmd += ["-an"]

    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium", output_path]
    subprocess.run(cmd, check=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--jp-verse", required=True)
    p.add_argument("--en-verse", required=True)
    p.add_argument("--jp-ref", required=True)
    p.add_argument("--en-ref", required=True)
    p.add_argument("--location", required=True)
    p.add_argument("--brand", default="World Dawn")
    p.add_argument("--bgm", help="Optional background music file, looped/trimmed to the clip's length and mixed under any ambient audio.")
    p.add_argument("--bgm-volume", type=float, default=0.25, help="BGM volume multiplier relative to ambient audio (default 0.25).")
    args = p.parse_args()

    with tempfile.TemporaryDirectory() as tmpdir:
        build_overlay(
            args.input, args.output,
            args.jp_verse, args.en_verse, args.jp_ref, args.en_ref, args.location, args.brand,
            tmpdir, bgm_path=args.bgm, bgm_volume=args.bgm_volume,
        )
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    sys.exit(main())
