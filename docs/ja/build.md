# 開発・ビルド・カスタマイズガイド (Build & Customization)

本リポジトリのコードを改修してカスタマイズを行いたい開発者向けの手順です。
目的に応じて、以下の2つのいずれかの環境を構築してください。

- **カスタマー**: SDK本体（ネイティブライブラリ）のビルドは行わず、Ren'Py側のPython/Ren'Pyコードのみをカスタマイズしたい方
- **SDK・Player開発者**: ネイティブライブラリ (`libssruntime`, `libssconverter`) を含めてフルビルドし、コア仕様から改修したい方

---

## 1. カスタマー向け: Playerカスタマイズ環境
Rust製のネイティブライブラリをビルドする必要がないため、手軽にカスタマイズ環境を構築できます。

### 1.1 必要な環境
- **Python (3.x)**: デモ用データのコンバートスクリプト (`deploy-examples.sh`) や、Ren'Py SDKの取得スクリプトの実行に必要です。

### 1.2 リポジトリの準備
デモ用のテストデータ等を取得するため、サブモジュールを初期化します。ここではネイティブのビルド環境は不要なため、`--recursive` オプションは**付けません**。
```bash
git clone https://github.com/Naruto/SSPlayerForRenPy.git
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
4. **`wasm-opt` (Binaryen)**: Web (WASM) ターゲット向けにビルドを行う場合に必須です。

### 2.2 リポジトリとサブモジュールの完全な準備
依存する全てのクレート等を含めて取得するため、`--recursive` を付けてサブモジュールを初期化します。
```bash
git clone https://github.com/Naruto/SSPlayerForRenPy.git
cd SSPlayerForRenPy
git submodule update --init --recursive
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
※リリースビルドを行いたい場合は、引数に `build=release` 等を指定します（詳しくはスクリプトの中身をご参照ください）。

### 2.4 デモの起動と開発のイテレーション
カスタマー向けと同様に、データのコンバートとデモ起動を行います。
**開発サイクルの回し方:**
ネイティブライブラリ (`SpriteStudio-SDK/libs/`) 側を書き換えた場合は、再度 `build-runtime.sh` を実行してバイナリを更新してから `run-demo.sh` を起動してください。

### 2.5 FlatBuffers バインディングの更新 (スキーマ変更時)
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

### 2.6 SDK開発のルール
- `SpriteStudio-SDK` はコア仕様であるため、Player側（Ren'Py側）の都合で無理なワークアラウンドを入れないでください。仕様変更が必要な場合はSDK本体側のイシューとして提起してください。
