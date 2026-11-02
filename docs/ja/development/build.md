# 🛠️ ビルドガイド

本リポジトリのコードを改修してカスタマイズを行いたい開発者向けの手順です。ビルド、変更した版をゲームで使う方法、Ren'Py での確かめ方があります。プレイヤーの構成とその理由は[プレイヤーの構成](architecture.md)にあります。

> **プレイヤーを自分のゲームで使いたいだけの方**は、このガイドは不要です —
> [導入ガイド (Setup)](../setup.md) と [再生と制御 (Usage)](../usage.md) を参照してください。このページは*本リポジトリ内での作業*（プレイヤーのコードのカスタマイズや、ネイティブライブラリの再ビルド）向けです。（下記の「カスタマー」も開発者＝ Ren'Py 側コードのみを編集する人の意味で、エンドユーザーではありません。）

目的に応じて、以下の2つのいずれかの環境を構築してください。

- **カスタマー**: SDK本体（ネイティブライブラリ）のビルドは行わず、Ren'Py側のPython/Ren'Pyコードのみをカスタマイズしたい方
- **SDK・Player開発者**: ネイティブライブラリ (`libssruntime`, `libssconverter`) を含めてフルビルドし、コア仕様から改修したい方

---

## 1. カスタマー向け: Playerカスタマイズ環境
Rust製のネイティブライブラリをビルドする必要がないため、手軽にカスタマイズ環境を構築できます。

### 1.1 必要な環境
- **`curl`・`tar`・`unzip`**（macOS / Linux）: ダウンロードと取得のスクリプトが使います。Python を別にインストールする必要はありません。`deploy-examples` と `run-demo` は Ren'Py SDK に同梱の Python を使います。

### 1.2 リポジトリの準備
デモが再生するテストプロジェクトを持つ `SpriteStudio-SDK` サブモジュールを初期化します。
```bash
git clone https://github.com/cri-middleware/SSPlayerForRenPy.git
cd SSPlayerForRenPy
git submodule update --init
```

### 1.3 ネイティブライブラリのダウンロード
SDKのリリースからビルド済みバイナリを自動でダウンロード・配置します。
**macOS / Linux:**
```bash
scripts/download-sdk.sh
```
**Windows:**
```powershell
scripts\download-sdk.ps1
```

### 1.4 デモの起動と開発のイテレーション
デモプロジェクトに含まれるアニメーションデータを変換し、Ren'Pyを起動して動作確認を行います。
**macOS / Linux (`*.sh`):**
```bash
# Ren'Py SDKの取得
scripts/fetch-renpy-sdk.sh

# デモ用再生データのコンバートとデモプロジェクトの起動テスト
scripts/deploy-examples.sh
scripts/run-demo.sh
```
**Windows (`*.ps1`):**
```powershell
# Ren'Py SDKの取得
scripts\fetch-renpy-sdk.ps1

# デモ用再生データのコンバートとデモプロジェクトの起動テスト
scripts\deploy-examples.ps1
scripts\run-demo.ps1
```

※ `deploy-examples`, `run-demo` は Ren'Py SDK にバンドルされている Python を使用します。

**開発サイクルの回し方:**
Ren'Py側のPythonコード (`game/spritestudio/python/`) やRen'Pyスクリプト (`game/*.rpy`) を書き換えた後は、`run-demo.sh` を再実行するだけで変更が反映されます。

---

## 2. SDK・Player開発者向け: フルビルド環境
Rust製の `SpriteStudio-SDK` のコードを含めてフルスクラッチでビルド・改修を行う方向けの手順です。

### 2.1 必要な環境
1. **Python (3.x)**: ツールおよび各種スクリプト用。
2. **Rust環境 (`rustup`)**: ランタイムライブラリをソースコードからビルドするために必須です。公式サイト ([rustup.rs](https://rustup.rs/)) からインストールしてください。
3. **`flatc` (FlatBuffers Compiler)**: 再生データのバインディング定義（自動生成）を再構築する場合のみ必要です。
4. **`wasm-pack`**（`cargo install wasm-pack`）: Web（`platform=web`）のビルドに必須です。`wasm-opt` は wasm-pack が自分で取得します。
5. **ビルド先の Rust ターゲット**: macOS では `build-runtime.sh` が universal framework の両方のアーキテクチャを必ずビルドするので、`rustup target add aarch64-apple-darwin x86_64-apple-darwin` を実行しておきます。`platform=android` にはさらに Android NDK、`cargo-ndk`（`cargo install cargo-ndk`）、`rustup target add aarch64-linux-android armv7-linux-androideabi x86_64-linux-android` が、`platform=ios` には Xcode と `rustup target add aarch64-apple-ios aarch64-apple-ios-sim x86_64-apple-ios` が要ります。

### 2.2 リポジトリとサブモジュールの完全な準備
1.2 と同じようにサブモジュールを初期化します。SDK が依存するクレートは、ビルドの際に cargo が取得します。
```bash
git clone https://github.com/cri-middleware/SSPlayerForRenPy.git
cd SSPlayerForRenPy
git submodule update --init
```

### 2.3 ネイティブライブラリのビルド
C/Rustのコードを修正・ビルドします。結果は `game/spritestudio/libs/` に出力されます。
**macOS / Linux:**
```bash
scripts/build-runtime.sh
```
**Windows:**
```powershell
scripts\build-runtime.ps1
```
※リリースビルドを行いたい場合は、引数に `build=release` 等を指定します（オプションの一覧は `--help` で確認できます）。

### 2.4 デモの起動と開発のイテレーション
カスタマー向けと同様に、データのコンバートとデモ起動を行います。**開発サイクルの回し方:**
ネイティブライブラリ (`SpriteStudio-SDK/libs/`) 側を書き換えた場合は、再度 `build-runtime.sh` を実行してバイナリを更新してから `run-demo.sh` を起動してください。

### 2.5 FlatBuffers バインディングの更新 (スキーマ変更時)
`SpriteStudio-SDK` 側で FlatBuffers スキーマ (`.fbs` ファイル) に変更が加えられた場合、Python側の読み取りコード（バインディング）を再生成する必要があります。この作業にはローカル環境に `flatc` コンパイラがインストールされ、パスが通っている必要があります。

**macOS / Linux:**
```bash
scripts/generate-fbs-code.sh
```
**Windows:**
```powershell
scripts\generate-fbs-code.ps1
```
※実行すると `game/spritestudio/python/ss/` 以下のPythonコードが自動的に再生成・上書きされます。
※純粋なPython用ランタイムライブラリ自体 (`game/spritestudio/python/flatbuffers/`) を更新したい場合は、`scripts/download-flatbuffers.*` を実行してベンダーリングし直してください。

### 2.6 SDK開発のルール
- `SpriteStudio-SDK` はコア仕様であるため、Player側（Ren'Py側）の都合で無理なワークアラウンドを入れないでください。仕様変更が必要な場合はSDK本体側のイシューとして提起してください。

---

## 3. 各プラットフォームへのエクスポート (ヘルパースクリプト)

本リポジトリには、デモの各プラットフォーム向けエクスポートを実行し、SSPlayer 固有の後処理を自動で適用する `scripts/` 以下のヘルパースクリプトが含まれています。これは
[エクスポートガイド](../export.md) に記載した手動手順の**開発者向けの対応物**で、上記で取得した Ren'Py SDK を利用します。

> これらのスクリプトは**本リポジトリ内での作業**用です。自分のゲームをエクスポートする制作者は標準の Ren'Py ランチャーを使ってください（[エクスポートガイド](../export.md) 参照）。

### 3.1 前提条件
- **対象**プラットフォームのネイティブライブラリが `game/spritestudio/libs/` に配置済みであること — `scripts/download-sdk.*`（ビルド済み）または `scripts/build-runtime.*`
  （ソース）。デスクトップ / モバイル / Web はそれぞれ専用が必要です。例:
  `build-runtime.* platform=android build=release`、`platform=ios`、`platform=web`。
- Ren'Py SDK（`scripts/fetch-renpy-sdk.*`）。desktop / Android / iOS の deploy スクリプトは無ければ自動取得します（`deploy-web.*` は先に実行するよう促して終了します）。
- プラットフォーム固有ツールチェーン（一度だけ）:
    - **Android**: `scripts/fetch-renpy-android.*`（RAPT）取得後、launcher GUI（→ Android）から **Install SDK**、**Configure**（`android.json` にパッケージ名を設定。必須）、
      **Generate Keys** を実施。
    - **iOS**: `scripts/fetch-renpy-ios.sh`（renios。macOS 専用）。
    - **Web**: `scripts/fetch-renpy-web.*`（Ren'Py の Web サポート）。

### 3.2 エクスポートコマンド

**macOS / Linux (`*.sh`):**
```bash
scripts/deploy-desktop.sh [dest_dir]                       # ホスト OS のデスクトップアプリ (mac / linux)
scripts/deploy-android.sh [dest_dir] [--bundle] [--install] [--launch]
scripts/deploy-ios.sh     [dest_dir] [--recreate] [--open] # Xcode プロジェクトを生成 (macOS 専用)
scripts/deploy-web.sh     [dest_dir]                       # 標準の Web エクスポート（後処理は無し）
```

**Windows (`*.ps1`):**
```powershell
scripts\deploy-desktop.ps1 [dest_dir]                      # win デスクトップアプリ
scripts\deploy-android.ps1 [dest_dir] [--bundle] [--install] [--launch]
scripts\deploy-web.ps1     [dest_dir]
# (iOS エクスポートは macOS 専用のため deploy-ios.ps1 はありません)
```

- **デスクトップ**: ホスト OS 向けにビルド（`.sh`: mac / linux、`.ps1`: win）し、そのまま実行できる形に展開します。ネイティブライブラリがあるプラットフォームのみ実行可能な形でビルドできます。
- **Android**: `--bundle` は `.aab`（Play アップロード用）、`--install` / `--launch` は
  `adb` で端末へ転送・起動します。
- **iOS**: Xcode プロジェクトを生成 / 更新します。Brain は Xcode での一度きりの
  **Embed & Sign** が別途必要です（[エクスポートガイド](../export.md) 参照）。
- **Web**: 標準の Web エクスポートを実行するだけで、後処理はありません。出力は正しい MIME タイプで HTTP 配信してください。

各プラットフォームでこれらのスクリプトの処理が要る理由（ABI ごとの `.so`、動的な iOS xcframework）は[ネイティブライブラリの読み込み元](architecture.md#ネイティブライブラリの読み込み元)に、`.rpa` の順序は [エクスポートガイド](../export.md) にあります。

---

## 4. 変更したプレイヤーを使う

ゲームはプレイヤーを 1 つのフォルダとして取り込むので、チェックアウトもリリースと同じ方法でゲームに入れられます。

1. ネイティブライブラリを置きます。リリース版なら `scripts/download-sdk.*`、SDK を変更したなら `scripts/build-runtime.*` です（[2.3](#23-ネイティブライブラリのビルド)。Android・iOS・Web は `platform=` で指定します）。
2. ゲームの `game/spritestudio/` を削除してから、チェックアウトの `game/spritestudio/` をコピーします。先に削除するのは、`.rpy` が無くなっても Ren'Py が残った `.rpyc` を実行し続けるためです。

変更をほかの人に渡すときは、リリースが公開する zip を作ります。`scripts/build-release.sh demo=skip sdk=skip` が、手順 1 で置いたライブラリのまま、チェックアウトから `release-dist/SSPlayerForRenPy-<version>.zip` を書き出します。`sdk=skip` を付けないと、先に `scripts/SDK_VERSION.txt` が指す SDK リリースをその上にインストールします（選択肢は `--help` にあります）。インストールは [導入ガイド](../setup.md) のとおりです。

---

## 5. 実際のホストで確かめる

`scripts/run-tests.sh` は、エンジン非依存のコアを素の CPython で確かめます。その規則は CONTRIBUTING にあります。それで確かめられないもの（描画、Displayable、ランチャー、エクスポート）は Ren'Py を動かして確かめます。どれもスクリプトから回せます。

### 5.1 Ren'Py の表記の引き方

ガイドでは、ランチャーの画面とゲーム内の開発者ツールを Ren'Py の表示どおりに書きます。英語の文字列は `renpy-sdk/launcher/game/*.rpy`（ランチャー）と `renpy-sdk/renpy/common/`（ゲーム内のツール）の `_("…")` の呼び出し、日本語は `renpy-sdk/launcher/game/tl/japanese/` の `old` / `new` の組です。たとえば **Create Xcode Project** は英語が `ios.rpy`、日本語が `tl/japanese/launcher.rpy` の「Xcode プロジェクト作成」です。

### 5.2 人が操作せずに描画を確かめる

GL2 の描画にはヘッドレスの確認がありません。それでも、使い捨てのスクリプトで起動からスクリーンショットまでを回せます。次を `game/zz_check.rpy` として保存し、終わったらそれと `.rpyc` を消してください。

```renpy
init python:
    import os as _check_os
    if _check_os.environ.get("SS_CHECK_PACK"):
        config.label_overrides["start"] = "zz_check"
        config.log = "zz_check_log.txt"

label zz_check:
    scene expression Solid("#202020")
    $ _p = SSPlayer(_check_os.environ["SS_CHECK_PACK"], size=(1280, 720))
    show expression _p as check:
        xalign 0.5 yalign 0.5
    pause 1.5
    python:
        renpy.screenshot(_check_os.environ["SS_CHECK_SHOT"])
        renpy.quit()
```

実行は `RENPY_SKIP_MAIN_MENU=1 SS_CHECK_PACK=ss_assets/Ringo/Ringo.ssab SS_CHECK_SHOT=<png> renpy-sdk/renpy.sh .` です。

- `RENPY_SKIP_MAIN_MENU` を付けないと、メインメニューで待ち続け、`label_overrides` が効きません。
- 例外が起きると、Ren'Py はエラー画面で待ち続けます。`traceback.txt` の出現を見張り、実行時間を区切り（`perl -e 'alarm 60; exec @ARGV' renpy-sdk/renpy.sh .`）、結果はファイルに書いてください。kill されたプロセスはバッファにある出力を失います。
- Player 自身の報告（`[SSPlayer] …`）は print で出すので、どのプロジェクトでも `log.txt` とコンソールに届きます。`renpy.log` は、`config.log` が無いと何も書きません。
- `modal True` の画面（Shift+B のブラウザなど）を出したまま `renpy.pause` すると戻りません。`zorder` の高い画面の `timer … repeat True` で手順を進め、ラベルでは `$ ui.interact()` で待ちます。
- 操作は本物の入力で起こします。`renpy.test.testmouse` の `move_mouse`・`press_mouse`・`release_mouse` を、`renpy.display.focus.focus_list` から読んだ位置で使います。Displayable の状態を書き換えてドラッグを真似ると、Ren'Py が実際に通る経路を素通りします。
- init のコードは要るが描画は要らないもの（`SSPlayer` のコンストラクタ、`_duplicate`、読み込み、インポーター）は、init ブロックを実行する lint で回せます。使い捨ての `game/zz_*.rpy` に `init 999 python:` を書き、`renpy-sdk/renpy.sh . lint --error-code` を実行します。
- デモ自体のスクリプト（`spritestudio/` の外の `game/*.rpy`）にはテストが無く、lint もその Python の中の `ss_*` の呼び出しは確かめません。`ss_*` のメソッドを改名したら、手で探してください。

### 5.3 Web 版

`scripts/deploy-web.sh <dir>` でビルドし、HTTP で配信して（`python3 -m http.server <port>`）Chrome で開きます。ヘッドレスの Chrome では DevTools プロトコルで操作します。

- Ren'Py Web は emscripten でコンパイルした CPython で、Pyodide ではありません。
- ビルドごとにポートを変えてください。`http.server` は `Cache-Control` を返さないので、古いビルドが返ることがあります。
- 起動には 1〜2 分かかります。橋渡しが wasm を読み込むと `window.ss_runtime_state` が `ready` になり、ページから `renpy_exec("…")` でゲーム内の Python を実行できます。
- 画面が変わるたびに、canvas への最初のクリックはフォーカスに使われます。
- JavaScript の例外は、何も言わずに Ren'Py のループを止めます。`renpy_exec` が返らなくなり、CPU が止まります。例外はプロトコルの `Runtime.exceptionThrown` で読みます。

### 5.4 Android と iOS

`scripts/deploy-android.*` は RAPT でビルドし、RAPT は JDK 21 を必要とします。`JAVA_HOME` を JDK 21 に向けてください。向けないと `android_build` が "Java version is wrong" で失敗します。`scripts/deploy-ios.sh` は Xcode プロジェクトを生成し、xcframework を配置します。一度 **Embed & Sign** すれば、シミュレータでの実行には署名が要りません。

### 5.5 ホットパスを測る

`game/ss_assets/` のパックで、ヘッドレスの `SSInternalPlayer` の `update()` を計時します。比較は 1 つのディレクトリの中で行い、試す `.py` を差し替えながら 3 周以上回し、パックごとの最小値を取ります。同じコードでも、repo の別のチェックアウトで測ると 13% ほど違うことがあります。効くのは、仕事をインタプリタから C に移すことです（ベクタ全体を 1 回の `struct.unpack` で読む、`append` のループを `list.extend` にする、頂点ループの不変量を外に出す）。`.rpy` のコードが遅いときは、まず cProfile で `renpy/revertable.py` が上位に出ていないかを見てください。`.rpy` で作ったリストは `RevertableList` になり、変更のたびにロールバック用の記録が残り、Ren'Py のメッシュはその要素を 1 つずつ読み戻します。

---
