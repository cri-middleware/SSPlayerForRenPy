# アニメーションデータのコンバート (Import)

SpriteStudio Player for Ren'Py では、SpriteStudio のプロジェクトファイル (`.sspj`) を Ren'Py 用のバイナリ形式 (`.ssab`) に変換して利用します。プロジェクトの規模やワークフローに合わせて、2つのコンバート方法を提供しています。

---

## 方法1: 自動インポート機能 (Auto Importer)
Ren'Pyの起動時に `.sspj` ファイルの更新を自動で検知し、裏側でコンバートを実行してゲーム内に取り込む機能です。**手動コンバートの手間を省き、素早くイテレーション（調整・確認）を回したい場合**におすすめです。

※この機能は **Ren'Pyが開発者モード (`config.developer = True`) で起動した場合のみ** 動作します。リリースビルドでは動作しません。

### 基本的な使い方
1. ゲームプロジェクトのルートディレクトリ（`game/` フォルダと同じ階層）に **`SpriteStudio_Source`** という名前のフォルダを作成します。
2. 作成した `SpriteStudio_Source` フォルダの中に、SpriteStudioで作成したプロジェクト一式（`.sspj`, `.ssae`, 画像など）を配置します。
3. Ren'Pyのプロジェクトを起動、またはリロード（`Shift + R`）します。

**実行結果:**
起動時の初期化フェーズでファイルの更新が検知されると自動的にコンバートが走り、プロジェクト名と同名のフォルダが **`game/ss_assets/`** 以下に生成されます。
（例: `SpriteStudio_Source/Hero/Hero.sspj` を配置した場合、`game/ss_assets/Hero/` に変換データが出力されます）

### 出力パスのカスタマイズ
ソースとなる配置場所や出力先パスを変更したい場合は、Ren'Pyスクリプト側で変数を定義して上書きできます。

```renpy
# 例: options.rpy 等でオートインポーター（init -10）より先に定義する
define -15 ss_source_dir = "my_custom_source_folder"
define -15 ss_output_dir = "game/my_converted_assets"
```

---

## 方法2: CLIコンバータ (`ssconverter-cli`) による手動 / バッチ処理
CI（継続的インテグレーション）での自動ビルドや、大規模プロジェクトで一括バッチ処理を行いたい場合は、独立した実行ツールである **`ssconverter-cli`** の利用がおすすめです。**Python等の実行環境が不要**で、コマンドラインから直接コンバート処理を行えます。

### ダウンロード方法
[SpriteStudio-SDK の Releases ページ](https://github.com/cri-middleware/SpriteStudio-SDK/releases) から、お使いのOSに合った `ssconverter-cli` の実行可能ファイル（Windows向けは `ssconverter-cli.exe` 等が含まれたZIP）をダウンロードし、任意のフォルダに展開してください。

### 基本的な使い方
ターミナル（コマンドプロンプトやバッチファイル）から以下のコマンドを実行します。`-o` オプションを使わずに入力ファイルのみを指定するのが最も簡単です。

```bash
# 基本構文
ssconverter-cli <入力ファイルパス.sspj>

# 実行例
ssconverter-cli SpriteStudio_Source/Hero/Hero.sspj
```

- 上記を実行すると、`.sspj` ファイルと同じディレクトリ内にプロジェクトと同名のフォルダ（例: `Hero/`）が生成され、その中に `.ssab` や画像ファイルが出力されます。
- コンバート完了後、生成されたフォルダをご自身のRen'Pyプロジェクトの `game/` ディレクトリ内（例: `game/ss_assets/Hero/`）に手動で移動・配置してください。
- ※任意の場所へ直接出力したい場合は、`-o <出力先ディレクトリパス>` オプションを使用することも可能です。

### ディレクトリ指定による一括バッチ処理
ファイル単位ではなくディレクトリのパスを指定することで、そのディレクトリ内にあるすべての `.sspj` プロジェクトを自動的に探し出して一括コンバートしてくれます。

```bash
# 指定フォルダ以下の全プロジェクトを一括コンバート
ssconverter-cli SpriteStudio_Source/
```
複数のキャラクターやシーンのアニメーションデータを一気に変換・更新したい場合に非常に便利です。

