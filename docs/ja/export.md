# ゲームのエクスポート

SpriteStudio Player for Ren'Py を組み込んだゲームを各プラットフォーム向けにエクスポートする手順です。

## Web (ブラウザ) 向けエクスポート

Ren'Py の標準 Web エクスポート機能（Pyodide / WASM）を利用して、ブラウザ上で動作するゲームを出力できます。
本ライブラリは内部で `ssruntime_web.py` による非 ctypes な JS バインディングを自動的に使用するため、Python コードの変更は不要です。

> **⚠️ Ren'Py の Web エクスポートは、そのままでは動きません。**
> Web レンダラは別の WASM モジュール（`ssruntime.js` / `ssruntime_bg.wasm`）を読み込みます。
> Ren'Py のエクスポータはこれを認識しないため、**エクスポートのたびに 2 つの後処理が必須**です
> ——`index.html` の編集（手順3）と、WASM アセットの実ファイル配置（手順4）。
> これを行わないと、ブラウザの console に
> `Cannot read properties of undefined (reading 'SSRuntimeContext')`
> （＝ `window.ssruntime` が未ロード）が出て、何も描画されません。
> エクスポータは**実行のたびに `index.html` を作り直し `game.zip` を再パッケージ**するため、
> この 2 手順は**毎回のエクスポート後に再適用**する必要があります。

### 自動ビルド（推奨）

エクスポートと 2 つの後処理（手順3・4）をまとめて行うヘルパースクリプトを用意しています。冪等なので何度実行しても安全です:

```bash
scripts/deploy-web.sh [dest_dir]      # 省略時の出力先: web_out
# Windows:
scripts\deploy-web.ps1 [dest_dir]
```

その後、出力先を HTTP で配信してください（後述の[動作確認](#動作確認)参照）。手作業で行いたい場合は、以下の手順に従ってください。

### 手動の手順

1. **Web エクスポート環境のセットアップ**
   Ren'Py で Web エクスポートを行うためのパッケージをインストールします。
   （Ren'Py ランチャーからダウンロードするか、プロジェクトの `scripts/fetch-renpy-web.sh` を使用してください）

2. **エクスポートの実行**
   Ren'Py ランチャーの「Web (Beta)」メニューから「Build Web Application」を選択し、エクスポートを実行します。
   （CLI の場合は `./renpy.sh launcher web_build <project_dir> --dest <out>` を実行します）

3. **⚠️ 必須: `index.html` への JS/WASM ロード用スクリプトの追加**
   生成されたフォルダ内の `index.html` を開き、Ren'Py の起動処理の**前**
   （`<script src="renpy-pre.js"></script>` の直前の行）に以下のコードを追記してください。
   これにより、SSPlayer のレンダリングを担う WASM バインディングがゲーム起動前に読み込まれます。
   **この追記は必須で、再エクスポートのたびに消えます——毎回追記し直してください。**

   ```html
   <script type="module">
     import init, * as ss from './game/spritestudio/libs/web/ssruntime.js';
     window.ssruntime = ss;
     window.ssruntime_wasm = await init('./game/spritestudio/libs/web/ssruntime_bg.wasm');
   </script>
   ```

4. **⚠️ 必須: Web アセット (`ssruntime.js` / `ssruntime_bg.wasm`) の配置**
   エクスポート時に `game` ディレクトリは `game.zip` に圧縮されるため、`index.html` 内の
   ブラウザネイティブの ES モジュール `import` からは `game.zip` 内のランタイムを読み込めません。
   そのため、`game/spritestudio/libs/web/` の `ssruntime.js` と `ssruntime_bg.wasm` を、
   出力先フォルダの同じパス（`web_out/game/spritestudio/libs/web/` 等）に**実ファイルとしてコピー**してください。
   手順3の import パスは、この配置先と**完全に一致**させる必要があります。

### 動作確認

* **`file://` ではなく HTTP で配信してください。** ES モジュールと WASM はファイルシステムからは読み込めません。
  静的サーバなら何でも構いませんが、MIME を正しく返す必要があります:
  `.js` → `application/javascript`、`.wasm` → `application/wasm`。
  Ren'Py 純正の web サーバ（`renpy.sh launcher web_build <dir> --launch`、または
  ランチャーの「Web (Beta)」ページ）はこれを満たします。
* **再テスト時は Service Worker をクリアしてください。** Ren'Py の Web ビルドは `game.zip` を
  キャッシュする service worker を登録します。再エクスポート後、ブラウザが**古い**ビルドを
  返すことがあります。DevTools → Application で service worker を **Unregister** し、
  **Clear site data** してからハードリロード（またはシークレットウィンドウ）してください。

### 仕様に関する注意点

* **`.ssab` とオーディオ (`.wav` / `.mp3`) のパッケージング**
  Ren'Py は Web エクスポート時に、デフォルトでは `.png` や `.ogg` など限られた拡張子のファイルしか出力用アーカイブ (`game.zip`) に含めません。
  本ライブラリは `spritestudio.rpy` 内で `build.classify('**.ssab', 'all')` を定義しているため、SpriteStudio パックは常に含まれます（この分は `options.rpy` の変更不要）。
  **非圧縮オーディオはライブラリではなくゲーム側の責務です。** SpriteStudio の **Audio** タイムラインイベントで `.wav` / `.mp3` を再生する場合は、ご自身の `options.rpy` に `build.classify('**.wav', 'all')` と `build.classify('**.mp3', 'all')` を追加してください（本デモも `game/options.rpy` でそうしています）。追加しないと Web ビルドで除外されます。

## デスクトップ向けエクスポート (Windows / macOS / Linux)

デスクトップ向けエクスポートは、Ren'Py 標準の **Build Distributions** 機能を
そのまま使います。Web 向けと違い、**エクスポート後の手作業は不要**です。ネイティブ
の「頭脳 (Brain)」ライブラリ (`libssruntime.dylib` / `ssruntime.dll` /
`libssruntime.so`) は `game/` の内側に置かれているため、Ren'Py が自動的にアプリへ
同梱し、`ssruntime.py` が実行時に `game/spritestudio/libs/<platform-arch>/` から
解決します（開発時とまったく同じレイアウトです）。

アセットも対応済みです。`spritestudio.rpy` が `build.classify('**.ssab', 'all')`
を宣言しているため、`.ssab` パック（および同じ場所のテクスチャ）は `options.rpy`
を触らなくても正しくパッケージングされます。非圧縮**オーディオ** (`.wav` / `.mp3`)
はゲーム側の責務です。SS Audio イベントを使う場合はご自身の `options.rpy` で
classify してください（本デモは `game/options.rpy` で対応済みです）。

> **⚠️ ターゲットの各プラットフォームごとに、対応するネイティブライブラリが必要です。**
> Brain はコンパイル済みバイナリなので、パッケージが *実行* できるのは、そのライブラリ
> が `game/spritestudio/libs/` 以下に存在するプラットフォームだけです。
>
> | パッケージ | 必要なもの | パス |
> |---|---|---|
> | `mac`   | `libssruntime.dylib`（ユニバーサル） | `libs/macos/` |
> | `win`   | `ssruntime.dll`      | `libs/windows/x86_64/` |
> | `linux` | `libssruntime.so`    | `libs/linux/x86_64/` |
>
> **本リポジトリには現在 macOS 用ライブラリのみが同梱されています。** 対応バイナリ
> が無いまま `win`/`linux` パッケージをビルドすると、ビルド自体は通りますが、SSPlayer
> がロード時に落ちます（解決先の `.dll`/`.so` が存在しないため）。他プラットフォーム
> のライブラリは `scripts/download-sdk.*`（ビルド済みを取得）または
> `scripts/build-runtime.*`（ソースからビルド）で先に用意してから、再度エクスポート
> してください。

### 自動ビルド（推奨）

ヘルパースクリプトを使うと、**ホスト OS** に応じたパッケージをビルドし、そのまま
実行できる形に展開します。冪等なので何度でも安全に再実行できます:

```bash
scripts/deploy-desktop.sh [dest_dir]     # 既定の出力先: dist
#   macOS -> dist/<name>.app         （ダブルクリック / `open`）
#   Linux -> dist/<name>-linux-x86_64/ （中の <name>.sh を実行）
# Windows (.exe):
scripts\deploy-desktop.ps1 [dest_dir]    # -> dist\<name>-win\<name>.exe
```

ホストプラットフォーム用のネイティブライブラリが無い場合、スクリプトはヒントを
表示して終了します。本リポジトリには macOS 用ライブラリのみ同梱されているため、
そのまま動くビルドを得るには `.sh` を **Mac 上で** 実行してください。

### 手動ビルド

プロジェクトルートから（下記は `mac` パッケージ。各ホストでは `--package` を
`win` / `linux` に置き換え）:

```bash
renpy-sdk/renpy.sh renpy-sdk/launcher distribute . \
  --package mac --format app-zip --no-update --destination dist
```

Ren'Py Launcher の GUI からも可能です。プロジェクトを選択 → **Build Distributions**
→ **Macintosh** にチェック → **Build**。

出力は `dist/<name>-mac.zip` で、中身は自己完結した `.app` です。ネイティブ
ライブラリは
`<name>.app/Contents/Resources/autorun/game/spritestudio/libs/macos/libssruntime.dylib`
に配置され、追加の配線なしにアプリがロードします。

> **⚠️ `build.name` を設定しないとアプリが起動しません。** `build.name` が未設定
> だと、Ren'Py は `CFBundleExecutable`（および `Contents/MacOS/` の起動バイナリ）を
> 空のままにするため、`.app` が起動できない中途半端な `-mac.zip` になります。本デモの
> `options.rpy` は `define build.name = "SSPlayerForRenPy"` を設定済みです。ご自身の
> ゲームでも必ず設定してください（例: `define build.name = "MyGame"` → `MyGame-1.0`）。

### macOS 配布時の注意

ローカルでビルドした `.app` は自分の Mac ではそのまま動きます。しかし他者へ **配布**
する（ユーザーがダウンロードする）場合、macOS Gatekeeper が未署名の `.dylib` を
隔離 (quarantine) し、アプリの起動がブロックされます。リリース時にはアプリを
**コード署名 (code-sign) と公証 (notarize)** する必要があります（Ren'Py Launcher は
署名済みアプリを `--macapp` で渡す方式に対応しています。Ren'Py の
"Signing a Mac App" のドキュメントを参照）。

### パッケージングの詳細

`spritestudio.rpy` が `build.classify` でデスクトップビルドを自動的に軽量化するため、
基本的に `options.rpy` を触る必要はありません:

* **同梱されるネイティブライブラリはターゲットプラットフォームのものだけ。** 各
  `libs/<platform>/` サブツリーに Ren'Py のプラットフォームタグを付与しています
  （`macos/`→`mac`、`windows/x86_64/`→`windows`、`linux/x86_64/`→`linux` …）。
  そのため `mac` ビルドには `.dylib` のみが入り、Windows の `.dll`・Linux の `.so`・
  Web の `.wasm` は含まれません。
* **コンバータ (`libssconverter.*`) は一切同梱されません。** これはインポート/開発時
  ツール（`auto_importer`、`config.developer` でガード)で、配布されたゲームが実行時に
  ロードすることはありません。
* 古い `__pycache__` も除外します。（本リポジトリ自身の開発用ファイル — `renpy-sdk/`・
  `SpriteStudio-SDK/`・`scripts/`・`docs/`・`dist/`・ルート直下の `*.md` / `*.txt` など —
  は、ライブラリではなく**デモの** `game/options.rpy` で除外しています。そのため
  `game/spritestudio/` を取り込んだ下流ゲームには一切影響しません。）

**任意 — アセットを `.rpa` アーカイブにまとめる。** Ren'Py は既定でゲームファイルを
ルーズに配置します。1 つのアーカイブにまとめたい場合は、アーカイブを宣言してアセットを
classify で振り分けます。SSPlayer は `renpy.loader.load` 経由でパックを読み込むため、
ルーズでもアーカイブ済みでも同じように動作します。`build.classify` は登録順の
**先勝ち (first-match-wins)** なので、ライブラリの `**.ssab`→`all`（init −10）より
**前**に登録します（= より早い init 優先度）:

```renpy
init -20 python:
    build.archive("ssdata", "all")
    build.classify("game/ss_assets/**", "ssdata")   # -> game/ssdata.rpa
```

デモの `options.rpy` は既にこれを `ss_pack_assets_into_rpa` トグル付きで実装済みです
（`False` にするとアセットをルーズで配布します）。

## Android 向けエクスポート

Android 向けエクスポートは Ren'Py 標準の **RAPT**（Ren'Py Android Packaging Tool）
を使います。デスクトップ向けと同様、Web と違って**エクスポート後の手作業は不要**です。
`game/spritestudio/libs/android/<arch>/` のネイティブ「頭脳 (Brain)」`.so` がアプリに
同梱され、`ssruntime.py` が実行時にロードします。

> **⚠️ Android は ABI ごとに専用のネイティブライブラリが必要です。**
> Brain はコンパイル済みバイナリなので、`.so` が存在する ABI でしか動作しません。
> 配置先は SDK の **arch トークン**（`arm64` / `arm32` / `x86_64`）であり、Android の
> ABI 名（`arm64-v8a` / `armeabi-v7a`）**ではありません** — これは APK の `lib/<abi>/`
> ではなく `game/` 内の ctypes ロードパスだからです:
>
> | デバイス | パス |
> |---|---|
> | 64bit スマホ/タブレット（大半） | `libs/android/arm64/libssruntime.so` |
> | 旧 32bit スマホ                | `libs/android/arm32/libssruntime.so` |
> | x86_64 エミュレータ            | `libs/android/x86_64/libssruntime.so` |
>
> 取得は `scripts/build-runtime.* platform=android build=release`（ソースからビルド、
> Android NDK が必要）または `scripts/download-sdk.*`（ビルド済み）で行います。

### 一度だけの準備

1. **RAPT を取得** — Android ターゲットに必要な追加ダウンロード（Web における
   `fetch-renpy-web.*` に相当）:
   ```bash
   scripts/fetch-renpy-android.sh          # Windows: scripts\fetch-renpy-android.ps1
   ```
2. **Android SDK のインストールと署名鍵の生成** — どちらも対話式なので、launcher の
   GUI から一度だけ実施します:
   ```bash
   renpy-sdk/renpy.sh renpy-sdk/launcher   # -> Android
   ```
   * **Install SDK** — Android SDK / NDK / JDK を `renpy-sdk/rapt/Sdk/` にダウンロード。
   * **Generate Keys** — 署名用の `android.keystore`（および `bundle.keystore`）を
     プロジェクトルートに生成。

### 自動ビルド（推奨）

上記の前提を確認してエクスポートを実行するヘルパスクリプトを使います。Ren'Py SDK と
RAPT が未取得なら自動で取得します:

```bash
scripts/deploy-android.sh [dest_dir] [--bundle] [--install] [--launch]   # 既定 dest: dist
# Windows:
scripts\deploy-android.ps1 [dest_dir] [-Bundle] [-Install] [-Launch]
```

* `--bundle` は Universal `.apk` の代わりに `.aab` App Bundle（Play アップロード用）を
  ビルドします。`--install` / `--launch` は接続中の端末へ `adb` で転送・起動します。

### 手動ビルド

```bash
renpy-sdk/renpy.sh renpy-sdk/launcher android_build . --dest dist
```

または launcher GUI からプロジェクトを選択 → **Android** → **Build**。デスクトップ
同様 `build.name` の設定が必須です（本デモの `options.rpy` は設定済み）。

## iOS 向けエクスポート

*(後日追加予定 — iOS 用ネイティブライブラリ (`libssruntime.xcframework`) をビルドして
`game/spritestudio/libs/ios/` へ配置する必要があります。`scripts/build-runtime.*
platform=ios` で生成できます。)*
