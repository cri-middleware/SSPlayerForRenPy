<!--
Thanks for contributing! See CONTRIBUTING.md for the constraints this project works under
(Ren'Py idioms first, a lean render path, core logic in the SDK).
CONTRIBUTING.md に本プロジェクトの制約が記載されています。日本語でも英語でも構いません。
-->

## What does this change? / 変更内容

<!-- What it does and why. Link any related issue: Fixes #123 -->

## How was it verified? / 検証方法

<!--
Which checks ran, and on what. If you could not run them, say so —
that is useful information, not a problem.
実行した確認と環境。実行できなかった場合はその旨をお書きください。
-->

- [ ] `scripts/run-tests.sh` — a SKIP that survives the run counts as a failure
- [ ] `renpy-sdk/renpy.sh . lint` from the repository root (`scripts/fetch-renpy-sdk.sh` first)
- [ ] `scripts/run-demo.sh` — checked drawing in the demo; GL2 rendering has no headless check
- [ ] Not run — see notes below / 未実行（理由は下記）

**Environment / 環境:** Ren'Py version, OS, platform

## Checklist

- [ ] Scoped to one thing. Unrelated fixes are easier to review as their own PR.
- [ ] Follows the style of the files it touches.
- [ ] Docs updated if behaviour changed.
- [ ] Anything that exists twice changed twice — a page and its translation, a `.sh` and its `.ps1`.
- [ ] `render` does no unnecessary work and uses the runtime's `DrawBatch` plans directly.
- [ ] Core logic goes to SpriteStudio-SDK, and nothing is committed inside the submodule.
- [ ] `docs/` stays user-facing: it never cites a development script.

## Anything reviewers should know? / レビュー時の注意点

<!-- Trade-offs you made, alternatives you rejected, parts you are unsure about. -->
