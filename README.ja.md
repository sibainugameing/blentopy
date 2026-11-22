# blentopy(日本語ガイド)

**Blenderのシーンを Python で作成・確認・アニメーション・レンダリングするための、AIネイティブなフレームワークです。**

blentopy自体はAIモデルではなく、AI APIも呼び出しません。MCP対応のチャットクライアント(または人が書いたPythonスクリプト)がシーンのコードを用意し、blentopyがそれを検証し、ローカルのBlenderを起動してシーンを構築します。編集可能な `.blend` とMP4動画を出力できます。APIキーは不要です。

> 初期段階のプロトタイプです。GUIプレビューと動画レンダリングは、お使いのOSとBlenderのバージョンで事前に動作確認してください。

詳細な仕様・全機能は [README.md](README.md)(英語)を参照してください。

## 必要なもの

- Python 3.11 以上
- Blender 4.2 以上
- GUIプレビューにはデスクトップ環境が必要です
- MCPサーバーを使う場合のみ MCP Python SDK 2.x

## インストール

~~~bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install -e '.[mcp]'   # MCPを使う場合のみ
~~~

## はじめかた

~~~bash
blentopy doctor                 # Blenderが見つかるか確認
blentopy new my_scene.py         # minimalテンプレートを生成
blentopy new spinner.py --template spinner  # アニメーション付きテンプレート
blentopy new --list              # テンプレート一覧
blentopy demo                   # 内蔵デモをMP4にレンダリング
blentopy check my_scene.py      # Blenderを起動せず構文だけ高速チェック
blentopy check my_scene.py --json  # AIやエディタ向けJSON出力
blentopy doctor --json          # 環境情報をJSON出力
blentopy preview my_scene.py    # BlenderのGUIで開いて確認
blentopy render my_scene.py --output renders/out.mp4
blentopy gui                    # 簡易デスクトップGUI
~~~

Blenderが自動検出されない場合は、`--blender` で実行ファイルを指定するか、環境変数 `BLENTOPY_BLENDER` を設定してください。

~~~bash
# macOS
export BLENTOPY_BLENDER="/Applications/Blender.app/Contents/MacOS/Blender"
~~~

~~~powershell
# Windows PowerShell
$env:BLENTOPY_BLENDER = "C:\Program Files\Blender Foundation\Blender 4.2\blender.exe"
~~~

## スターターシーン

空のファイルから始めず、動作に必要なカメラ・ライトを含むシーンを生成できます。

~~~bash
blentopy new my_scene.py
blentopy new spinner.py --template spinner
blentopy new --list
~~~

- `minimal`: ベベル付きキューブ、床、カメラ、キーライト。
- `spinner`: 回転するメインオブジェクトと、円軌道上を回るビーズのアニメーション。

既存ファイルは通常上書きされません。明示的に上書きする場合だけ `--force` を付けてください。

~~~bash
blentopy new my_scene.py --force
blentopy check my_scene.py --json
blentopy doctor --json
~~~

`check --json` は構文検査の結果をJSONで出力します。構文検査はBlender内での実行成功を保証するものではありません。

## AIチャットと組み合わせる流れ

1. GUIの **Copy AI instructions** で作成ルールをコピーし、AIチャットに貼り付けます。
2. AIにblentopyのシーンスクリプトを作成・修正してもらいます。
3. 返ってきたコードをGUIのエディタに貼り付けるか、`.py` として保存します。
4. `blentopy check` で構文を確認し、**Preview in Blender** または **Render MP4** を実行します。
5. エラーはCLIと同じ形式で表示されるので、そのままAIに貼って修正を依頼できます。

## 主なオプション

| オプション | 既定値 | 説明 |
|---|---|---|
| `--width` / `--height` | 1080 / 1920 | 解像度(1以上の整数) |
| `--fps` | 30 | フレームレート |
| `--duration` | 8 | 長さ(秒) |
| `--timeout` | 3600 | タイムアウト(秒) |
| `--workspace` | `blentopy-workspace` | 音声・HDRなどの素材置き場 |

## テスト

~~~bash
python -m pip install -e '.[test]'
python -m pytest -q
~~~

## ライセンス

[LICENSE](LICENSE) を参照してください。
