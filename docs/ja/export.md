# 📦 ゲームのエクスポート

SpriteStudio Player for Ren'Py を組み込んだゲームを各プラットフォーム向けにエクスポートする手順です。ここでは **SSPlayer 固有** の点だけを扱い、汎用的なビルド手順は Ren'Py 公式ドキュメントへのリンクに委ねます。

> このページは、標準の Ren'Py ランチャーで**自分のゲーム**をエクスポートする**ゲーム制作者**向けです。本リポジトリ内で作業する場合（デモやネイティブライブラリのビルド）は、以下の各エクスポートを自動化する開発者向けヘルパースクリプトを [ビルドガイド](build.md) にまとめています。

全プラットフォーム共通: ネイティブ「頭脳 (Brain)」ライブラリは、ビルド対象のプラットフォーム向けに `game/spritestudio/libs/<platform-arch>/` へ置かれている必要があります（Ren'Py がパッケージへ同梱し、`ssruntime.py` が実行時に解決します）。**アセット**の同梱はゲーム側の責務です（アセットはライブラリではなくゲームのコンテンツだからです）。`.ssab` パック（`.ssqb` シーケンスパックがあればそれも。また
SS Audio タイムラインイベントを使う場合は非圧縮の `.wav` または `.mp3`）を、ご自身の
`options.rpy` で classify してください。特に Web エクスポートは、明示分類しないと未知の拡張子を落とします。`build.classify('**.ssab', 'all')` と `'**.ssqb'`（オーディオを使うなら `'**.wav'` / `'**.mp3'` も）を追加してください（本デモは `game/options.rpy` で対応済み）。

## デスクトップ向けエクスポート (Windows / macOS / Linux)

Ren'Py 標準の [Build Distributions](https://www.renpy.org/doc/html/build.html) をそのまま使います。SSPlayer 固有の後処理はありません。

> **⚠️ 各プラットフォームごとに専用のネイティブライブラリが必要です。**
> `game/spritestudio/libs/` 以下に `macos/libssruntime.framework`、
> `windows/x86_64/ssruntime.dll`、`linux/x86_64/libssruntime.so`。Ren'Py が同梱し、
> `ssruntime.py` が実行時に解決します。ビルド対象プラットフォームのライブラリが無くてもパッケージのビルドは通りますが、SSPlayer がロード時に例外を送出します。

`build.name` はご自身の `options.rpy` で必ず設定してください（未設定だと `.app` が起動しません。デモは設定済み）。配布時は Ren'Py のドキュメントに従いコード署名・公証を行ってください（未署名 `.dylib`
は Gatekeeper にブロックされます）。

**任意 — アセットを `.rpa` にまとめる:** アセットをアーカイブへ振り分けるため、
`**.ssab` / オーディオの classify ルールより**前**にアーカイブを登録します（build.classify は first-match-wins）。デモの `options.rpy` に `ss_pack_assets_into_rpa`
トグルがあるので参考にできます。

## Android 向けエクスポート

Ren'Py 標準の [RAPT](https://www.renpy.org/doc/html/android.html) を使います。
launcher GUI（→ Android）から **Install SDK**、**Configure**（パッケージ名を設定）、
**Generate Keys** を一度だけ実施してください（Ren'Py のドキュメント参照）。

> **⚠️ Brain は APK の `lib/<abi>/`（jniLibs）にネイティブライブラリとして入れる必要があります。** Android のリンカは、インストーラが読み取り専用の `nativeLibraryDir` に展開したネイティブライブラリしか `dlopen()` しません（API 29 以降の W^X 制約）。ゲームアセット内や書き込み可能領域の `.so` はロードされません。`ssruntime.py` は実行時に
> soname（`libssruntime.so`）でロードします。**NDK の ABI 名**で ABI ごとに 1 つ配置:
> `libs/android/arm64-v8a/libssruntime.so`（大半の 64bit 端末）、`armeabi-v7a/`
> （旧端末）、`x86_64/`（エミュレータ）。
>
> RAPT にはゲーム側からネイティブコードを注入するフックが無いため、各 `.so` を一度だけ手動で Ren'Py SDK の RAPT jniLibs にコピーしてください（iOS と同種の一度きりの手作業です）:
>
> ```
> <renpy-sdk>/rapt/prototype/renpyandroid/src/main/jniLibs/<abi>/libssruntime.so
> ```

`.aab`（Play アップロード用）でビルドすることも、`.apk` を得ることもできます。

## iOS 向けエクスポート

Ren'Py 標準の [renios](https://www.renpy.org/doc/html/ios.html) を使います。**Xcode
プロジェクト**を生成し、`.ipa` は Xcode でビルドします。**macOS + Xcode が必須**です。

> **⚠️ Brain は *動的* な `libssruntime.xcframework` で、app ターゲットに「Embed & Sign」で追加します。** `ssruntime.py` は ctypes の `CDLL(None)` で読み込むため、ロード済みイメージである必要があります。Embed & Sign はリンク（dyld が起動時にロード）とバンドルへの署名付きコピーを行います（renios が `MetalANGLE.xcframework` に対して行うのと同じ扱い）。**静的** xcframework はリンクはできますが dead-strip されて
> `CDLL(None)` が実行時に失敗するので、動的版を使います。スライスは（素の
> dylib ではなく）`.framework` バンドルなので、Embed & Sign が App Store のバンドル構造検証を通ります。

1. **Xcode プロジェクトを生成** — Ren'Py のランチャー（→ iOS → Xcode プロジェクトを作成）、または同等の `<renpy> launcher ios_create . <xcode-project-dir>` CLI コマンドで生成します。
2. **Brain を一度だけ埋め込む** — Xcode で app ターゲット → **General** → **Frameworks,
   Libraries, and Embedded Content** → **+** → *Add Files…* →
   `game/spritestudio/libs/ios/libssruntime.xcframework` → **Embed & Sign**。Ren'Py にはサードパーティのネイティブコードを自動リンクする仕組みがないため、この 1 手だけは手動です（以降の `ios_populate` 再実行でも維持されます）。
3. **ビルド** — **シミュレータ**を選んで **Run**（署名不要）、または signing team を設定し
   **Product > Archive** で実機 `.ipa` を生成します。

## Web (ブラウザ) 向けエクスポート

Ren'Py 標準の [Web エクスポート](https://www.renpy.org/doc/html/web.html) をそのまま使います。SSPlayer 固有の後処理はありません。Brain の WebAssembly 版（`game/spritestudio/libs/web/`）はフォルダの他の部分と一緒に `game.zip` に入り、SSPlayer がゲーム起動時にそこから読み込むため、ランチャーが出力したものがそのまま動きます。

**動作確認:** `file://` ではなく HTTP で配信します（Ren'Py 付属の web サーバで足ります）。再エクスポート後は、キャッシュされた **Service Worker の登録解除 / サイトデータのクリア**を行わないと、ブラウザが古いビルドを表示します。
