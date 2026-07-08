# 導入ガイド (Setup Guide)

本ドキュメントは、「**利用者**」向けの手順です。パッケージをそのままご自身のゲームプロジェクトに導入する手順を解説します。
カスタマイズを行いたい方は [ビルド・カスタマイズガイド (build.md)](build.md) をご参照ください。

## 1. 必要環境
- **Ren'Py**: バージョン 8.x 系 (Python 3 ベース) が必要です。

## 2. ライブラリの配置
最新パッケージ — [`SSPlayerForRenPy.zip`](https://github.com/cri-middleware/SSPlayerForRenPy/releases/latest/download/SSPlayerForRenPy.zip)（恒久リンク・常に最新リリース。特定バージョンは [GitHub Releases](https://github.com/cri-middleware/SSPlayerForRenPy/releases) から）— をダウンロードして展開し、中にある **`spritestudio/`** フォルダを、ご自身のプロジェクトの `game/` ディレクトリ内にそのままコピーしてください。

> **内部構成**: このフォルダにはPythonスクリプト（`spritestudio.rpy` 等）と、各OS向けのネイティブライブラリ(Windows / macOS / Linux)がすべて含まれています。

## 3. 再生データ (`.ssab`) の配置
SpriteStudio で作成したアニメーションプロジェクト (`.sspj`) は、Ren'Py向けにコンバートしたデータ (`.ssab`) として配置する必要があります。

コンバート方法には以下の2通りがあります。プロジェクトの開発スタイルに合わせて選んでください。
- **自動インポート (Auto Importer):** Ren'Py起動時に自動コンバートする手軽な方法
- **CLIコンバート:** 外部バッチスクリプトやCI等で一括変換する方法

詳しくは **[アニメーションデータのコンバート (import.md)](import.md)** をご参照ください。

これで導入は完了です。実際の呼び出し方については [usage.md](usage.md) をご参照ください。
