# blentopy

**PythonでBlenderの3Dシーンを作成し、GUIで確認・編集したり、MP4まで自動出力したりするためのローカルAI操作ブリッジ。**

blentopy自体はAIモデルではありません。ChatGPTなどのMCP対応AIがシーンのPythonコードを考え、ローカルのblentopyがBlenderを起動して実行します。AI APIキーはblentopy側には不要です。

> まだプロトタイプです。GUIプレビューとMP4レンダリングの実機確認は、使用するMacとBlenderのバージョンで行ってください。

## 目次

- [できること・できないこと](#できることできないこと)
- [必要な環境](#必要な環境)
- [インストール](#インストール)
- [アップデート](#アップデート)
- [Blenderの認識確認](#blenderの認識確認)
- [GUIプレビューを使う](#guiプレビューを使う)
- [MP4をレンダリングする](#mp4をレンダリングする)
- [シーン用Pythonコードの書き方](#シーン用pythonコードの書き方)
- [Studio API リファレンス](#studio-api-リファレンス)
- [音声を使う](#音声を使う)
- [MCPでチャットAIと接続する](#mcpでチャットaiと接続する)
- [出力ファイル](#出力ファイル)
- [トラブルシューティング](#トラブルシューティング)
- [テスト](#テスト)
- [安全性について](#安全性について)
- [現在の制限](#現在の制限)

## できること・できないこと

### できること

- Blender GUIを開き、Pythonスクリプトからシーンを作成する
- GUIプレビューで生成したシーンを確認し、そのまま手動編集する
- Cube、Sphere、Cylinder、Plane、テキストなどの基本オブジェクトを作る
- マテリアル、カメラ、ライトを設定する
- オブジェクトの移動・回転・拡縮アニメーションをキーフレームで作る
- 既存の音声ファイルを動画タイムラインに配置する
- MP4 (H.264) と編集可能な .blend ファイルを出力する
- MCP対応チャットからローカルBlenderの操作を呼び出す

### 現状まだできないこと

- AIが自動で複雑な3Dモデルやキャラクターを生成する
- リギング、歩行アニメーション、モーションキャプチャ
- 音声・BGMを自動生成する
- 画像を理解して自由にモデリングする
- エラー発生時にAIが自動で原因分析・修復・再実行する
- GUI上のオブジェクトを見ながらリアルタイムにAIが連続操作する（現状はスクリプト実行単位）

## 必要な環境

- macOS / Windows / Linux (GUIプレビューにはデスクトップ環境が必要)
- Python 3.11 以降
- Blender 4.2 以降を推奨
- GUIプレビュー: BlenderがGUIで起動できること
- MCP接続を使う場合: MCP SDK 2.x

Python環境とBlender内部のPython環境は別物です。blentopyは外側のPythonからBlender実行ファイルを呼び出し、Blender内で専用ワーカーを実行します。

## インストール

ターミナルでリポジトリのディレクトリに移動します。

\`\`\`bash
cd blentopy
\`\`\`

仮想環境を作成し、有効化します。

\`\`\`bash
python3 -m venv .venv
source .venv/bin/activate
\`\`\`

パッケージを開発モードでインストールします。

\`\`\`bash
python -m pip install --upgrade pip
python -m pip install -e .
\`\`\`

MCP機能も使う場合は、追加依存関係込みでインストールします。

\`\`\`bash
python -m pip install -e '.[mcp]'
\`\`\`

> 仮想環境を使うことを推奨します。以降のコマンドは、同じターミナルで \`.venv\` を有効化して実行してください。

## アップデート

GitHubのmainブランチから最新コードを取得します。

\`\`\`bash
git switch main
git pull --ff-only origin main
source .venv/bin/activate
python -m pip install -e . --force-reinstall
\`\`\`

CLIのコマンド一覧を確認します。

\`\`\`bash
blentopy --help
\`\`\`

\`preview\`, \`render\`, \`demo\`, \`doctor\` などが表示されればCLIの読み込みができています。

\`preview\` が \`invalid choice\` と表示される場合、古いCLIがインストールされたままか、別のPython環境を使っている可能性があります。上記の再インストールを実行し、次を確認してください。

\`\`\`bash
which blentopy
python -m pip show blentopy
blentopy --help
\`\`\`

## Blenderの認識確認

BlenderがPATHから見つかるかを確認します。

\`\`\`bash
blentopy doctor
\`\`\`

Blenderが見つからない場合は実行ファイルを明示します。

### macOS

\`\`\`bash
blentopy doctor --blender /Applications/Blender.app/Contents/MacOS/Blender
\`\`\`

Blenderのアプリ名やインストール場所を変更している場合は、その実際のパスを指定してください。環境変数 \`BLENTOPY_BLENDER\` にBlender実行ファイルのパスを設定することもできます。

\`\`\`bash
export BLENTOPY_BLENDER="/Applications/Blender.app/Contents/MacOS/Blender"
\`\`\`

設定した環境変数は、同じターミナルから実行するコマンドに適用されます。

## GUIプレビューを使う

GUIプレビューは、**Blenderを画面に表示しながらシーンを生成して、生成した .blend を開いた状態で確認・編集する機能**です。MP4レンダリングは行いません。

### 基本コマンド

リポジトリのルートで実行します。

\`\`\`bash
blentopy preview examples/demo_scene.py
\`\`\`

Blenderの実行ファイルがPATHにないmacOSでは、次のように指定します。

\`\`\`bash
blentopy preview examples/demo_scene.py \\
  --blender /Applications/Blender.app/Contents/MacOS/Blender
\`\`\`

### GUIプレビューの動作

1. blentopyがBlenderをGUIモードで起動します。
2. Blender内でスクリプトを読み込み、許可されたStudio APIを実行します。
3. シーン、カメラ、ライト、マテリアルなどを設定します。
4. \`.blend\` ファイルを保存します。
5. 保存成功をCLI側が確認します。
6. BlenderのGUIは終了せず、開いたままになります。
7. CLIに保存先とログファイル、BlenderのPIDが表示されます。

Blenderが開いても、保存完了を確認する前に成功とは表示しません。

### プレビューのオプション

\`\`\`bash
blentopy preview examples/demo_scene.py \\
  --blender /Applications/Blender.app/Contents/MacOS/Blender \\
  --blend-output renders/my_preview.blend \\
  --workspace blentopy-workspace \\
  --width 720 \\
  --height 1280 \\
  --fps 30 \\
  --duration 8 \\
  --startup-timeout 120
\`\`\`

| オプション | 説明 | デフォルト |
|---|---|---|
| \`script\` | 実行するシーンPythonファイル | 必須 |
| \`--blender\` | Blender実行ファイルのパス | PATH / 環境変数から検索 |
| \`--blend-output\` | 保存する.blendのパス | \`renders/<script名>.blend\` |
| \`--workspace\` | 音声素材などの作業フォルダ | \`blentopy-workspace\` |
| \`--width\` | 出力幅 (px) | 720 |
| \`--height\` | 出力高さ (px) | 1280 |
| \`--fps\` | フレームレート | 30 |
| \`--duration\` | シーン長 (秒) | 8 |
| \`--startup-timeout\` | シーン保存完了までの待機上限 (秒) | 120 |

起動タイムアウトは1〜600秒です。タイムアウトやシーン構築エラーが起きた場合、ログを確認してください。

### Blender内で確認・編集する

GUIプレビューが成功したらBlenderで次の操作ができます。

- 3D Viewでカメラ・オブジェクト・ライトを確認
- Outlinerからオブジェクトを選択
- Transformを手動変更
- マテリアルを調整
- Timelineでアニメーションを確認
- Blender標準の保存操作で編集内容を保存

生成した .blend は通常のBlenderプロジェクトです。blentopy独自形式ではありません。

## MP4をレンダリングする

GUIプレビューではなく、完成動画ファイルを書き出したい場合は \`render\` または \`demo\` コマンドを使います。

### サンプルをレンダリング

\`\`\`bash
blentopy demo
\`\`\`

macOSでBlenderを明示する場合:

\`\`\`bash
blentopy demo \\
  --blender /Applications/Blender.app/Contents/MacOS/Blender \\
  --output renders/demo.mp4
\`\`\`

### 自分のシーンスクリプトをレンダリング

\`\`\`bash
blentopy render examples/demo_scene.py \\
  --output renders/custom.mp4
\`\`\`

### Renderのオプション

\`render\` と \`demo\` には共通オプションがあります。

| オプション | 説明 | デフォルト |
|---|---|---|
| \`--blender\` | Blender実行ファイル | 自動検出 |
| \`--output\` | MP4出力先 | \`renders/<script名>.mp4\` |
| \`--blend-output\` | Blenderプロジェクト保存先 | MP4と同じ名前の.blend |
| \`--workspace\` | 素材の作業フォルダ | \`blentopy-workspace\` |
| \`--width\` | 動画幅 | 720 |
| \`--height\` | 動画高さ | 1280 |
| \`--fps\` | フレームレート | 30 |
| \`--duration\` | 動画の長さ (秒) | 8 |
| \`--timeout\` | レンダリングの最大時間 (秒) | 3600 |

レンダリング設定は幅・高さ256〜1920px、総解像度419万px以下、FPS 1〜60、長さ1〜120秒、最大3600フレームの制限があります。

## シーン用Pythonコードの書き方

AIが生成するコードも、手動で書くコードも、**blentopyが許可しているStudio APIの呼び出しだけ**を使います。

Blenderの通常のPythonコードと異なり、スクリプト内で \`bpy\` を直接使うことはできません。シーン操作は \`studio\` 経由で行います。

### 最小のシーン

\`\`\`python
studio.set_timeline(duration_seconds=6, fps=30)
studio.set_world_color((0.02, 0.03, 0.06))

studio.add_cube(
    "Cube",
    location=(0, 0, 1),
    scale=(1, 1, 1),
    color=(0.1, 0.4, 0.9),
)

studio.add_camera(
    "Camera",
    location=(0, -12, 3),
    target=(0, 0, 1),
    orthographic_scale=7,
)

studio.add_area_light(
    "KeyLight",
    location=(-4, -5, 6),
    target=(0, 0, 1),
    energy=1400,
)
\`\`\`

### スクリプトの基本ルール

- \`studio\` と \`math\` が使用可能です。自分でimportする必要はありません。
- APIの引数はキーワード指定を推奨します。読みやすく、AIが修正しやすくなります。
- オブジェクト名は一意にしてください。アニメーションで指定する名前は、作成時の名前と一致させます。
- 座標とサイズはBlenderのワールド単位です。
- 色はRGBまたはRGBA、各値0〜1です。
- 回転アニメーションの角度はAPIに渡す時は度数です。
- シーンの長さは秒、FPSはフレームレートです。
- 3Dオブジェクトを配置しただけではカメラに映るとは限りません。カメラ位置・向き・画角を設定してください。
- テキストのデフォルト回転は正面向け用の角度です。カメラの向きに応じて調整できます。
- Pythonのimport、for/while、if、関数定義、ファイル操作などは現在の制限付き構文では使えません。

### AIにシーンを作ってもらう例

MCPを使わずにAIへコード生成を依頼する場合は、例えば次のように指示します。

> blentopyのStudio APIだけを使って、8秒の縦動画向け3Dシーンを作ってください。冒頭から最後までオブジェクトの動きがあり、カメラ・ライト・マテリアルも設定してください。Pythonのimport、bpy、ループ、関数定義は禁止。コードだけ出してください。

生成されたコードを \`examples/my_scene.py\` などに保存し、GUIプレビューで確認します。

\`\`\`bash
blentopy preview examples/my_scene.py
\`\`\`

## Studio API リファレンス

### 共通の値

| 値 | 意味 | 例 |
|---|---|---|
| \`location\` | 位置 X/Y/Z | \`(0, 0, 2)\` |
| \`scale\` | X/Y/Zの倍率 | \`(1, 2, 1)\` |
| \`target\` | カメラ・ライトが向く座標 | \`(0, 0, 0)\` |
| \`color\` | RGB/RGBAの色、0〜1 | \`(0.2, 0.5, 1.0)\` |
| \`size\` | 形状の大きさ、またはライトサイズ | APIごとに意味が異なる |
| \`start_frame/end_frame\` | アニメーションの開始・終了フレーム | \`1, 120\` |
| \`start_seconds\` | 音声の開始時刻 (秒) | \`2.5\` |

### タイムライン・ワールド

\`\`\`python
studio.set_timeline(duration_seconds=8, fps=30)
studio.set_world_color((0.025, 0.03, 0.05))
\`\`\`

- \`set_timeline(duration_seconds, fps=None)\`: シーンの長さとFPSを設定
- \`set_world_color(color)\`: 背景/ワールドの色を設定

### 形状

\`\`\`python
studio.add_plane(
    "Ground", location=(0, 0, 0),
    scale=(5, 5, 1), color=(0.08, 0.10, 0.14)
)

studio.add_cube(
    "Cube", location=(0, 0, 1),
    scale=(1, 1, 1), color=(0.15, 0.45, 0.9),
    metallic=0.15, roughness=0.35
)

studio.add_uv_sphere(
    "Sphere", location=(2, 0, 1),
    scale=(1, 1, 1), color=(0.1, 0.65, 0.85)
)

studio.add_cylinder(
    "Cylinder", location=(-2, 0, 1),
    scale=(1, 1, 1), color=(0.12, 0.16, 0.23),
    vertices=64
)
\`\`\`

- \`add_plane(name, location, scale, color)\`
- \`add_cube(name, location, scale, color, metallic, roughness)\`
- \`add_uv_sphere(name, location, scale, color)\`
- \`add_cylinder(name, location, scale, color, vertices)\`

各メソッドは作成したオブジェクト名を返します。球はスムーズシェーディング、円柱もスムーズ設定を行います。円柱の頂点数は12〜128の範囲で調整されます。

### テキスト

\`\`\`python
studio.add_text(
    "Title",
    "HELLO BLENDER",
    location=(0, -0.1, 2.5),
    size=0.5,
    color=(0.95, 0.97, 1),
    rotation=(1.5708, 0, 0),
    align="CENTER",
    extrude=0,
)
\`\`\`

\`add_text(name, body, location, size, color, rotation, align, extrude)\`

- \`body\`: 表示する文字
- \`size\`: テキストのサイズ
- \`rotation\`: XYZの回転（ラジアン）
- \`align\`: \`LEFT\`、\`CENTER\`、\`RIGHT\`
- \`extrude\`: 文字の厚み。0以上

### カメラ

\`\`\`python
studio.add_camera(
    "Camera",
    location=(0, -12, 4),
    target=(0, 0, 1),
    lens=50,
    orthographic_scale=7,
)
\`\`\`

\`add_camera(name, location, target, lens, orthographic_scale=None)\`

- \`location\`: カメラ位置
- \`target\`: 向けたい場所
- \`lens\`: 焦点距離（10〜300に制限）
- \`orthographic_scale\`: 指定すると正投影カメラになります。省略すると通常の透視投影です。
- \`set_active_camera(name)\`: 既存のCameraオブジェクトをアクティブカメラに指定します。

### ライト

\`\`\`python
studio.add_area_light(
    "KeyLight",
    location=(-4, -5, 6),
    target=(0, 0, 1),
    energy=1400,
    size=5,
    color=(1, 1, 1),
)
\`\`\`

\`add_area_light(name, location, target, energy, size, color)\`

Area Lightを指定位置に作成し、target方向へ向けます。

### アニメーション

\`\`\`python
studio.animate_location(
    "Cube",
    start_location=(0, 0, 1),
    end_location=(0, 0, 3),
    start_frame=1,
    end_frame=120,
)

studio.animate_rotation(
    "Cube",
    start_degrees=(0, 0, 0),
    end_degrees=(0, 360, 0),
    start_frame=1,
    end_frame=120,
)

studio.animate_scale(
    "Cube",
    start_scale=(1, 1, 1),
    end_scale=(1.5, 1.5, 1.5),
    start_frame=1,
    end_frame=120,
)
\`\`\`

- \`animate_location(name, start_location, end_location, start_frame=1, end_frame=None)\`
- \`animate_rotation(name, start_degrees, end_degrees, start_frame=1, end_frame=None)\`
- \`animate_scale(name, start_scale, end_scale, start_frame=1, end_frame=None)\`

\`end_frame\` を省略するとシーンの最終フレームが使われます。回転の引数は度数で指定し、内部でラジアンに変換されます。アニメーション対象のオブジェクトは先に作成しておく必要があります。

### math

使用できる定数・関数は次の通りです。

- 定数: \`math.pi\`、\`math.tau\`、\`math.e\`
- 関数: \`math.sin\`、\`math.cos\`、\`math.tan\`、\`math.radians\`、\`math.degrees\`、\`math.sqrt\`

ただし、現状はループや条件分岐が使えないため、関数を組み合わせて単純な数値計算を行う用途に限定されます。

## 音声を使う

blentopyは音声やBGMを生成しません。手持ちの音声ファイルを出力シーンのVideo Sequence Editorに配置します。

### 1. 音声ファイルをworkspaceに置く

例えば次の場所に音声を置きます。

\`\`\`text
blentopy-workspace/
└── assets/
    └── narration.wav
\`\`\`

workspaceはプレビュー・レンダリング時に指定した作業フォルダです。デフォルトはプロジェクトの実行場所にある \`blentopy-workspace\` です。

### 2. スクリプトから追加

\`\`\`python
studio.add_audio(
    "Narration",
    "assets/narration.wav",
    channel=2,
    start_seconds=0,
    volume=1,
)
\`\`\`

相対パスはworkspace内を基準にします。絶対パスを使用する場合も、workspace内のファイルでなければなりません。workspace外の音声は拒否されます。

\`add_audio(name, filepath, channel=2, start_seconds=0, volume=1)\`

- \`name\`: 音声ストリップ名
- \`filepath\`: workspace内の音声ファイル
- \`channel\`: VSEチャンネル。最低2
- \`start_seconds\`: 音声を開始する秒数
- \`volume\`: 音量0〜1

### 3. 音量を変化させる

\`\`\`python
studio.fade_audio("Narration", 0, 1, 1, 20)
\`\`\`

\`fade_audio(name, start_volume, end_volume, start_frame, end_frame)\` は指定フレーム間に音量のキーフレームを設定します。例では1フレームから20フレームにかけて音量0から1へ変化させます。

## MCPでチャットAIと接続する

MCP (Model Context Protocol) を使うと、MCP対応のAIクライアントからローカルのblentopyコマンドを呼び出せます。利用するチャットアプリ側にローカルMCPサーバー起動機能が必要です。

### 1. MCP追加依存をインストール

\`\`\`bash
source .venv/bin/activate
python -m pip install -e '.[mcp]'
\`\`\`

### 2. MCPサーバーを起動してみる

\`\`\`bash
blentopy-mcp
\`\`\`

サーバーはstdio経由で通信します。通常はこのコマンドをMCPクライアントの設定に登録して、そのクライアントから起動してもらいます。ターミナルで単独起動した場合は、終了するまで入力待ちになることがあります。

### 3. MCPクライアントの設定

MCP対応アプリの設定ファイルにサーバーを登録します。実際の仮想環境・リポジトリ・workspaceのパスに置き換えてください。

\`\`\`json
{
  "mcpServers": {
    "blentopy": {
      "command": "/ABSOLUTE/PATH/blentopy/.venv/bin/blentopy-mcp",
      "args": [],
      "env": {
        "BLENTOPY_WORKSPACE": "/ABSOLUTE/PATH/blentopy-workspace",
        "BLENTOPY_BLENDER": "/Applications/Blender.app/Contents/MacOS/Blender"
      }
    }
  }
}
\`\`\`

- \`command\`: 仮想環境にインストールされた \`blentopy-mcp\` の絶対パス
- \`BLENTOPY_WORKSPACE\`: 素材や出力を保存するworkspace
- \`BLENTOPY_BLENDER\`: Blenderの実行ファイルパス

相対パスや \`~\` は、MCPクライアントによって解釈が異なる場合があります。絶対パスを推奨します。

### 4. MCPで提供されるツール

| ツール名 | 内容 |
|---|---|
| \`blentopy_environment\` | Blenderのバージョン、実行パス、workspaceを確認 |
| \`blentopy_preview_scene\` | GUIを開いてシーンを生成し、.blendを保存。MP4はレンダリングしない |
| \`blentopy_render_scene\` | シーンを実行してMP4と.blendを出力 |
| \`blentopy_list_outputs\` | 最近の出力ファイルを一覧表示 |

### 5. AIへの指示例

MCP接続後、チャットで次のように指示できます。

- 「Blender GUIで確認したいので、まずプレビューを実行して」
- 「8秒のシーンを作って、青い球が上下に移動するアニメーションを追加して」
- 「カメラを少し引いて、全体が見えるように修正して」
- 「プレビューを実行して、生成された.blendを開いたままにして」
- 「このシーンをMP4として書き出して」

MCPクライアントがツールを呼び出すかどうかは、クライアントの設定とAIの判断に依存します。接続設定だけでAIが常に自動実行するわけではありません。

## 出力ファイル

### CLIプレビューのデフォルト

\`\`\`text
renders/
├── demo_scene.blend
└── demo_scene-<識別子>.preview.log
\`\`\`

### レンダリング

\`\`\`text
renders/
├── demo.mp4
└── demo.blend
\`\`\`

### MCP経由の出力

workspaceを指定している場合、そのworkspace内にスクリプトとレンダリング結果が保存されます。

\`\`\`text
blentopy-workspace/
├── scripts/
│   └── <シーン名>-<日時>.py
└── renders/
    ├── <シーン名>-<日時>.blend
    └── <シーン名>-<日時>.mp4
\`\`\`

GUIプレビューではMP4ファイルを作成しません。ログはプレビュー時にBlenderの標準出力・エラー出力を保存するファイルです。問題が起きた場合はログの末尾を確認してください。

## トラブルシューティング

### \`blentopy: command not found\`

仮想環境が有効になっていないか、インストールが完了していません。

\`\`\`bash
source .venv/bin/activate
python -m pip install -e . --force-reinstall
\`\`\`

### \`invalid choice: preview\`

古いCLIエントリーポイントを使用している可能性があります。

\`\`\`bash
source .venv/bin/activate
git pull --ff-only origin main
python -m pip install -e . --force-reinstall
which blentopy
blentopy --help
\`\`\`

### Blenderが見つからない

\`\`\`bash
blentopy doctor --blender "/Applications/Blender.app/Contents/MacOS/Blender"
\`\`\`

Blenderアプリが別の場所にある場合は、実際のパスを指定します。

### GUIプレビューが起動しない・途中で終了する

1. Blender実行ファイルのパスが正しいか \`doctor\` で確認。
2. Blenderが通常のGUIとして単独で起動するか確認。
3. \`--startup-timeout\` を増やして試す。
4. 出力に表示された \`.preview.log\` ファイルを開き、エラーの末尾を確認。
5. 仮想環境のblentopyが最新か確認。

\`\`\`bash
blentopy preview examples/demo_scene.py \\
  --blender "/Applications/Blender.app/Contents/MacOS/Blender" \\
  --startup-timeout 180
\`\`\`

GUIプレビューはデスクトップセッションが必要です。SSHなど画面のない環境ではGUI起動ができない場合があります。

### \`Unknown Studio API method\` / \`Unsupported Python syntax\`

スクリプトが現在許可されていないAPIやPython構文を使用しています。使用できるAPI一覧を参照して書き直してください。

現在許可されていない例:

\`\`\`python
import bpy
for i in range(10):
    ...
\`\`\`

代わりに、必要なAPI呼び出しを直接列挙します。

### カメラにオブジェクトが映らない

- Cameraのlocationを確認
- targetがオブジェクト方向を向いているか確認
- オブジェクトのlocation/scaleを確認
- カメラのlensまたはorthographic_scaleを調整
- GUIプレビューでCamera Viewに切り替えて確認

### レンダリングに時間がかかる

- オブジェクト数を減らす
- 解像度を下げる
- 動画の秒数を短くする
- FPSを下げる
- まずGUIプレビューで構図を確認してからレンダリングする

## テスト

Blenderがなくても、Pythonのユニットテストと構文チェックを実行できます。

\`\`\`bash
source .venv/bin/activate
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests examples
\`\`\`

実際のGUIプレビュー・MP4レンダリングには、インストールされたBlenderとGUI環境が必要です。

## 安全性について

blentopyのシーンスクリプトは通常のPythonより狭い構文に制限されています。現在許可されているもの:

- ドキュメント化された \`studio.*\` APIの呼び出し
- 数値、文字列、真偽値などのリテラル
- 単純な変数代入
- List、Tuple、Dict
- 数値の符号
- 一部の \`math.*\` 定数と関数

拒否されるもの:

- \`import\`
- \`bpy\` への直接アクセス
- ファイルシステム操作
- Shellコマンド
- ネットワークアクセス
- ループや条件分岐
- 関数・クラス定義
- 属性チェーン

**この構文制限はOSレベルのサンドボックスではありません。** Blenderや依存ソフトウェアはローカルユーザー権限で実行されます。未知の.blendファイルや素材を安全とみなさないでください。

## 現在の制限

- 基本プリミティブ中心の3D制作
- AIモデル自体は同梱しない
- TTS・音楽・画像生成などは別途必要
- 高度なモデリング、リギング、キャラクター制作は未対応
- AIによる自動リトライ・エラー修正機構は未実装
- Blenderバージョン間のVSE API差異は検証が必要
- GUIプレビューと実際のレンダリングは使用するMac上で確認が必要

## License

MIT. See [LICENSE](LICENSE).
