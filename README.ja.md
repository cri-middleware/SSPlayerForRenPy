[**日本語**](./README.ja.md) | [**English**](./README.md)

# SpriteStudio Player for Ren'Py

**[SpriteStudio 7](https://www.webtech.co.jp/spritestudio/)** のアニメーション (`.ssab`) を [Ren'Py](https://www.renpy.org/) で再生するための拡張ライブラリ（プレイヤー）です。

## 📚 ドキュメント (Documentation)
本リポジトリのドキュメントは、以下の3つのペルソナ（対象読者）に向けて構成されています。ご自身の目的に合わせた項目を参照してください。

- **利用者**: 提供されているパッケージをそのままゲームに組み込みたい方
- **カスタマー**: SDK本体のビルドは行わず、Ren'Py側（Player側）の挙動をカスタマイズしたい方
- **SDK・Player開発者**: ネイティブライブラリ(Rust)を含めたコア部分から自身でビルドし、開発・改修を行いたい方

目的別の詳細な手順や仕様については、以下のドキュメントをご参照ください。
- **[導入ガイド (Setup)](docs/setup.md)**: ゲームプロジェクトへの組み込み方法（利用者向け）
- **[データのコンバート (Import)](docs/import.md)**: アニメーションデータ (`.sspj`) の変換方法
- **[再生と制御 (Usage)](docs/usage.md)**: Ren'Pyスクリプトからの呼び出し方
- **[ビルド・カスタマイズガイド (Build)](docs/build.md)**: カスタマイズ環境の構築とネイティブのビルド手順（カスタマー・開発者向け）
- **[仕様と制約事項 (Limitations)](docs/limitations.md)**: 対応状況・未サポート機能の一覧

---

## 🎮 1. 利用者向け: ゲームへの組み込み手順 (Quick Start)
ビルド済みのパッケージを利用し、負担なく手軽に導入できる方法です。

[GitHub Releases](https://github.com/cri-middleware/SSPlayerForRenPy/releases) から最新のZIPファイルをダウンロードし、展開してできる **`spritestudio/`** フォルダを、ご自身のRen'Pyプロジェクトの `game/` フォルダ内にそのままコピーしてください。これだけで導入は完了です。

```renpy
# ゲームプロジェクト内で呼び出す例
screen demo():
    add SSPlayer("overall/Basic.ssab") xalign 0.5 yalign 0.5
```
※詳しくは [導入ガイド](docs/setup.md) および [再生と制御](docs/usage.md) をご覧ください。

## 🛠 2. カスタマー向け: Playerのカスタマイズ
Ren'Py側のPythonコードやRen'Pyスクリプトを改修したいが、Rust製のSDKコア(ネイティブライブラリ)はビルドせずに既存のものをそのまま利用したい方向けの環境構築です。
`SpriteStudio-SDK` をリカーシブ(recursive)にクローンして自身でビルドする必要はなく、公式リリースからビルド済みバイナリを取得します。

**macOS / Linux:**
```bash
# デモのデータ等を利用するためサブモジュールを取得 (recursiveは不要)
git submodule update --init

# SDKのネイティブライブラリをReleasesからダウンロード
scripts/download-sdk.sh

# デモ用再生データのコンバート
scripts/deploy-examples.sh

# Ren'Py SDKの取得とデモプロジェクトの起動テスト
scripts/fetch-renpy-sdk.sh
scripts/run-demo.sh
```

**Windows:**
```powershell
# デモのデータ等を利用するためサブモジュールを取得 (recursiveは不要)
git submodule update --init

# SDKのネイティブライブラリをReleasesからダウンロード
scripts\download-sdk.ps1

# デモ用再生データのコンバート
scripts\deploy-examples.ps1

# Ren'Py SDKの取得とデモプロジェクトの起動テスト
scripts\fetch-renpy-sdk.ps1
scripts\run-demo.ps1
```
※詳細は [ビルド・カスタマイズガイド](docs/build.md) をご覧ください。

## ⚙️ 3. SDK・Player開発者向け: フルビルド環境
アニメーション計算のコア部分を担うRust製サブモジュール (`SpriteStudio-SDK`) も含めて開発・コントリビュートを行いたい方向けの手順です。
`rustup` を用いて、自身で `libssconverter` および `libssruntime` をビルドして配置するため、事前に Rust ツールチェーン (`cargo` / `rustup`) の環境構築が必要です。

**macOS / Linux:**
```bash
# サブモジュールを含めて完全にクローン
git submodule update --init --recursive

# ネイティブランタイムのビルド
scripts/build-runtime.sh

# 以降はカスタマー向けと同様にデモを起動できます
```

**Windows:**
```powershell
# サブモジュールを含めて完全にクローン
git submodule update --init --recursive

# ネイティブランタイムのビルド
scripts\build-runtime.ps1

# 以降はカスタマー向けと同様にデモを起動できます
```

- `tools/` フォルダ内のPythonスクリプトを利用することで、Ren'Pyを起動せずにヘッドレスでの動作検証が可能です。
- 仕様の詳細や正しい実装方法については、**必ず `SpriteStudio-SDK/libs/ssruntime/docs/` にあるPlayer移植ドキュメント（ポーティングガイド）を参照**してください。
