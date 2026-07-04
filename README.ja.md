[**English**](./README.md) | [**日本語**](./README.ja.md)

# SpriteStudio Player for Ren'Py

**ビジュアルノベルに、エディタで作り込んだ2Dアニメーションを。動画ファイル不要、たった数行で。**

**[OPTPiX SpriteStudio 7](https://www.webtech.co.jp/spritestudio/)** のアニメーション (`.ssab`) を [Ren'Py](https://www.renpy.org/) でそのまま再生する拡張ライブラリ（プレイヤー）です。普段お使いの PNG / WebP 素材を専用エディタでアニメーションさせ、完成したアニメーションをプロジェクトに組み込むだけ——長くて複雑な ATL も、重い動画ファイルも要りません。

## ✨ SpriteStudio Player の特長

- **エディタで作り込むアニメ。ATL の手書きは不要。** SpriteStudio 7 は**ラスター（ビットマップ画像）ベースの2Dアニメーション**専用エディタで、ボーン階層・メッシュ変形・パーティクルエフェクトに対応します。動きはビジュアルに作り込み、プレイヤーはそれを再生するだけ。アニメーションそのものを長くて複雑な ATL (Animation and Transformation Language) で書く必要はありません。
- **動画（ムービー）の軽量な代替に。** Ren'Py の演出で多用される動画——`.webm` / `.ogv` / `.mp4` などを `Movie` で再生するオープニングムービー、動く背景、エフェクトのカットイン——を、軽量なネイティブ再生で置き換えます。実行時に自由に拡大縮小でき、シームレスにループし、ただ流れるだけでなくゲームの状態に反応します。重い動画ファイルは不要です。
- **手持ちの素材（PNG / WebP）をそのまま活用。** テクスチャは Ren'Py 標準の画像パイプラインで読み込むため、PNG も WebP もプロジェクト内の他の画像とまったく同じように扱えます。
- **ATL・`Transform` とも共存。** `SSPlayer` は Ren'Py 標準の Displayable なので、ATL が活きる場面はそのまま活かせます。アニメーション全体を、通常の画像と同じように配置・スライドイン・ズーム・フェードできます。

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

**macOS / Linux (`*.sh`):**
```bash
git submodule update --init
scripts/download-sdk.sh
scripts/fetch-renpy-sdk.sh
scripts/deploy-examples.sh
scripts/run-demo.sh
```

**Windows (`*.ps1`):**
```powershell
git submodule update --init
scripts\download-sdk.ps1
scripts\fetch-renpy-sdk.ps1
scripts\deploy-examples.ps1
scripts\run-demo.ps1
```

※ `deploy-examples`, `run-demo` は Ren'Py SDK にバンドルされている Python を使用します。
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
