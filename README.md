# World-Dawn-Repo
世界の夜明けの動画を作成

## テキストオーバーレイ (scripts/overlay_dawn_video.py)

Notion「World Dawn × Bible Verses 制作ルーティーン」の定型テンプレート
(参考画像: IMG_2805)に従い、Artlistで生成した夜明け動画に下記6要素の
テキストを焼き込む ffmpeg ベースのツール。

- 上下に黒帯(レターボックス)
- 白文字・セリフ体(Noto Serif CJK JP)・影付き・フェードイン
- 画面中央やや下寄りに、日本語聖句 → 英語聖句(NIV) → 日本語聖書箇所 →
  英語聖書箇所 → ロケーション名 → ブランド名「World Dawn」の順で中央揃え配置
- 動画終端は映像(音声・BGMがあればそれらも)がフェードアウト
- `--bgm` でBGMをクリップの長さにループ/トリムして環境音の下にミックス
  (既定で音量25%、冒頭フェードイン)

### 必要な環境

```bash
apt-get install -y ffmpeg fonts-noto-cjk
pip install --break-system-packages pillow
```

### 使い方

```bash
python3 scripts/overlay_dawn_video.py \
  --input source.mp4 --output final.mp4 \
  --jp-verse "夜には泣きながら過ごしても、朝には喜びの歌がある" \
  --en-verse "weeping may stay for the night, but rejoicing comes in the morning" \
  --jp-ref "詩篇 30:5" --en-ref "Psalm 30:5" \
  --location "Zhangjiajie / China" \
  --bgm bgm/world_dawn_theme.mp3
```

`--brand` を省略すると既定値「World Dawn」が使われる。`--bgm` は省略可能
(省略時は元動画の音声のみ、無音なら無音のまま)。`--bgm-volume` でBGM音量
を調整できる(既定0.25 = 環境音より控えめ)。

### 既知の制限

このリポジトリを扱うClaude Code(World Dawn環境)のサンドボックスは、
組織のネットワークポリシーにより `*.artlist.io` への直接アクセスが
ブロックされている(`curl`で `CONNECT tunnel failed, response 403`)。
そのため、Artlistが発行する動画URLからのダウンロードがこの環境では
実行できない。動画ファイルを他の経路(手元のブラウザ等)で入手した上で、
このスクリプトに `--input` として渡すこと。
