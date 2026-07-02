# Contributing to SSPlayerForRenPy

Thank you for your interest in contributing to SSPlayerForRenPy! We welcome all kinds of contributions, including bug reports, feature requests, documentation improvements, and code contributions.

## Table of Contents
- [Code of Conduct](#code-of-conduct)
- [How Can I Contribute?](#how-can-i-contribute)
- [Development Environment](#development-environment)
- [Coding Standards](#coding-standards)

## Code of Conduct
Please refer to [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md).

## How Can I Contribute?

### Technical Constraints & Guiding Principles
To maintain high performance and native integration with Ren'Py, please adhere to the following principles:

- **Ren'Py Idioms First:** Use Ren'Py's built-in systems (Creator-Defined Displayables, `image` declarations, Screen Language) instead of recreating them. Let Ren'Py handle the rendering and UI logic.
- **Performance in the Hot Path:** Avoid unnecessary operations during the `render` method. Use the `DrawBatch` plans emitted by the runtime directly with Ren'Py's GL2 mesh and texture rendering APIs.
- **SDK Separation:** The core playback logic resides in the `SpriteStudio-SDK` submodule (Rust). Changes to core logic should be directed to the SDK repository, while Ren'Py-specific integrations belong in `game/spritestudio/`.

### Reporting Bugs
If you find a bug, please use the provided Issue Templates. Include:
- A clear, descriptive title.
- Steps to reproduce.
- Your Ren'Py version and OS.
- Expected vs. actual behavior.

*Note: If you need to send proprietary `.sspj` projects to reproduce the bug, please do not attach them to public issues. See [SUPPORT.md](./SUPPORT.md) for how to contact us privately.*

### Pull Requests
1. Fork the repository and create your branch from `develop`.
2. Ensure your code follows the existing style and conventions.
3. Test your changes locally by running the sample projects via `scripts/run-demo.sh` or `scripts\run-demo.ps1`.
4. Submit a Pull Request targeting the `develop` branch with a clear description of the changes.

## Development Environment

### Prerequisites
- Python 3
- Rust (`rustup`) for building the core runtime

### Build the Runtime
To compile the SDK runtime, use the provided build scripts:

**macOS / Linux:**
```bash
./scripts/build-runtime.sh
```

**Windows:**
```powershell
.\scripts\build-runtime.ps1
```

Once built, you can run the demo to verify your changes.

---
By contributing to this project, you agree that your contributions will be licensed under the project's [LICENSE.md](./LICENSE.md).

<br>
<br>

---

# SSPlayerForRenPy への貢献について

SSPlayerForRenPy にご関心をお寄せいただき、ありがとうございます！ バグ報告、機能提案、ドキュメントの改善、コードの提供など、あらゆる形での貢献を歓迎します。

## 目次
- [行動規範](#行動規範-1)
- [貢献する方法](#貢献する方法-1)
- [開発環境のセットアップ](#開発環境のセットアップ-1)
- [コーディング規約](#コーディング規約-1)

## 行動規範
[CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md) を参照してください。

## 貢献する方法

### 技術的制約と設計原則
Ren'Pyとのネイティブな統合と高いパフォーマンスを維持するため、以下の原則に従ってください。

- **Ren'Pyのパラダイムを優先:** `image` 宣言や Screen 言語、Creator-Defined Displayable (CDD) など、Ren'Pyの標準的な機能を積極的に活用してください。独自の実装を行うよりもRen'Pyの設計に委ねることを優先します。
- **再生パスのパフォーマンス:** `render` メソッド等の描画ループ中での不要な処理は避けてください。Rustランタイムから提供される描画バッチ情報を直接Ren'PyのGL2描画APIに渡すように実装されています。
- **SDKの分離:** コアのアニメーション計算ロジックは `SpriteStudio-SDK` サブモジュール(Rust)に存在します。アルゴリズムやコアロジックの修正はSDK側のリポジトリへ、Ren'Py特有の実装は `game/spritestudio/` へ行ってください。

### バグの報告
バグを発見した場合は、Issue テンプレートを使用して以下の情報を含めてください：
- 簡潔で分かりやすいタイトル
- 再現手順
- 利用している Ren'Py のバージョンとOS
- 期待される動作と実際の動作

*注: バグ再現のために非公開の `.sspj` プロジェクトデータ等を提供いただける場合は、公開 Issue には添付せず、[SUPPORT.md](./SUPPORT.md) に記載のヘルプセンターをご利用ください。*

### プルリクエスト
1. リポジトリをフォークし、`develop` ブランチから作業用ブランチを作成してください。
2. 既存の規約に従ってコードを記述してください。
3. デモプロジェクトを実行し、動作確認を行ってください。
4. `develop` ブランチに向けて、変更内容を明確に記載したプルリクエストを送信してください。

## 開発環境のセットアップ

### 前提条件
- Python 3
- RustランタイムをビルドするためのRust環境 (`rustup`)

### ビルド方法
提供されているスクリプトを使用して、SDKからRustランタイムをビルドします。

**macOS / Linux:**
```bash
./scripts/build-runtime.sh
```

**Windows:**
```powershell
.\scripts\build-runtime.ps1
```

ビルド完了後、デモプロジェクトを起動して変更内容をテストしてください。

---
本プロジェクトへの貢献は、プロジェクトの [LICENSE.md](./LICENSE.md) に同意したものとみなされます。
