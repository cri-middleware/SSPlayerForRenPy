# 🎭 SpriteStudio Player for Ren'Py

[OPTPiX SpriteStudio 7](https://www.webtech.co.jp/spritestudio/) で作成したアニメーションを [Ren'Py](https://www.renpy.org/) 上で再生するためのプラグイン（プレイヤー）です。再生処理は [SpriteStudio-SDK](https://github.com/cri-middleware/SpriteStudio-SDK) が提供する `libssruntime` を介して行います。

!!! tip "ブラウザで試す"
    サンプルプロジェクトを Ren'Py Web でビルドしたデモを、本ドキュメントと同じサイトの
    `https://cri-middleware.github.io/SSPlayerForRenPy/demo/` で公開します。インストールは不要です。
    _準備中_: デモは最初のリリースと同時に公開されるため、それまでは 404 になります。

## 目次

本ドキュメントは、目的別に以下の構成となっています。

- **利用者向けガイド**
    - [導入ガイド (Setup)](setup.md): ゲームプロジェクトへの組み込み方法
    - [データのコンバート (Import)](import.md): `.sspj` アニメーションデータの変換方法
    - [再生と制御 (Usage)](usage.md): Ren'Pyスクリプトからの呼び出し方・制御方法
    - [ゲームのエクスポート (Export)](export.md): 標準の Ren'Py ツールで各プラットフォーム（デスクトップ / モバイル / Web）へ書き出す方法
- **開発者向けガイド**
    - [ビルド・カスタマイズガイド (Build)](build.md): カスタマイズ環境の構築とネイティブのビルド手順
    - [仕様と制約事項 (Limitations)](limitations.md): 対応状況・未サポート機能の一覧

## 主な機能 (Key Features)

本プレイヤーは、Ren'Py エンジン上で SpriteStudio の表現力をフルに引き出すために設計されています。

*   **複雑な ATL を排除:** Ren'Py 側で長大な ATL (Animation and Transformation Language) を書く必要はありません。エディタで作成したモーションをそのまま数行のスクリプトで再生できます。
*   **完全な機能サポート:** ボーン階層、メッシュ＆デフォーム、パーティクルエフェクトなど、SpriteStudio 7 の高度なアニメーション機能を標準でサポートします。
*   **高速なネイティブ処理:** バックエンドの `libssruntime` (Rust) による最適化と、Ren'Py のレンダリングパイプラインを活かした設計により、動画ファイルに頼らず軽量・高速に描画します。
*   **透過とブレンドのサポート:** シームレスなフェードや、エフェクトの加算合成など、ビジュアルノベルに欠かせないリッチな画面演出が可能です。

## 関連リポジトリ

- [SpriteStudio-SDK](https://github.com/cri-middleware/SpriteStudio-SDK) — `libssruntime` / `libssconverter` を提供する SDK 本体
- [SSConverterGUI](https://github.com/cri-middleware/SSConverterGUI) — 手動でのアセット変換に便利な専用GUIアプリ
