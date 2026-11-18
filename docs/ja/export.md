# 📦 ゲームのエクスポート

SpriteStudio Player for Ren'Py を組み込んだゲームを各プラットフォーム向けにエクスポートする手順です。ここではこのプレイヤーで加わる手順だけを扱い、汎用的なビルド手順は Ren'Py 公式ドキュメントへのリンクに委ねます。

> このページは、標準の Ren'Py ランチャーで**自分のゲーム**をエクスポートする**ゲーム制作者**向けです。本リポジトリ内で作業する場合（デモやネイティブライブラリのビルド）は、以下の各エクスポートを自動化する開発者向けヘルパースクリプトを [ビルドガイド](development/build.md) にまとめています。

全プラットフォーム共通: `game/spritestudio/libs/` には全プラットフォーム向けのネイティブライブラリが入っています。デスクトップと Web では、Ren'Py が必要なものをゲームに同梱します。Android と iOS では、後述のとおり一度だけ手で配置します。**アセット**（`.ssab`、`.ssqb`、テクスチャ、サウンド）は、`game/` の他のファイルと同じようにゲームに同梱されます。`SpriteStudio_Source/` の下のプロジェクトは同梱されません。

## デスクトップ向けエクスポート (Windows / macOS / Linux)

Ren'Py 標準の [配布物のビルド](https://www.renpy.org/doc/html/build.html) をそのまま使います。このプレイヤーで加わる手順はありません。配布時は Ren'Py のドキュメントに従いコード署名・公証を行ってください（未署名の `.dylib` は Gatekeeper にブロックされます）。

**任意 — アセットを `.rpa` にまとめる:** `build.classify` は最初に当たったルールを使うので、同じファイルに当たるご自身の classify ルールより**前**にアーカイブを登録します。

```renpy
init python:
    build.archive("ssdata", "all")
    build.classify("game/ss_assets/**", "ssdata")
```

## Android 向けエクスポート

Ren'Py 標準の [RAPT](https://www.renpy.org/doc/html/android.html) を使います。ランチャーの **Android** から **SDKのインストール**、**構成の設定**（パッケージ名を設定）、**キーの生成** を一度だけ実施してください（Ren'Py のドキュメント参照）。そのうえで:

1. **ネイティブライブラリを RAPT に一度だけコピーします。** Android はアプリ自身のライブラリフォルダからしかネイティブライブラリを読み込まないので、ABI ごとの `.so` を `game/spritestudio/libs/android/<abi>/libssruntime.so` から Ren'Py SDK へコピーします。

   ```
   <renpy-sdk>/rapt/prototype/renpyandroid/src/main/jniLibs/<abi>/libssruntime.so
   ```

   ABI は `arm64-v8a`（大半の 64bit 端末）、`armeabi-v7a`（旧端末）、`x86_64`（エミュレータ）です。
2. **ビルド** — 同じ画面で **Play Bundle**（`.aab`、Play アップロード用）か **Universal APK**（`.apk`）を選び、**パッケージのビルド** を押します。

## iOS 向けエクスポート

Ren'Py 標準の [renios](https://www.renpy.org/doc/html/ios.html) を使います。**Xcode プロジェクト**を生成し、`.ipa` は Xcode でビルドします。**macOS + Xcode が必須**です。

1. **Xcode プロジェクトを生成** — Ren'Py のランチャー（**iOS** → 初回は **Xcode プロジェクトディレクトリー選択**、続けて **Xcode プロジェクト作成**）、または同等の `<renpy> launcher ios_create . <xcode-project-dir>` CLI コマンドで生成します。
2. **ネイティブライブラリを一度だけ埋め込む** — Xcode で app ターゲット → **General** → **Frameworks, Libraries, and Embedded Content** → **+** → *Add Files…* → `game/spritestudio/libs/ios/libssruntime.xcframework` → **Embed & Sign**。以降の `ios_populate` の再実行でも維持されます。
3. **ビルド** — **シミュレータ**を選んで **Run**（署名不要）、または signing team を設定し **Product > Archive** で実機 `.ipa` を生成します。

## Web (ブラウザ) 向けエクスポート

Ren'Py 標準の [Web エクスポート](https://www.renpy.org/doc/html/web.html) をそのまま使います。このプレイヤーで加わる手順はありません。`game/spritestudio/libs/web/` の WebAssembly 版は `game.zip` に入り、ゲームの起動時に読み込まれます。この WebAssembly 版は **WebAssembly SIMD** を利用するため、対象ブラウザが SIMD に対応している必要があります（[制約と適用範囲](limitations.md) を参照）。

**動作確認:** `file://` ではなく HTTP で配信します（Ren'Py 付属の web サーバで足ります）。再エクスポート後は、キャッシュされた **Service Worker の登録解除 / サイトデータのクリア**を行わないと、ブラウザが古いビルドを表示します。
