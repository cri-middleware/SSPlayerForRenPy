[**English**](./README.md) | [**日本語**](./README.ja.md)

# SpriteStudio Player for Ren'Py

**[SpriteStudio 7](https://www.webtech.co.jp/spritestudio/)** のアニメーション (`.ssab`) を [Ren'Py](https://www.renpy.org/) で再生するための拡張ライブラリ（プレイヤー）です。

このライブラリを使用することで、Ren'Py ユーザーは長くて複雑な ATL (Animation and Transformation Language) やアニメーション制御のコーディングから解放されます。専用エディタで作り込んだ表現力豊かな2Dアニメーション（なめらかな立ち絵、ダイナミックなUI、エフェクトなど）を、重い動画ファイルに頼ることなく、たった数行のスクリプトで軽量かつ手軽にプロジェクトへ組み込むことができます。

## 📚 ドキュメント (Documentation)

詳細な仕様、インポート手順、APIリファレンスなどの全容については、ドキュメントサイト（MkDocs）をご覧ください。

- [**ドキュメント (日本語)**](./docs/ja/index.md)
- [**Documentation (English)**](./docs/index.md)

### クイックリンク
- [導入ガイド (Setup)](docs/ja/setup.md)
- [データのコンバート (Import)](docs/ja/import.md)
- [再生と制御 (Usage)](docs/ja/usage.md)
- [ビルド・カスタマイズガイド (Build)](docs/ja/build.md)

---

## 🎮 1. クイックスタート (利用者向け)

ビルド済みのパッケージを利用し、負担なく手軽に導入できる方法です。

[GitHub Releases](https://github.com/cri-middleware/SSPlayerForRenPy/releases) から最新のZIPファイルをダウンロードし、展開してできる **`spritestudio/`** フォルダを、ご自身のRen'Pyプロジェクトの `game/` フォルダ内にそのままコピーしてください。これだけで導入は完了です。

```renpy
# ゲームプロジェクト内で呼び出す例
screen demo():
    add SSPlayer("overall/Basic.ssab") xalign 0.5 yalign 0.5
```
※詳しくは [導入ガイド](docs/ja/setup.md) および [再生と制御](docs/ja/usage.md) をご覧ください。

## 🛠 2. カスタマー向け: Playerのカスタマイズ
Ren'Py側のPythonコードやRen'Pyスクリプトを改修したいが、Rust製のSDKコアはビルドせずに既存のものを利用したい方向けの環境構築です。

**macOS / Linux:**
```bash
git submodule update --init
scripts/download-sdk.sh
scripts/deploy-examples.sh
scripts/fetch-renpy-sdk.sh
scripts/run-demo.sh
```

**Windows:**
```powershell
git submodule update --init
scripts\download-sdk.ps1
scripts\deploy-examples.ps1
scripts\fetch-renpy-sdk.ps1
scripts\run-demo.ps1
```
※詳細は [ビルド・カスタマイズガイド](docs/ja/build.md) をご覧ください。

## ⚙️ 3. SDK・Player開発者向け: フルビルド環境
アニメーション計算のコア部分を担うRust製サブモジュール (`SpriteStudio-SDK`) も含めて開発・コントリビュートを行いたい方向けの手順です。

**macOS / Linux:**
```bash
git submodule update --init --recursive
scripts/build-runtime.sh
```

**Windows:**
```powershell
git submodule update --init --recursive
scripts\build-runtime.ps1
```
- 仕様の詳細や正しい実装方法については、**必ず `SpriteStudio-SDK/libs/ssruntime/docs/` にあるPlayer移植ドキュメント（ポーティングガイド）を参照**してください。

## 📄 ライセンス (License)

本プロジェクトのソースコードおよび成果物は、[LICENSE.md](LICENSE.md) (BSD-3-Clause) の条件下で提供されています。

同梱されている `SpriteStudio-SDK` や、依存するサードパーティライブラリのライセンスについては、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照してください。
