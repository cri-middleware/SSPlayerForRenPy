# ゲームのエクスポート

SpriteStudio Player for Ren'Py を組み込んだゲームを各プラットフォーム向けに
エクスポートする手順です。ここでは **SSPlayer 固有** の点だけを扱い、汎用的な
ビルド手順は Ren'Py 公式ドキュメントへのリンクに委ねます。

全プラットフォーム共通: ネイティブ「頭脳 (Brain)」ライブラリは
`game/spritestudio/libs/<platform-arch>/` に置かれ、`spritestudio.rpy` が
`build.classify` で `**.ssab` パック（および同じ場所のテクスチャ）をビルドへ自動同梱
します（`options.rpy` の編集不要）。SS Audio タイムラインイベント用の非圧縮**オーディオ**
(`.wav` / `.mp3`) はゲーム側の責務です。ご自身の `options.rpy` に
`build.classify('**.wav', 'all')` / `'**.mp3'` を追加してください（本デモは
`game/options.rpy` で対応済み）。

## デスクトップ向けエクスポート (Windows / macOS / Linux)

Ren'Py 標準の [Build Distributions](https://www.renpy.org/doc/html/build.html) を
そのまま使います。SSPlayer 固有の後処理はありません。

> **⚠️ 各プラットフォームごとに専用のネイティブライブラリが必要です。**
> `game/spritestudio/libs/` 以下に `macos/libssruntime.dylib`、
> `windows/x86_64/ssruntime.dll`、`linux/x86_64/libssruntime.so`。Ren'Py が同梱し、
> `ssruntime.py` が実行時に解決します。**本リポジトリには macOS 用のみ同梱**。他は
> `scripts/download-sdk.*`（ビルド済み）または `scripts/build-runtime.*`（ソース）で
> 用意してください。無いままビルドすると起動は通っても SSPlayer がロード時に落ちます。

ヘルパー（ホスト OS 用パッケージをビルドし、そのまま実行できる形に展開）:

```bash
scripts/deploy-desktop.sh [dest_dir]      # Windows: scripts\deploy-desktop.ps1
```

そのまま動くビルドを得るには `.sh` を **Mac 上で** 実行してください。`build.name` の
設定は必須です（未設定だと `.app` が起動しません。デモは設定済み）。配布時は Ren'Py の
ドキュメントに従いコード署名・公証を行ってください（未署名 `.dylib` は Gatekeeper に
ブロックされます）。

**任意 — アセットを `.rpa` にまとめる:** ライブラリの `**.ssab` ルール（init −10）より
**前**にアーカイブを登録します。デモの `options.rpy` に `ss_pack_assets_into_rpa`
トグルがあります。

## Android 向けエクスポート

Ren'Py 標準の [RAPT](https://www.renpy.org/doc/html/android.html) を使います。
SSPlayer 固有の後処理はありません。

> **⚠️ ABI ごとに `.so` が 1 つ必要。配置は SDK の arch トークンで、Android の ABI 名
> ではありません。** これは APK の `lib/<abi>/` ではなく `game/` 内の ctypes ロード
> パスだからです: `libs/android/arm64/libssruntime.so`（大半の 64bit 端末）、`arm32/`
> （旧端末）、`x86_64/`（エミュレータ）。取得は
> `scripts/build-runtime.* platform=android build=release`（NDK 必要）または
> `scripts/download-sdk.*`（ビルド済み）。

一度だけ: `scripts/fetch-renpy-android.*` で RAPT を取得し、launcher GUI（→ Android）
から **Install SDK** と **Generate Keys** を実施（対話式。Ren'Py のドキュメント参照）。

```bash
scripts/deploy-android.sh [dest_dir] [--bundle] [--install] [--launch]
# Windows: scripts\deploy-android.ps1 [dest_dir] [-Bundle] [-Install] [-Launch]
```

`--bundle` は `.aab`（Play アップロード用）、`--install` / `--launch` は `adb` で端末へ
転送・起動します。

## iOS 向けエクスポート

Ren'Py 標準の [renios](https://www.renpy.org/doc/html/ios.html) を使います。**Xcode
プロジェクト**を生成し、`.ipa` は Xcode でビルドします。**macOS + Xcode が必須**です。

> **⚠️ Brain は *動的* な `libssruntime.xcframework` で、app ターゲットに
> 「Embed & Sign」で追加します。** `ssruntime.py` は ctypes の `CDLL(None)` で読み込む
> ため、ロード済みイメージである必要があります。Embed & Sign はリンク（dyld が起動時に
> ロード）とバンドルへの署名付きコピーを行います（renios が `MetalANGLE.xcframework` に
> 対して行うのと同じ扱い）。`game/spritestudio/libs/ios/` に
> `scripts/build-runtime.sh platform=ios build=release` または
> `scripts/download-sdk.sh` で用意してください。**静的** xcframework はリンクはできますが
> dead-strip されて `CDLL(None)` が実行時に失敗するので、動的版を使います。

一度だけ: `scripts/fetch-renpy-ios.sh`（renios。macOS 専用のため `.ps1` はありません）。

1. **Xcode プロジェクトを生成** — `scripts/deploy-ios.sh [dest_dir] [--recreate]
   [--open]`（SDK/renios の自動取得、create/populate の判定も実施）、または標準ランチャー:
   `renpy-sdk/renpy.sh renpy-sdk/launcher ios_create . <xcode-project-dir>`。
2. **Brain を一度だけ埋め込む** — Xcode で app ターゲット → **General** → **Frameworks,
   Libraries, and Embedded Content** → **+** → *Add Files…* →
   `game/spritestudio/libs/ios/libssruntime.xcframework`（`deploy-ios` は
   `<project>/Frameworks/` にもコピーを配置します）→ **Embed & Sign**。Ren'Py には
   サードパーティのネイティブコードを自動リンクする仕組みがないため、この 1 手だけは手動
   です（以降の `ios_populate` 再実行でも維持されます）。
3. **ビルド** — **シミュレータ**を選んで **Run**（署名不要）、または signing team を設定し
   **Product > Archive** で実機 `.ipa` を生成します。

## Web (ブラウザ) 向けエクスポート

Ren'Py 標準の [Web エクスポート](https://www.renpy.org/doc/html/web.html)
（Pyodide / WASM）を使います。SSPlayer は非 ctypes な JS バインディング
(`ssruntime_web.py`) に自動的に切り替わるため、コード変更は不要です。

> **⚠️ そのままの Web エクスポートは動きません。** レンダラは別の WASM モジュール
> (`ssruntime.js` / `ssruntime_bg.wasm`) を必要としますが、Ren'Py のエクスポータは
> これを認識しません。そのため**エクスポートのたびに下記 2 つの後処理が必須**です。Ren'Py
> は毎回 `index.html` を再生成し `game.zip` を再パックするので、**エクスポートごとに
> 再適用**してください。行わないと console に
> `Cannot read properties of undefined (reading 'SSRuntimeContext')` が出ます。

ヘルパー（エクスポートと 2 つの後処理を**まとめて**実行。冪等）:

```bash
scripts/deploy-web.sh [dest_dir]      # 既定 web_out。Windows: scripts\deploy-web.ps1
```

`web_build` エクスポート後に手作業で行う場合:

1. **`index.html` を編集** — ゲーム起動前に WASM バインディングを読み込むため、
   `<script src="renpy-pre.js">` タグの**直前**に以下を追加:
   ```html
   <script type="module">
     import init, * as ss from './game/spritestudio/libs/web/ssruntime.js';
     window.ssruntime = ss;
     window.ssruntime_wasm = await init('./game/spritestudio/libs/web/ssruntime_bg.wasm');
   </script>
   ```
2. **WASM アセットを実ファイルとして配置** — `game/spritestudio/libs/web/` の
   `ssruntime.js` と `ssruntime_bg.wasm` を、出力側の同じパス（例:
   `web_out/game/spritestudio/libs/web/`）へコピーします。エクスポートは `game/` を
   `game.zip` に固めるため、ブラウザはその中から `import` できません。手順1のパスと
   一致させてください。

**動作確認:** `file://` ではなく HTTP で、正しい MIME（`.js` →
`application/javascript`、`.wasm` → `application/wasm`）で配信します（Ren'Py 付属の
web サーバはこれを満たします）。再エクスポート後は、キャッシュされた **Service Worker の
登録解除 / サイトデータのクリア**を行わないと、ブラウザが古いビルドを表示します。
