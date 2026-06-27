# 開発・ビルドガイド (Build & Customization)

本リポジトリのデモプロジェクトを動かしたり、ネイティブランタイム (`ssruntime`) をカスタマイズしたい開発者向けの手順です。

## 必要な環境
1. **Python (3.x)**: データのコンバートスクリプト (`deploy-examples.sh`) や、`tools/` 内の検証ツール、Ren'Py SDKの取得スクリプトの実行に必要です。
2. **Rust環境 (`rustup`)**: ランタイムライブラリをソースコードからビルドする場合にのみ使用します。公式サイト ([rustup.rs](https://rustup.rs/)) からインストールしてください。
3. **`flatc` (FlatBuffers Compiler)**: 再生データのバインディング定義（自動生成）を再構築する場合のみ必要です。

## 1. リポジトリとサブモジュールの準備
コアとなるランタイムやサンプルデータは `SpriteStudio-SDK` としてサブモジュール化されています。リポジトリのクローン後、必ず初期化を行ってください。
```bash
git clone https://github.com/Naruto/SSPlayerForRenPy.git
cd SSPlayerForRenPy
git submodule update --init --recursive
```

## 2. ネイティブライブラリの準備
Ren'Pyでアニメーションを再生するにはネイティブライブラリ (`.dll`, `.dylib`, `.so`) が必要です。用途に合わせて**ダウンロード**するか**ビルド**してください。

### A. リリース版をダウンロードする（推奨・手軽）
C/Rust側のライブラリコードを書き換えない場合は、ビルド済みのバイナリをダウンロードするのが最も手軽です。
**macOS / Linux:**
```bash
scripts/download-sdk.sh
```

**Windows:**
```powershell
scripts\download-sdk.ps1
```

### B. ソースコードからビルドする（カスタマイズ用）
C/Rustのコードを修正した場合は、以下のスクリプトでビルドを実行します。結果は `game/spritestudio/libs/` に出力されます。
**macOS / Linux:**
```bash
scripts/build-runtime.sh
```

**Windows:**
```powershell
scripts\build-runtime.ps1
```
※リリースビルドを行いたい場合は、引数に `build=release` 等を指定します（詳しくはスクリプトの中身をご参照ください）。

## 3. 開発のイテレーション（デモの操作方法）
ライブラリの準備ができたら、再生データの変換とデモの起動を行います。
これが基本的な開発サイクル（イテレーション）になります。

### 3.1 再生データの変換
デモプロジェクトに含まれるアニメーションデータを用意するため、以下のコンバートスクリプトを実行します。変換された `.ssab` とテクスチャは `game/sprites/` へ出力されます。
**macOS / Linux:**
```bash
scripts/deploy-examples.sh
```

**Windows:**
```powershell
scripts\deploy-examples.ps1
```

### 3.2 デモの起動と動作確認
Ren'Py SDKを自動で取得し、このリポジトリのプロジェクト（デモ）を起動します。
**macOS / Linux:**
```bash
scripts/fetch-renpy-sdk.sh
scripts/run-demo.sh
```

**Windows:**
```powershell
scripts\fetch-renpy-sdk.ps1
scripts\run-demo.ps1
```

**開発サイクルの回し方:**
- Pythonコード (`game/spritestudio/python/`) やRen'Pyスクリプト (`game/*.rpy`) を書き換えた後は、`run-demo.sh` を再実行するだけで変更が反映されます。
- ネイティブライブラリ (`SpriteStudio-SDK/libs/`) 側を書き換えた場合は、再度 `build-runtime.sh` を実行してバイナリを更新してからデモを起動してください。

## 4. FlatBuffers バインディングの更新 (スキーマ変更時)
`SpriteStudio-SDK` 側で FlatBuffers スキーマ (`.fbs` ファイル) に変更が加えられた場合、Python側の読み取りコード（バインディング）を再生成する必要があります。この作業にはローカル環境に `flatc` コンパイラがインストールされ、パスが通っている必要があります。

**macOS / Linux:**
```bash
scripts/generate-runtime-code.sh
```

**Windows:**
```powershell
scripts\generate-runtime-code.ps1
```
※実行すると `game/spritestudio/python/ss/` 以下のPythonコードが自動的に再生成・上書きされます。
※純粋なPython用ランタイムライブラリ自体 (`game/spritestudio/python/flatbuffers/`) を更新したい場合は、`scripts/download-flatbuffers.*` を実行してベンダーリングし直してください。

## SDK開発のルール
- `SpriteStudio-SDK` はコア仕様であるため、Player側（Ren'Py側）の都合で無理なワークアラウンドを入れないでください。仕様変更が必要な場合はSDK本体側のイシューとして提起してください。
