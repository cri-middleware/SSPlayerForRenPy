# ビルドガイド (Build & Customization)

C/Rustネイティブランタイムのカスタマイズや、最新のSDKモジュールを利用してソースコードから自分でビルドを行いたいユーザー・開発者向けの手順です。

## 必要な環境
1. **Rust ツールチェーン (`cargo`)**: ランタイムライブラリのコンパイルに使用します。
2. **`flatc` (FlatBuffers Compiler)**: 再生データのバインディング定義（自動生成）を再構築する場合のみ必要です。

## 1. リポジトリとサブモジュールの準備
コアとなるランタイム ("Brain") は `SpriteStudio-SDK` としてサブモジュール化されています。リポジトリのクローン後、必ず初期化を行ってください。
```bash
git clone https://github.com/Naruto/SSPlayerForRenPy.git
cd SSPlayerForRenPy
git submodule update --init --recursive
```

## 2. ネイティブライブラリのビルド
`scripts/` 以下のビルドスクリプトを実行すると、プラットフォームごとのネイティブライブラリ (`.dll`, `.dylib`, `.so`) が `game/spritestudio/libs/` に出力されます。

```bash
# macOS または Linux の場合
scripts/build-runtime.sh

# Windows の場合
scripts\build-runtime.ps1
```
※リリースビルドを行いたい場合は、引数に `build=release` 等を指定します（詳しくはスクリプトの中身をご参照ください）。

## 3. デモ用再生データの変換
デモプロジェクトに含まれるアニメーションデータを用意するには、以下のデータコンバートスクリプトを実行します。変換された `.ssab` とテクスチャは `game/sprites/` へ出力されます。

```bash
# macOS または Linux の場合
scripts/deploy-examples.sh

# Windows の場合
scripts\deploy-examples.ps1
```

## SDK開発のルール
- `SpriteStudio-SDK` はコア仕様であるため、Player側（Ren'Py側）の都合で無理なワークアラウンドを入れないでください。仕様変更が必要な場合はSDK本体側のイシューとして提起してください。
