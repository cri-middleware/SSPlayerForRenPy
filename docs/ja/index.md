# 🎭 SpriteStudio Player for Ren'Py

[SpriteStudio](https://www.webtech.co.jp/spritestudio/) で作成したアニメーションを [Ren'Py](https://www.renpy.org/) 上で再生するためのプラグイン（プレイヤー）です。SpriteStudio のプロジェクトをゲームに置き、Ren'Py ランチャーで **プロジェクトの起動** を押せば、`show` の 1 行でアニメを表示できます。

> [!TIP] ブラウザで試す
> [▶️ サンプルプロジェクトを再生する](https://cri-middleware.github.io/SSPlayerForRenPy/demo/) — 本ドキュメントと同じサイトで公開している
> Ren'Py Web ビルドです。インストールは不要です。

> [!TIP] SpriteStudio のデータが手元に無くても始められます
> [公式のサンプルデータ](https://www.webtech.co.jp/help/ja/spritestudio7/download/sample/)がそのまま使えます。キャラクターなら
> [Ringo](https://www.webtech.co.jp/help/ja/spritestudio7/download/sample/#ringo)、エフェクトを含むものなら
> [パーティクル](https://www.webtech.co.jp/help/ja/spritestudio7/download/sample/#Perticle_sample) が手頃です。自分のアニメーションを作るには SpriteStudio 本体を使います（[製品サイト](https://www.webtech.co.jp/spritestudio/)）。

## 目次

本ドキュメントは、目的別に以下の構成となっています。

- **利用者向けガイド**
    - [導入ガイド (Setup)](setup.md): ゲームプロジェクトへの組み込み方法
    - [アセットの取り込み (Import)](import.md): `.sspj` アニメーションデータの変換方法
    - [再生と制御 (Usage)](usage.md): Ren'Pyスクリプトからの呼び出し方・制御方法
    - [ボタン](buttons.md): アニメーションを、idle・hover・insensitive の状態を持つボタンにする方法
    - [ゲームのエクスポート (Export)](export.md): 標準の Ren'Py ツールで各プラットフォーム（デスクトップ / モバイル / Web）へ書き出す方法
    - [制約と適用範囲](limitations.md): 対応していない機能と、一部だけ対応している機能の一覧
- **Player・SDK 開発者向けガイド**
    - [ビルドガイド](development/build.md): カスタマイズ環境の構築、ネイティブのビルド手順、変更した版をゲームで使う方法、Ren'Py での確かめ方
    - [プレイヤーの構成](development/architecture.md): 層、各プラットフォームがネイティブライブラリを読み込む場所、この作りになっている理由

## 主な機能 (Key Features)

- **立ち絵が“生きる”——数値ではなく、目で見て動かせる。** 呼吸・まばたき、なびく髪や衣装、斬撃・魔法のエフェクトまで、動きは専用エディタ（SpriteStudio）でボーン階層・メッシュ変形・パーティクルを使ってビジュアルに作り込みます。ATL で各パーツの位置・回転・タイミングを数値で書いてはリロードして確かめる代わりに、キャンバス上でパーツを動かし、タイミングはタイムラインとイージングカーブで決められるので、立ち絵を描いた人がそのまま動きまで付けられます。Ren'Py はそれを再生するだけです。
- **セリフに合わせて口パク。** `SSCharacter` を 1 行書けば、画像と話者の定義がまとめて済みます。セリフの表示中は talk アニメーション、終われば待機アニメーションに自動で切り替わり、セリフごとのコードは要りません。
- **普通の画像と同じように使える。** `image` 文なしで `show ringo wait1` と書け、別のアニメーションへの切り替えも、表情を変えるときと同じ `show` 1 行です。ATL・`Transform` での配置・スライドイン・ズーム・フェードもそのまま使え、インタラクティブディレクターにも並びます。切り替えをカットではなくブレンドにしたいときは `ss_crossfade()` で次のアニメーションへクロスフェードでき、トラックを重ねれば再生中の動きにまばたきや手振りを足せます（[アニメーションの合成](usage.md#mixing-animations)）。実行時のテクスチャ差し替えやパーツ上書きで、衣装変更や表情差分も扱えます。
- **動画（ムービー）の軽量な代替に。** オープニング、動く背景、エフェクトのカットインなど、`Movie` を使っていた場面をアニメーションで置き換えます。自由に拡大縮小でき、シームレスにループし、スクリプトの進行に合わせて切り替わり、動画に焼き込まれたフレームレートではなくディスプレイのリフレッシュレートで動きます。ファイルに入っているのは絵と動きで、毎フレームの画像ではないので、どれだけ滑らかに動かしても大きさは変わりません。
- **エディタから実行画面まで、シームレスな更新。** **Auto Importer** が開発中の `SpriteStudio_Source/` を監視します。**Shift+R** を 1 回押しておけば、あとは SpriteStudio で保存するだけ。変更のあったプロジェクトだけが再コンバートされ、実行中の Ren'Py が自分でリロードして反映します（[ホットリロード](import.md#ホットリロード)）。書き出しの手作業は要りません。

## 関連リポジトリ

- [SpriteStudio Docs](https://cri-middleware.github.io/SpriteStudio-Docs/ja/) — SDK と公式 Player のドキュメントポータル。
- [SpriteStudio-SDK](https://github.com/cri-middleware/SpriteStudio-SDK) — `libssruntime` / `libssconverter` を提供する SDK 本体。
- [SSConverterGUI](https://github.com/cri-middleware/SSConverterGUI) — Player を介さず `.sspj` を変換するデスクトップ GUI。
