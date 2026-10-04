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

- **Ren'Py Idioms First:** Use Ren'Py's built-in systems (Creator-Defined Displayables, `image` declarations, Screen Language) instead of recreating them. Let Ren'Py handle the rendering and UI logic: placement and scaling belong to `Transform` / ATL and the `at` clause, volume to the mixers, and persistence to the pickled displayable — do not rebuild them behind an `ss_*` method.
- **Performance in the Hot Path:** Avoid unnecessary operations during the `render` method. Use the `DrawBatch` plans emitted by the runtime directly with Ren'Py's GL2 mesh and texture rendering APIs.
- **Stay Droppable:** Everything ships as `game/spritestudio/`, pasted into a stock project with no build step, so a feature must work without `scripts/`, `tools/` or the SDK checkout — and each sibling `.rpy` must stay independently removable.
- **Ren'Py Naming:** The public API is `ss_`-prefixed `snake_case` on the displayable, and callbacks are constructor arguments (`on_animation_finished`, …), the way Ren'Py itself takes them. Names read as idiomatic Ren'Py rather than mirroring another port's spelling.
- **SDK Separation:** The core playback logic resides in the `SpriteStudio-SDK` submodule (Rust). Changes to core logic should be directed to the SDK repository, while Ren'Py-specific integrations belong in `game/spritestudio/`.

### Reporting Bugs
If you find a bug, please open a [GitHub Issue](https://github.com/cri-middleware/SSPlayerForRenPy/issues). Include:
- A clear, descriptive title.
- Steps to reproduce.
- Your Ren'Py version and OS.
- Expected vs. actual behavior.

*Note: If you need to send proprietary `.sspj` projects to reproduce the bug, please do not attach them to public issues. See [SUPPORT.md](./SUPPORT.md) for how to contact us privately.*

### Pull Requests
1. Fork the repository and create your branch from `develop`.
2. Ensure your code follows the existing style and conventions.
3. Run the headless test suite: `scripts/run-tests.sh` (`scripts\run-tests.ps1` on Windows).
   It needs the runtime and the example data — see Development Environment below.
4. Test your changes on screen by running the sample projects via `scripts/run-demo.sh` or `scripts\run-demo.ps1`.
   Rendering is not covered by the suite and has to be signed off this way.
5. Submit a Pull Request targeting the `develop` branch with a clear description of the changes.

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

Once built, deploy the example assets and run the demo:

```bash
./scripts/download-sdk.sh        # or build-runtime.sh, above
./scripts/deploy-examples.sh     # game/ss_assets/
./scripts/run-demo.sh
```

Every script is `scripts/*.sh` with a `.ps1` twin, except `deploy-ios.sh` and `fetch-renpy-ios.sh`, which need macOS and Xcode anyway. All take `key=value` options and `--help`.

### Test
```bash
./scripts/run-tests.sh           # only=mask,events / skip= / list=yes / verbose=yes
```
Every engine-independent layer has a headless check in `tools/`, in plain CPython: the playback core and events, geometry and mesh and PartColor, instance and effect and shape and slot stepping, masks, part overrides and shaders, the `.ssab` identifier gate and the resolver, the auto importer's output plan and freshness marker, and the test doubles themselves.

**Run them through the runner, never as a bare loop over the tools.** Both prerequisites are gitignored, so a fresh clone has neither — `game/spritestudio/libs/` and `game/ss_assets/` — and a tool that cannot find its pack prints `SKIP` and **exits 0**. The runner checks both up front, refuses to start a partial suite, and treats a surviving `SKIP` as a failure; sub-case skips are counted beside the passes. Nothing runs the suite on a pull request, so this is the gate: run it after touching anything under `game/spritestudio/python/`. Renaming a property on `SSInternalPlayer` is the case to watch — no compiler catches the call sites, so it surfaces only as an `AttributeError` from whichever tool still reads the old name. Lint from the repository root with `renpy-sdk/renpy.sh . lint`; `scripts/fetch-renpy-sdk.sh` (`.ps1` on Windows) fetches `renpy-sdk/` first.

**GL2 rendering has no headless check** (PMA, mesh, blend, mask, the `ss-*` GLSL) — sign it off in a GUI run, via `Shift+B` or `run-demo`.

Outside the suite: `tools/analyze.py` (DrawBatchKind audit), `cli_convert.py` (shell `.sspj` → `.ssab`), `ss_stamp_import.py` (stamp the auto-importer marker over an out-of-band pack), and `render_png.py` / `render_mask_png.py` (software raster, not GL2 — the only two needing Pillow).

### Documentation
`docs/` is bilingual and ordered `setup → import → usage → export`, plus `build` and `limitations`; `limitations.md` is the canonical supported / unsupported list. Every page exists as both `docs/en/<path>` and `docs/ja/<path>`, each locale owning its own `assets/`, with source-relative asset paths **including inside raw `<video>` / `<img>` HTML**. Keep `docs/` user-facing: never cite a dev script there. If you edit a page, build both locales before you finish: nothing builds the docs on a pull request, so that local build is the only gate.

```bash
scripts/prepare-docs.sh              # once: .venv + the pins in docs/requirements.txt
scripts/build-docs.sh                # English then Japanese, both --strict
scripts/build-pages.sh serve=yes     # + the released Web demo -> http://localhost:8000/
```

Both locales, English first: it clears `site/`, which contains `site/ja`, so an English-only build leaves no Japanese site at all. `mkdocs.base.yml` sets `strict: true`; `serve` validates nothing.

`build-pages.sh` is the whole published site, and `pages.yml`'s build job **is** this script. `demo=download` needs `gh` and a Release carrying `SSPlayerForRenPy-web-demo.zip`; `zip=<path>` feeds one by hand, and `demo=build` runs the export here instead, for when no Release carries one. `sdk=` picks `download-sdk` or `build-runtime` and is consulted for `demo=build` only, since a downloaded demo brings its own runtime. An existing `renpy-sdk/` is never re-fetched.

`game/options.rpy` excludes `site/**`: the docs build copies the screencasts into `site/*/assets/`, and Ren'Py would otherwise classify every `**.webm` into every package.

## Coding Standards

### Python Guidelines
- Follow [PEP 8](https://peps.python.org/pep-0008/) naming and the existing style of the files you touch.
- Every module under `game/spritestudio/python/` must import in plain CPython, with no `renpy` — the headless suite runs them that way.
- Handle the Rust FFI objects safely: release every handle with its destroy function (`ss_runtime_destroy`, `ss_resource_destroy`, `ss_converter_destroy`). The bindings do it in `close()` and `__del__`, so put a new handle on the same path. Textures are the exception — Ren'Py owns them.
- Do not hand-edit `game/spritestudio/python/ss/`; regenerate it with `scripts/generate-fbs-code.sh` and commit. `game/spritestudio/python/flatbuffers/` is the vendored FlatBuffers runtime from `scripts/download-flatbuffers.sh` — leave it as downloaded.

---
By contributing to this project, you agree that your contributions will be licensed under the project's [LICENSE.md](./LICENSE.md).

<br>
<br>

---

# SSPlayerForRenPy への貢献について

SSPlayerForRenPy にご関心をお寄せいただき、ありがとうございます！ バグ報告、機能提案、ドキュメントの改善、コードの提供など、あらゆる形での貢献を歓迎します。

## 目次
- [行動規範](#行動規範)
- [貢献する方法](#貢献する方法)
- [開発環境のセットアップ](#開発環境のセットアップ)
- [コーディング規約](#コーディング規約)

## 行動規範
[CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md) を参照してください。

## 貢献する方法

### 技術的制約と設計原則
Ren'Pyとのネイティブな統合と高いパフォーマンスを維持するため、以下の原則に従ってください。

- **Ren'Pyのパラダイムを優先:** `image` 宣言や Screen 言語、Creator-Defined Displayable (CDD) など、Ren'Pyの標準的な機能を積極的に活用してください。独自の実装を行うよりもRen'Pyの設計に委ねることを優先します。配置と拡大縮小は `Transform` / ATL と `at` 節、音量はミキサー、永続化は pickle される Displayable の役割です。これらを `ss_*` メソッドの裏で作り直さないでください。
- **再生パスのパフォーマンス:** `render` メソッド等の描画ループ中での不要な処理は避けてください。Rustランタイムから提供される描画バッチ情報を直接Ren'PyのGL2描画APIに渡すように実装されています。
- **ドロップインのまま保つ:** すべては `game/spritestudio/` として配布され、ビルド手順なしで標準のプロジェクトに貼り付けて使います。そのため機能は `scripts/`・`tools/`・SDK のチェックアウトなしで動く必要があり、同じフォルダの各 `.rpy` は個別に取り外せる状態を保ってください。
- **Ren'Py の命名規則:** 公開 API は Displayable 上の `ss_` 接頭辞付き `snake_case` で、コールバックは Ren'Py 自身と同じくコンストラクタ引数（`on_animation_finished` など）で受け取ります。他の Player の綴りを写すのではなく、Ren'Py として自然な名前にしてください。
- **SDKの分離:** コアのアニメーション計算ロジックは `SpriteStudio-SDK` サブモジュール(Rust)に存在します。アルゴリズムやコアロジックの修正はSDK側のリポジトリへ、Ren'Py特有の実装は `game/spritestudio/` へ行ってください。

### バグの報告
バグを発見した場合は、[GitHub Issues](https://github.com/cri-middleware/SSPlayerForRenPy/issues) に以下の情報を含めて投稿してください：
- 簡潔で分かりやすいタイトル
- 再現手順
- 利用している Ren'Py のバージョンとOS
- 期待される動作と実際の動作

*注: バグ再現のために非公開の `.sspj` プロジェクトデータ等を提供いただける場合は、公開 Issue には添付せず、[SUPPORT.md](./SUPPORT.md) に記載のヘルプセンターをご利用ください。*

### プルリクエスト
1. リポジトリをフォークし、`develop` ブランチから作業用ブランチを作成してください。
2. 既存の規約に従ってコードを記述してください。
3. ヘッドレステストを実行してください: `scripts/run-tests.sh`（Windows は `scripts\run-tests.ps1`）。実行にはランタイムとサンプルデータが必要です（後述の「開発環境のセットアップ」を参照）。
4. `scripts/run-demo.sh`（Windows は `scripts\run-demo.ps1`）でデモプロジェクトを実行し、画面上での動作確認を行ってください。描画はテストの対象外のため、この確認でしか担保できません。
5. `develop` ブランチに向けて、変更内容を明確に記載したプルリクエストを送信してください。

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

ビルドしたら、サンプルアセットを配置してデモを実行してください。

```bash
./scripts/download-sdk.sh        # または上記の build-runtime.sh
./scripts/deploy-examples.sh     # game/ss_assets/
./scripts/run-demo.sh
```

スクリプトはすべて `scripts/*.sh` と `.ps1` の双子です。ただし `deploy-ios.sh` と `fetch-renpy-ios.sh` はどのみち macOS と Xcode が必要なので `.sh` だけです。いずれも `key=value` オプションと `--help` を取ります。

### テスト
```bash
./scripts/run-tests.sh           # only=mask,events / skip= / list=yes / verbose=yes
```
エンジン非依存の各層には、素の CPython で動くヘッドレスチェックが `tools/` にあります（再生コア・イベント、ジオメトリ / メッシュ / PartColor、インスタンス・エフェクト・シェイプ・スロット送り、マスク、パートオーバーライドとシェーダー、`.ssab` 識別子ゲートとリゾルバ、自動インポーターの出力先の割り当てと鮮度マーカー、そしてテストダブル自身）。

**必ずランナー経由で実行してください。ツールを素でループさせてはいけません。** 前提となる `game/spritestudio/libs/` と `game/ss_assets/` はどちらも git 管理外で、クリーンなクローンには存在しません。パックを見つけられなかったツールは `SKIP` と表示して **exit 0** します。ランナーは両方を先に確認し、欠けていれば部分実行を拒否し、それでも残った `SKIP` は失敗として扱います（サブケースのスキップは PASS と並べて数えます）。プルリクエストではスイートは走らないので、`game/spritestudio/python/` 配下を触ったらこれがゲートです。特に注意すべきは `SSInternalPlayer` のプロパティ改名で、呼び出し側を検出するコンパイラが無いため、古い名前を読んでいるツールの `AttributeError` としてしか現れません。lint はリポジトリのルートで `renpy-sdk/renpy.sh . lint` を実行します。`renpy-sdk/` は先に `scripts/fetch-renpy-sdk.sh`（Windows は `.ps1`）で取得してください。

**GL2 の描画にはヘッドレスチェックがありません**（PMA、メッシュ、ブレンド、マスク、`ss-*` の GLSL）。`Shift+B` か `run-demo` の GUI 実行で確認してください。

スイートの外にあるもの: `tools/analyze.py`（DrawBatchKind の監査）、`cli_convert.py`（シェルからの `.sspj` → `.ssab` 変換）、`ss_stamp_import.py`（別経路で作ったパックに自動インポーターのマーカーを付ける）、`render_png.py` / `render_mask_png.py`（GL2 ではなくソフトウェアラスタ。Pillow が必要なのはこの 2 つだけ）。

### ドキュメント
`docs/` は日英 2 言語で、`setup → import → usage → export`（＋ `build` と `limitations`）の順です。`limitations.md` が対応・非対応の正典一覧です。ページは `docs/en/<path>` と `docs/ja/<path>` の両方に存在し、`assets/` もロケールごとに持ち、アセットのパスはソース相対です（**生の `<video>` / `<img>` HTML の中でも同じ**）。`docs/` は利用者向けに保ち、開発用スクリプトを引用しないでください。ページを編集したら、仕上げる前に両ロケールをビルドしてください。プルリクエストでは docs はビルドされないため、手元のビルドが唯一のゲートです。

```bash
scripts/prepare-docs.sh              # 一度だけ: .venv と docs/requirements.txt のピン
scripts/build-docs.sh                # 英語 → 日本語の順に、どちらも --strict
scripts/build-pages.sh serve=yes     # + リリース済み Web デモ -> http://localhost:8000/
```

必ず両ロケールを、英語を先にビルドします。英語ビルドは `site/ja` を含む `site/` を消すため、英語だけビルドすると日本語サイトは残らず消えます。`mkdocs.base.yml` が `strict: true` を設定します。`serve` は何も検証しません。

`build-pages.sh` が公開サイト全体で、`pages.yml` のビルドジョブは**このスクリプト**です。`demo=download` には `gh` と、`SSPlayerForRenPy-web-demo.zip` を持つ Release が必要です。`zip=<path>` で手渡しもでき、`demo=build` はここでエクスポートを実行します（それを持つ Release が無いときに使います）。`sdk=` は `download-sdk` と `build-runtime` の選択で、参照されるのは `demo=build` のときだけです（ダウンロードしたデモは自前のランタイムを持っているため）。既存の `renpy-sdk/` は再取得しません。

`game/options.rpy` は `site/**` を除外しています。docs のビルドがスクリーンキャストを `site/*/assets/` に複製するため、除外しないと Ren'Py が `**.webm` をすべてのパッケージに分類します。

## コーディング規約

### Python のガイドライン
- [PEP 8](https://peps.python.org/pep-0008/) の命名と、触るファイルの既存のスタイルに従ってください。
- `game/spritestudio/python/` 配下のモジュールは、`renpy` の無い素の CPython で import できるようにしてください。ヘッドレスのスイートはその状態で実行します。
- Rust FFI オブジェクトの安全な取り扱いに注意してください。ハンドルは必ず対応する destroy 関数（`ss_runtime_destroy`、`ss_resource_destroy`、`ss_converter_destroy`）で解放します。バインディングは `close()` と `__del__` で解放しているので、新しいハンドルも同じ経路に乗せてください。テクスチャは Ren'Py が所有するので例外です。
- `game/spritestudio/python/ss/` は手で編集せず、`scripts/generate-fbs-code.sh` で生成し直してコミットしてください。`game/spritestudio/python/flatbuffers/` は `scripts/download-flatbuffers.sh` で取得して同梱している FlatBuffers ランタイムなので、取得したまま手を加えないでください。

---
本プロジェクトに貢献することで、あなたの貢献がプロジェクトの [LICENSE.md](./LICENSE.md) の下でライセンスされることに同意したものとみなされます。
