[**English**](./README.md) | [**日本語**](./README.ja.md)

# SpriteStudio Player for Ren'Py

**ビジュアルノベルに、エディタで作り込んだ2Dアニメーションを。動画ファイル不要、たった数行で。**

▶️ **[ブラウザでライブデモを試す](https://cri-middleware.github.io/SSPlayerForRenPy/demo/)** — 同梱の SpriteStudio アニメーションを Ren'Py Web で再生できます。

**[SpriteStudio](https://www.webtech.co.jp/spritestudio/)** のアニメーション (`.ssab`) を [Ren'Py](https://www.renpy.org/) でそのまま再生する拡張ライブラリ（プレイヤー）です。普段お使いの PNG / WebP 素材を専用エディタでアニメーションさせ、完成したアニメーションをプロジェクトに組み込むだけ——長くて複雑な ATL も、重い動画ファイルも要りません。

## ✨ SpriteStudio を Ren'Py で使うメリット

- **立ち絵が“生きる”——数値ではなく、目で見て動かせる。** 呼吸・まばたき、なびく髪や衣装、斬撃・魔法のエフェクトまで、動きは専用エディタ（SpriteStudio）でボーン階層・メッシュ変形・パーティクルを使ってビジュアルに作り込みます。ATL で各パーツの位置・回転・タイミングを数値で書いてはリロードして確かめる代わりに、キャンバス上でパーツを動かし、タイミングはタイムラインとイージングカーブで決められるので、立ち絵を描いた人がそのまま動きまで付けられます。Ren'Py はそれを再生するだけです。
- **セリフに合わせて口パク。** `SSCharacter` を 1 行書けば、画像と話者の定義がまとめて済みます。セリフの表示中は talk アニメーション、終われば待機アニメーションに自動で切り替わり、セリフごとのコードは要りません。
- **普通の画像と同じように使える。** `image` 文なしで `show ringo wait1` と書け、別のアニメーションへの切り替えも、表情を変えるときと同じ `show` 1 行です。ATL・`Transform` での配置・スライドイン・ズーム・フェードもそのまま使え、インタラクティブディレクターにも並びます。切り替えをカットではなくブレンドにしたいときは `ss_crossfade()` で次のアニメーションへクロスフェードでき、トラックを重ねれば再生中の動きにまばたきや手振りを足せます。
- **動画（ムービー）の軽量な代替に。** オープニング、動く背景、エフェクトのカットインなど、`Movie` を使っていた場面をアニメーションで置き換えます。自由に拡大縮小でき、シームレスにループし、スクリプトの進行に合わせて切り替わり、動画に焼き込まれたフレームレートではなくディスプレイのリフレッシュレートで動きます。ファイルに入っているのは絵と動きで、毎フレームの画像ではないので、どれだけ滑らかに動かしても大きさは変わりません。
- **エディタから実行画面まで、シームレスな更新。** **Auto Importer**が開発中の `SpriteStudio_Source/` を監視します。**Shift+R** を 1 回押しておけば、あとは SpriteStudio で保存するだけ。変更のあったプロジェクトだけが再コンバートされ、実行中の Ren'Py が自分でリロードして反映します。書き出しの手作業は要りません。

## 📚 ドキュメント

詳細な仕様、インポート手順、APIリファレンスなどの全容については、ドキュメントサイトをご覧ください。

- [**ドキュメントサイト (ホスト版)**](https://cri-middleware.github.io/SSPlayerForRenPy/ja/)
- [**ドキュメント (日本語)**](./docs/ja/index.md)
- [**Documentation (English)**](./docs/en/index.md)
- [**AI アシスタント向け**](https://cri-middleware.github.io/SSPlayerForRenPy/ja/llms.txt) — このドキュメントを Markdown で提供します。`llms.txt` はページの目次、`llms-full.txt` は全ページを 1 ファイルにまとめたものです。インストールした Player にも、同じページが `game/spritestudio/` に入っています
- [**SpriteStudio Docs（ポータル）**](https://cri-middleware.github.io/SpriteStudio-Docs/ja/) — SDK と全公式 Player の入口。コーディングアシスタントに SpriteStudio を教える[プラグイン](https://cri-middleware.github.io/SpriteStudio-Docs/ja/ai/)もあります

---

## 🚀 クイックスタート

**ゲームで使う場合**はこのまま下へ。フォルダを置く → 自分の `.sspj` を変換する → 表示する。その先（イベント、パーツ単位の上書き、`SSCharacter`）も同じ道の続きで、[ドキュメント](./docs/ja/index.md)にあります。
**Player 自体や、その下の Rust コアを変更する場合**は [CONTRIBUTING.md](./CONTRIBUTING.md) と[ビルドガイド](docs/ja/development/build.md)（変更した版をゲームで使う方法と、Ren'Py での確かめ方を含む）へ。層とその理由は[プレイヤーの構成](docs/ja/development/architecture.md)にあります。

**Ren'Py 8.x**（Python 3 系）と、**SpriteStudio 7.6 以上**で作成したプロジェクトを用意してください。

1. **導入**: [`SSPlayerForRenPy.zip`](https://github.com/cri-middleware/SSPlayerForRenPy/releases/latest/download/SSPlayerForRenPy.zip)（常に最新リリースを指す恒久リンク。すべての版は [GitHub Releases](https://github.com/cri-middleware/SSPlayerForRenPy/releases) にあります）をダウンロードして展開し、中の `spritestudio/` フォルダをプロジェクトの `game/` フォルダへコピーします。
2. **変換**: プロジェクトのルート（`game/` と同じ階層）に `SpriteStudio_Source/` フォルダを作り、SpriteStudio のプロジェクトを `.sspj` だけでなくフォルダごとコピーします。Ren'Py ランチャーでプロジェクトを選び **プロジェクトの起動** を押すと、ゲームが始まる前にプロジェクトが `game/ss_assets/<プロジェクト名>/` へ変換されます（ランチャーは開発者モードでゲームを起動し、変換には開発者モードが必要です。配布したゲームが変換することはありません）。

   ```
   MyGame/
   ├── game/
   │   ├── spritestudio/          ← ZIP の中のフォルダをそのまま
   │   │   ├── spritestudio.rpy
   │   │   ├── libs/
   │   │   ├── python/
   │   │   └── …
   │   ├── ss_assets/
   │   │   └── Ringo/             ← ゲームの起動時に変換される
   │   │       ├── Ringo.ssab
   │   │       ├── Ringo.png
   │   │       └── …
   │   └── script.rpy
   └── SpriteStudio_Source/
       └── Ringo/                 ← プロジェクトのフォルダをそのまま
           ├── Ringo.sspj
           ├── Ringo.png
           └── …
   ```

3. **表示**: 変換したパックは、そのまま画像として使えます。名前は `.ssab` のファイル名を小文字にしたもので、アニメーションが属性になります。`game/script.rpy` の、新しいプロジェクトなら `show eileen happy` がある行を `show ringo wait1` にします。

   ```renpy
   label start:

       scene bg room

       show ringo wait1
   ```

   名前が分からないときは、ゲームの実行中に **Shift+B** を押してください。SpriteStudio Browserがパックとアニメーションを一覧にして再生し、貼り付けるスニペットをコピーしてくれます。

SpriteStudio のデータが手元に無くても始められます。[公式のサンプルデータ](https://www.webtech.co.jp/help/ja/spritestudio7/download/sample/)がそのまま使えます。キャラクターなら [Ringo](https://www.webtech.co.jp/help/ja/spritestudio7/download/sample/#ringo) が手頃です。

**次に読む:** [再生と制御](docs/ja/usage.md) · [アセットの取り込み](docs/ja/import.md)（SpriteStudio で編集したあとの[ホットリロード](docs/ja/import.md#ホットリロード)と、Ren'Py を起動せずに変換する方法も含む） · [制約と適用範囲](docs/ja/limitations.md)

## 🔗 関連リポジトリ

- [SpriteStudio Docs](https://cri-middleware.github.io/SpriteStudio-Docs/ja/) — SDK と公式 Player のドキュメントポータル
- [SpriteStudio-SDK](https://github.com/cri-middleware/SpriteStudio-SDK) — `libssruntime` / `libssconverter` を提供する SDK 本体
- [SSConverter GUI](https://github.com/cri-middleware/SSConverterGUI) — Player なしで `.sspj` を変換できるデスクトップ GUI

## 📄 ライセンス

本プロジェクトのソースコードおよび成果物は、[LICENSE.md](LICENSE.md) (BSD-3-Clause) の条件下で提供されています。参考訳は [LICENSE.ja.md](LICENSE.ja.md) にあります。

同梱されている `SpriteStudio-SDK` や、依存するサードパーティライブラリのライセンスについては、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照してください。
