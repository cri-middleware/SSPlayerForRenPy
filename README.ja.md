[**English**](./README.md) | [**日本語**](./README.ja.md)

# SpriteStudio Player for Ren'Py

**ビジュアルノベルに、エディタで作り込んだ2Dアニメーションを。動画ファイル不要、たった数行で。**

▶️ **[ブラウザでライブデモを試す](https://cri-middleware.github.io/SSPlayerForRenPy/demo/)** — 同梱の SpriteStudio アニメーションを Ren'Py Web で再生できます。

**[SpriteStudio](https://www.webtech.co.jp/spritestudio/)** のアニメーション (`.ssab`) を [Ren'Py](https://www.renpy.org/) でそのまま再生する拡張ライブラリ（プレイヤー）です。普段お使いの PNG / WebP 素材を専用エディタでアニメーションさせ、完成したアニメーションをプロジェクトに組み込むだけ——長くて複雑な ATL も、重い動画ファイルも要りません。

## ✨ SpriteStudio を Ren'Py で使うメリット

- **立ち絵が“生きる”。** 呼吸・まばたき、なびく髪や衣装、斬撃・魔法のエフェクトまで——動きは専用エディタ（SpriteStudio）で、ボーン階層・メッシュ変形・パーティクルを使ってビジュアルに作り込み、Ren'Py はそれを再生するだけ。
- **数値ではなく、目で見て動かせる。** ATL でパーツごとに動かすと、各パーツの位置・回転・タイミングを数値で書いては、リロードして見た目を確かめることになります。SpriteStudio ならキャンバス上でパーツを動かし、タイミングはタイムラインとイージングカーブで決めて、作りながら動きを確かめられます。立ち絵を描いた人が、そのまま動きまで付けられます。
- **セリフに合わせて口パク。** `SSCharacter` を 1 行書けば、画像と話者の定義がまとめて済みます。セリフの表示中は talk アニメーション、終われば待機アニメーションに自動で切り替わり、セリフごとのコードは要りません。
- **普通の画像と同じように使える。** `image` 文なしで `show ringo wait1` と書け、別のアニメーションへの切り替えも、表情を変えるときと同じ `show` 1 行です。ATL・`Transform` での配置・スライドイン・ズーム・フェードもそのまま使え、Interactive Director にも並びます。
- **動画（ムービー）の軽量な代替に。** オープニング、動く背景、エフェクトのカットインなど、`Movie` を使っていた場面をアニメーションで置き換えます。自由に拡大縮小でき、シームレスにループし、スクリプトの進行に合わせて切り替わり、動画に焼き込まれたフレームレートではなくディスプレイのリフレッシュレートで動きます。同梱の Ringo は、全アニメーションとテクスチャを合わせても 300 KB 未満です。
- **エディタから実行画面まで、シームレスな更新。** **オートインポーター機能**が開発中の `SpriteStudio_Source/` を監視します。**Shift+R** を 1 回押しておけば、あとは SpriteStudio で保存するだけ。変更のあったプロジェクトだけが再コンバートされ、実行中の Ren'Py が自分でリロードして反映します。書き出しの手作業は要りません。

## 📚 ドキュメント

詳細な仕様、インポート手順、APIリファレンスなどの全容については、ドキュメントサイト（MkDocs）をご覧ください。

- [**ドキュメントサイト (ホスト版)**](https://cri-middleware.github.io/SSPlayerForRenPy/ja/)
- [**ドキュメント (日本語)**](./docs/ja/index.md)
- [**Documentation (English)**](./docs/en/index.md)
- [**AI アシスタント向け**](https://cri-middleware.github.io/SSPlayerForRenPy/ja/llms.txt) — このドキュメントを Markdown で提供します。`llms.txt` はページの目次、`llms-full.txt` は全ページを 1 ファイルにまとめたものです
- [**SpriteStudio Docs（ポータル）**](https://cri-middleware.github.io/SpriteStudio-Docs/ja/) — SDK と全公式 Player の入口

### クイックリンク
- [導入ガイド (Setup)](docs/ja/setup.md)
- [データのコンバート (Import)](docs/ja/import.md)
- [再生と制御 (Usage)](docs/ja/usage.md)
- [制約と適用範囲](docs/ja/limitations.md)

---

## 🚀 1. クイックスタート

**ゲームで使う場合**はこのまま下へ。フォルダを置く → 自分の `.sspj` を変換する → 1 行書く。その先（イベント、パーツ単位の上書き、`SSCharacter`）も同じ道の続きで、[ドキュメント](./docs/ja/index.md)にあります。
**Player 自体や、その下の Rust コアを変更する場合**は [2 章](#%EF%B8%8F-2-フル開発環境sdk--player-開発者)へ。

### 導入方法

**Ren'Py 8.x**（Python 3 系）と、**SpriteStudio 7.5 以上**で作成されたアニメーションが前提です。

ビルド済みのパッケージを利用し、負担なく手軽に導入できる方法です。

最新パッケージ — [`SSPlayerForRenPy.zip`](https://github.com/cri-middleware/SSPlayerForRenPy/releases/latest/download/SSPlayerForRenPy.zip)（恒久リンク・常に最新リリース。特定バージョンは [GitHub Releases](https://github.com/cri-middleware/SSPlayerForRenPy/releases) から）— をダウンロードし、展開してできる **`spritestudio/`** フォルダを、ご自身のRen'Pyプロジェクトの `game/` フォルダ内にそのままコピーしてください。これだけで導入は完了です。

```renpy
# ゲームプロジェクト内で呼び出す例
screen demo():
    add SSPlayer("overall/Basic.ssab") xalign 0.5 yalign 0.5
```
※詳しくは [導入ガイド](docs/ja/setup.md) および [再生と制御](docs/ja/usage.md) をご覧ください。

**自分のアニメーションも同じ流れで入ります。** SpriteStudio のプロジェクトを `SpriteStudio_Source/` に置けば、次のリロードで Auto Importer が変換します（[ホットリロード](docs/ja/import.md#ホットリロード)をオンにしていれば、そのリロードも自動です）。手動の書き出し手順はありません。Ren'Py を起動せずに変換する 2 つの経路（デスクトップの SSConverter GUI、CI 向けの `ssconverter-cli`）も [アセットの取り込み](docs/ja/import.md) にあります。

### チェックアウトから動かしてみる

> これは上の導入手順の一部ではなくチェックアウトなので、パッケージを使うだけなら不要です。

同梱のデモを実行して、プレイヤーが正しく動作することを確認できます。以下のスクリプトは、ビルド済みのRust製SDKコアを取得し、デモを起動します（コアを自前でビルドする必要はありません）。

**macOS / Linux (`*.sh`):**
```bash
git clone https://github.com/cri-middleware/SSPlayerForRenPy.git
cd SSPlayerForRenPy
git submodule update --init --recursive
scripts/download-sdk.sh
scripts/fetch-renpy-sdk.sh
scripts/deploy-examples.sh
scripts/run-demo.sh
```

**Windows (`*.ps1`):**
```powershell
git clone https://github.com/cri-middleware/SSPlayerForRenPy.git
cd SSPlayerForRenPy
git submodule update --init --recursive
scripts\download-sdk.ps1
scripts\fetch-renpy-sdk.ps1
scripts\deploy-examples.ps1
scripts\run-demo.ps1
```

※ `deploy-examples`, `run-demo` は Ren'Py SDK にバンドルされている Python を使用します。
※詳細は [ビルド・カスタマイズガイド](docs/ja/build.md) をご覧ください。

## ⚙️ 2. フル開発環境（SDK / Player 開発者）
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

- [チェックアウトから動かしてみる](#チェックアウトから動かしてみる)の `scripts/download-sdk.*`（ビルド済みコアの取得）の代わりに `scripts/build-runtime.*` を実行し、コアを自前でビルドします。以降の `fetch-renpy-sdk` / `deploy-examples` / `run-demo` は同じ手順です。

## 🔗 関連リポジトリ

- [SpriteStudio Docs](https://cri-middleware.github.io/SpriteStudio-Docs/ja/) — SDK と公式 Player のドキュメントポータル
- [SpriteStudio-SDK](https://github.com/cri-middleware/SpriteStudio-SDK) — `libssruntime` / `libssconverter` を提供する SDK 本体
- [SSConverter GUI](https://github.com/cri-middleware/SSConverterGUI) — Player なしで `.sspj` を変換できるデスクトップ GUI

## 📄 ライセンス

本プロジェクトのソースコードおよび成果物は、[LICENSE.md](LICENSE.md) (BSD-3-Clause) の条件下で提供されています。参考訳は [LICENSE.ja.md](LICENSE.ja.md) にあります。

同梱されている `SpriteStudio-SDK` や、依存するサードパーティライブラリのライセンスについては、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照してください。
