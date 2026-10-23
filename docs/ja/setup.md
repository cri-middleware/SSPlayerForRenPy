# 🚀 導入ガイド (Setup Guide)

本ドキュメントは、「**利用者**」向けの手順です。パッケージをそのままご自身のゲームプロジェクトに導入する手順を解説します。カスタマイズを行いたい方は [ビルド・カスタマイズガイド (build.md)](build.md) をご参照ください。

## 1. 必要環境
- **Ren'Py**: バージョン 8.x 系 (Python 3 ベース) が必要です。

## 2. ライブラリの配置
最新パッケージ — [`SSPlayerForRenPy.zip`](https://github.com/cri-middleware/SSPlayerForRenPy/releases/latest/download/SSPlayerForRenPy.zip)（恒久リンク・常に最新リリース。特定バージョンは [GitHub Releases](https://github.com/cri-middleware/SSPlayerForRenPy/releases) から）— をダウンロードして展開し、中にある **`spritestudio/`** フォルダを、ご自身のプロジェクトの `game/` ディレクトリ内にそのままコピーしてください。

> **内部構成**: このフォルダにはPythonスクリプト（`spritestudio.rpy` 等）と、各プラットフォーム向けのネイティブライブラリ（Windows / macOS / Linux、Android、iOS、Web）がすべて含まれています。同じリリースのこのドキュメント（英語の Markdown。`README.md` と `docs/`）も入っていて、オフラインで読めます。ビルドしたゲームからは、`spritestudio.rpy` がドキュメントを除外します。

## 3. 再生データ (`.ssab`) の配置
SpriteStudio で作成したアニメーションプロジェクト (`.sspj`) は、どの SpriteStudio Player でも共通のランタイム形式 `.ssab` にして再生します。

`game/` と同じ階層の `SpriteStudio_Source/` にプロジェクトを置き、Ren'Py ランチャーで **プロジェクトの起動** を押すと、ゲームが始まる前に Auto Importer が `game/ss_assets/<プロジェクト名>/` へ変換します。

Ren'Py を起動せずに変換するには、**SSConverter GUI**（プロジェクトをドロップして変換するデスクトップアプリ）、**`ssconverter-cli`**（バッチスクリプトや CI 向け）、**`ssconverter-web`**（ブラウザ上で、インストール不要）を使います。

詳しくは **[アニメーションデータのコンバート (import.md)](import.md)** をご参照ください。

これで導入は完了です。実際の呼び出し方については [usage.md](usage.md) をご参照ください。

## 4. アップデートとアンインストール

**アップデートでは `game/spritestudio/` フォルダを丸ごと入れ替えます。既存のフォルダを削除してから、新しいフォルダを配置してください。**

Ren'Py は `.rpy` を同じ場所の `.rpyc` にコンパイルし、`.rpy` が無くなった後もその `.rpyc` を実行し続けます。先に古いフォルダを削除すると、新しいバージョンのスクリプトとライブラリだけが残ります。

1. プロジェクトから `game/spritestudio/` を削除します。
2. 新しい `SSPlayerForRenPy.zip` を展開し、中の `spritestudio/` フォルダを `game/` にコピーします。
3. 開発者モードでゲームを起動し、起動時のログ行（またはコンソール **Shift+O** から `ss_diagnostics()`）で読み込みを確認します。詳しくは [再生と制御](usage.md) をご覧ください。

この操作でご自身のデータが失われることはありません。コンバート済みの `.ssab` データ（例: `game/ss_assets/`）や `SpriteStudio_Source/` のプロジェクトは、このフォルダの外にあります。

**アンインストール**する場合は `game/spritestudio/` を削除してください。パッケージング設定はフォルダ自身が持っているため、フォルダ内に残るものはありません。ご自身で追加したもの — `options.rpy` の `.ssab` 分類設定（[ゲームの書き出し](export.md) 参照）、コンバート済みデータ、`SSPlayer(...)` の呼び出し — はそのまま残るので、不要になった時点で削除してください。
