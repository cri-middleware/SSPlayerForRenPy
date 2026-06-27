# SSPlayer for Ren'Py

**SpriteStudio 7** のアニメーション (`.ssab`) を [Ren'Py](https://www.renpy.org/) で再生するための拡張ライブラリ（プレイヤー）です。

## 📚 ドキュメント (Documentation)
目的別の詳細な手順や仕様については、以下のドキュメントをご参照ください。
- **[導入ガイド (Setup)](docs/setup.md)**: ゲームプロジェクトへの組み込み方法
- **[再生と制御 (Usage)](docs/usage.md)**: Ren'Pyスクリプトからの呼び出し方
- **[ビルドガイド (Build)](docs/build.md)**: ネイティブライブラリのコンパイルと開発環境
- **[仕様と制約事項 (Limitations)](docs/limitations.md)**: 対応状況・未サポート機能の一覧

---

## 🎮 1. ただ利用したいユーザー向け (Quick Start)
本リポジトリ内の **`game/spritestudio/`** フォルダをご自身のRen'Pyプロジェクトの `game/` フォルダ内にそのままコピーしてください。これだけで導入は完了です。

```renpy
# ゲームプロジェクト内で呼び出す例
screen demo():
    add SpriteStudioDisplayable("Basic.ssab", sprites_subdir="sprites") xalign 0.5 yalign 0.5
```
※詳しくは [導入ガイド](docs/setup.md) および [再生と制御](docs/usage.md) をご覧ください。

## 🛠 2. カスタマイズ・ビルドしたいユーザー向け
デモを動かしたり、Cのライブラリを自分でビルドする方向けの手順です。事前に Rust ツールチェーン (`cargo`) が必要です。

```bash
git submodule update --init --recursive

# ネイティブランタイムのビルド (macOS/Linux)
scripts/build-runtime.sh

# デモ用再生データのコンバート
scripts/deploy-examples.sh
```
※詳細は [ビルドガイド](docs/build.md) をご覧ください。

## ⚙️ 3. SDK開発者・コントリビューター向け
アニメーション計算のコア部分はRust製サブモジュール (`SpriteStudio-SDK`) が担い、Ren'Py側 ("Body") とは `ctypes` を介して連携します。
- `tools/` フォルダ内のPythonスクリプトを利用することで、Ren'Pyを起動せずにヘッドレスでの動作検証が可能です。
- 仕様の詳細や正しい実装方法については、**必ず `SpriteStudio-SDK/libs/ssruntime/docs/` にあるPlayer移植ドキュメント（ポーティングガイド）を参照**してください。
