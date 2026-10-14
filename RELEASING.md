# Releasing SpriteStudio Player for Ren'Py

Maintainers only. Contributors do not run any of this — see [CONTRIBUTING.md](./CONTRIBUTING.md).

## Cutting a release

Anyone with the Write role on this repository can cut a release: every step is a branch, a pull request, a tag, a workflow run or a Release, so nothing depends on whose machine runs it beyond the GUI run that signs off rendering. You need `git`, `gh` 2.87 or later (run `gh auth login` once) and Python 3, plus `flatc` when the SDK's schema changed. The repository needs GitHub Pages enabled with GitHub Actions as its source, and a `v*` tag rule on its `github-pages` environment, or publishing a Release deploys nothing; both are settings a repository admin makes. The commands are bash: in zsh, run `setopt interactive_comments` first, so that the `#` comments are not taken as arguments; on Windows, use Git Bash. Steps 1, 4 and 7 switch branches, so run them in a checkout of their own — a clone, or one made with `git worktree add` — not in one where other work is going on.

A release is a tag on `main`, pushed first and built second. The version is written in one place, `__version__` in `game/spritestudio/python/ss_renpy/__init__.py`, in PEP 440 form — `7.0.0b1`, `7.0.0rc1`, `7.0.0`, never a `-`. `scripts/release-version.sh` prints it, the tag is `v` followed by it, and the release build refuses a tag that disagrees. It ships inside the folder creators drop into their game, which is why it, and not `scripts/SDK_VERSION.txt`, names the release. Branches follow git-flow: `develop` integrates, `main` holds released commits only, and `release/X.Y` lives for one release — cut from `develop` when the release ships `develop`'s work, or from the line's latest tag when it ships only fixes on top of it, and deleted once the release is out.

Every block runs as written in a new shell: it works out what it needs from the checkout, git and GitHub. Two values are set by hand, each written as a placeholder to fill in: `<version>`, the version being released, as in `7.0.1`, in steps 1 and 2, and `<sdk-tag>`, the SpriteStudio-SDK release it ships, as in `v7.0.0`, in step 2. Left as it is, a placeholder stops its line with a syntax error. A value that would not stop a command by itself when empty is read as `${VAR:?}`: an empty `BRANCH` in step 3 would dispatch the QA build from `develop`, and an empty `TAG` in step 6 would watch the newest Pages run, whichever tag it built.

An agent can run every block. A person sorts the scan's matches in step 3 and signs off the rendering there, which is judged by eye, and decides two steps: the merge in step 4, which puts the release on `main`, and step 6, which publishes it for good.

### 1. Branch

A release that ships `develop`'s work is cut from `develop`: a new `X.Y`, or `7.0.0` after `7.0.0b1`. A patch release ships only fixes: it is cut from the line's latest tag, and its fixes are committed or cherry-picked onto it. Either way, an earlier `release/X.Y` that is still there is replaced. Run the block that fits.

For `develop`'s work:

```bash
VERSION=<version>
BRANCH=release/$(echo "${VERSION:?}" | cut -d. -f1,2)
git fetch origin
git switch -C "$BRANCH" origin/develop
```

For a patch:

```bash
VERSION=<version>
BRANCH=release/$(echo "${VERSION:?}" | cut -d. -f1,2)
git fetch origin --tags
BASE=$(git -c versionsort.suffix=a -c versionsort.suffix=b -c versionsort.suffix=rc tag --list "v${BRANCH#release/}.*" --sort=-v:refname | head -n 1)   # the line's latest tag
git switch -C "$BRANCH" "${BASE:?}"
```

The patch block sorts an `a`, `b` or `rc` version before the release it leads to, so `v7.0.0` counts as later than `v7.0.0rc1`.

### 2. SDK, version and changelog

In one commit. Pin the SpriteStudio-SDK release this one ships, in both places it is read from: `scripts/SDK_VERSION.txt`, the tag `download-sdk.sh` fetches the native libraries by, and the `SpriteStudio-SDK` submodule, whose test projects `deploy-examples.sh` converts. `<sdk-tag>` is that release's tag. The block's last command lists the SDK's `.fbs` schemas that changed since the previous pin; when it lists any, regenerate the bindings with `scripts/generate-fbs-code.sh`.

```bash
SDK_TAG=<sdk-tag>
printf '%s\n' "${SDK_TAG:?}" >| scripts/SDK_VERSION.txt
git submodule update --init SpriteStudio-SDK && git -C SpriteStudio-SDK fetch --tags origin && git -C SpriteStudio-SDK checkout "${SDK_TAG:?}"
git -C SpriteStudio-SDK diff --stat "$(git rev-parse HEAD:SpriteStudio-SDK)" HEAD -- libs/ssab/fbs libs/ssruntime/fbs   # any output: run scripts/generate-fbs-code.sh
```

Then set `__version__` to the version being released:

```bash
VERSION=<version>
VERSION="${VERSION:?}" perl -pi -e 's/^__version__ = ".*"$/__version__ = "$ENV{VERSION}"/' game/spritestudio/python/ss_renpy/__init__.py
scripts/release-version.sh                       # must print the version
```

Date the version's heading in `CHANGELOG.md` as `## [X.Y.Z] - YYYY-MM-DD`, adding the heading if the version has none yet, and commit:

```bash
git add scripts/SDK_VERSION.txt SpriteStudio-SDK game/spritestudio/python CHANGELOG.md
git commit -m "chore(release): v$(scripts/release-version.sh)"
```

### 3. Pull request, QA build and rendering sign-off

Open the pull request into `main`; its CI runs the headless suite and Ren'Py's lint on the runtime built from the SDK submodule, exports the project for Linux, macOS, Windows and the Web, and builds the documentation:

```bash
BRANCH=$(git branch --show-current | grep '^release/')
git push -u origin "${BRANCH:?}"
gh pr create -B main -H "${BRANCH:?}" --title "Release v$(scripts/release-version.sh)" --body ""
```

Then dispatch the release workflow from the branch. It runs the headless suite and Ren'Py's lint again, on the pinned SDK release this time, then builds everything the release will — the plugin zip, the Web demo, `SHA256SUMS` — and keeps them on the run (`SSPlayerForRenPy-release-dist`) without creating a Release. Fix anything on the branch and run this block again until it and the pull request's CI are green.

```bash
BRANCH=$(git branch --show-current | grep '^release/')
git push origin "${BRANCH:?}" &&
  RUN=$(gh workflow run release.yml --ref "${BRANCH:?}" | sed 's|.*/||')
gh run watch "${RUN:?}" --exit-status
```

**A person signs off the rendering.** GL2 rendering — premultiplied alpha, mesh, blend, mask, the `ss-*` shaders — has no headless check, so it is judged by eye in the demo, on the branch, against the SDK release from step 2. This is the one part that is not bash on Windows: `fetch-renpy-sdk.sh` refuses Git Bash and `run-demo.sh` starts the macOS / Linux launcher, so run the three scripts' `.ps1` twins in PowerShell, as [CONTRIBUTING.md](./CONTRIBUTING.md) does.

```bash
scripts/download-sdk.sh && scripts/deploy-examples.sh && scripts/run-demo.sh   # Shift+B opens the Asset Browser
```

Last, scan the branch for code copied from others. `scripts/scan-snippets.sh` matches the files tracked at `HEAD` against public open-source code with SCANOSS, sending their fingerprints rather than the code; it writes its report to `qa/scanoss-<commit>.json` and prints the matches. It runs on this machine, and needs Python 3: SCANOSS's free service limits calls per address, and GitHub's runners share addresses it has often limited already. `provenance.yml` runs ScanCode, which finds copyright and license notices, and keeps its report and a summary on the run (`provenance`); the block downloads them into `qa/<run ID>` and prints the summary. **A person sorts the matches.** A match with the earlier SpriteStudio Players and SDK is our own code. A match with a library this repository bundles must be listed in `THIRD_PARTY_NOTICES.md`. Anything else is rewritten, unless its license, read at its source, is compatible with BSD-3-Clause and the code keeps the notice that license asks for. After any change on the branch, run the block again.

```bash
BRANCH=$(git branch --show-current | grep '^release/')
git push origin "${BRANCH:?}" &&
  RUN=$(gh workflow run provenance.yml --ref "${BRANCH:?}" | sed 's|.*/||') &&
  scripts/scan-snippets.sh &&
  gh run watch "${RUN:?}" --exit-status &&
  gh run download "${RUN:?}" -n provenance -D "qa/$RUN" &&
  cat "qa/$RUN/summary.md"
```

### 4. Merge and tag

Merge with a merge commit, never a squash or a rebase, so that `main` keeps the commits the QA build built rather than copies of them. Before merging, check that a QA run built the branch's head green, and that merging it changes nothing in its tree. If it would, `main` holds changes the branch does not, and the tag would go on a tree no QA run built: merge `main` into the branch and go back to step 3.

```bash
BRANCH=$(git branch --show-current | grep '^release/')
git fetch origin
SHA=$(git rev-parse --verify -q "origin/${BRANCH:?}")
gh run list -w release.yml -c "${SHA:?}" -s success -L 1                                             # must list a run
git diff --stat "origin/${BRANCH:?}" "$(git merge-tree --write-tree origin/main "origin/$BRANCH")"   # must print nothing
```

**A person runs the merge**, which puts the release on `main`: choose **Create a merge commit** on the pull request's page, or run

```bash
BRANCH=$(git branch --show-current | grep '^release/')
gh pr merge "${BRANCH:?}" --merge
```

Then tag `main`. The tag goes on the merge commit only when its tree is the branch's, which `git diff` confirms by printing nothing:

```bash
git switch main && git pull --ff-only &&
  git diff --stat --exit-code HEAD^2 HEAD &&
  TAG=v$(scripts/release-version.sh) &&
  git tag -a "$TAG" -m "$TAG" && git push origin "$TAG"
```

### 5. Build the Release

Dispatch from the tag on `main`. The run tests and builds again and creates a **draft** Release named `SpriteStudio Player for Ren'Py <tag>`, carrying every zip, `SHA256SUMS` and generated notes; nothing is public yet.

```bash
git fetch origin --tags
TAG=$(git describe --exact-match --tags --match 'v[0-9]*' origin/main)
RUN=$(gh workflow run release.yml --ref "${TAG:?}" -f upload_release=true | sed 's|.*/||')
gh run watch "${RUN:?}" --exit-status
```

Nothing passes the tag around: `build-release.sh` reads `GITHUB_REF_NAME`, or the tag `HEAD` is checked out at, and refuses one that disagrees with `__version__` — a Release called `v1.2.3` carrying `SSPlayerForRenPy-1.2.4.zip` is worse than none. A tag that already has a Release, draft or published, keeps it as it is: the run builds, says so in a notice and creates nothing, so delete a draft before dispatching again ([Undoing a release](#undoing-a-release)). With `-f upload_release=false` a run from the tag only builds, its files kept on the run.

### 6. Publish

**A person runs this step**: the notes are a judgment, and a published Release is permanent. Open the draft on the [Releases](https://github.com/cri-middleware/SSPlayerForRenPy/releases) page and check the attachments: `SSPlayerForRenPy-X.Y.Z.zip` and its alias `SSPlayerForRenPy.zip`, `SSPlayerForRenPy-web-demo-X.Y.Z.zip` and `SSPlayerForRenPy-web-demo.zip`, and `SHA256SUMS`. Edit the notes and choose **Set as the latest release** — **a beta too, never Set as a pre-release**: the README and the docs hand out `releases/latest/download/SSPlayerForRenPy.zip`, which resolves only to a release that is not a pre-release. Then **Publish release**.

Publishing starts `pages.yml`, which deploys the [documentation site](https://cri-middleware.github.io/SSPlayerForRenPy/) and the playable Web demo it downloads from this Release. Watch the run through, then open the site: a failed run leaves the Release published and the site as it was. Once the cause is fixed, re-run it with `gh run rerun "${RUN:?}"`; a re-run builds the same tag.

```bash
git fetch origin --tags
TAG=$(git describe --exact-match --tags --match 'v[0-9]*' origin/main)
RUN=$(gh run list -w pages.yml -b "${TAG:?}" -L 1 --json databaseId -q '.[0].databaseId')
gh run watch "${RUN:?}" --exit-status             # RUN is empty until the run appears: repeat the last two lines
```

### 7. Merge back

Merge `main` into `develop`. After a patch release this conflicts where `develop` has moved on: keep `develop`'s version and its `Unreleased` heading, with the patch's section below it. When the next version is decided, set it in `__version__` on `develop` and open a `## [X.Y.Z] - Unreleased` heading for it.

```bash
git fetch origin --tags
TAG=$(git describe --exact-match --tags --match 'v[0-9]*' origin/main)
git switch develop && git pull --ff-only &&
  git merge --no-ff origin/main && git push origin develop
git push origin --delete "release/$(echo "${TAG:?}" | sed 's/^v//' | cut -d. -f1,2)"
```

If the button on its pull request already deleted the release branch, the last line only reports that the branch does not exist. Nothing needs it afterwards: the line's next release cuts it again in step 1.

## Undoing a release

Until the Release is published, it can be undone. The draft goes first, if the run made one:

```bash
git fetch origin --tags
TAG=$(git describe --exact-match --tags --match 'v[0-9]*' origin/main)
gh release delete "${TAG:?}" --yes
```

A run that failed for a transient reason is then dispatched again from the same tag, with step 5's block. A fault that needs new commits takes the tag down too, on GitHub and here; then fix it on the branch — restore it from its pull request if it was deleted — and go back to step 3.

```bash
git fetch origin --tags
TAG=$(git describe --exact-match --tags --match 'v[0-9]*' origin/main)
git push origin ":refs/tags/${TAG:?}" && git tag -d "${TAG:?}"
```

**Once published, the tag and its assets are permanent** — creators have the zip, and the `__version__` inside their game folder names it — so a fix is a new patch version.

## Building the release locally

`scripts/build-release.sh` is the release, and `release.yml`'s job runs exactly this script. It produces the version-pinned plugin zip and Web demo zip, a version-less alias of each, and `SHA256SUMS` over all four.

```bash
scripts/build-release.sh              # both assets
scripts/build-release.sh demo=skip    # the plugin zip only, much faster
```

`demo=skip` is for iterating on the plugin zip, never for a release: `pages.yml` publishes the playable demo by downloading it off the Release, so a release without it leaves the site on the previous one. The `.ps1` twin builds an archive with the same entries, contents and symlinks from the same inputs. Both need `zip` and `unzip` on PATH: `Compress-Archive` cannot store symlinks at all, and the archive is checked by unpacking it. Neither archive is byte-for-byte reproducible, not even across two runs of one script: `zip` records each entry's modification time, and the files the run copies in (`README.md`, the license files, `docs/`) and the `spritestudio/` and `spritestudio/docs/` folders carry the time of the run. `cp` gives those copies that time where `Copy-Item` keeps their source's, so the twins' archives differ there as well.

**The macOS framework must still be a bundle.** `libs/macos/libssruntime.framework` is versioned, its `Versions/Current` and bundle-root aliases are symlinks, and `zip` follows symlinks unless given `-y`. Flattening them invalidates the code signature, so a game bundling the extracted framework can no longer be signed or notarised. Consumers get that framework only through this zip, and the working tree here always has the real symlinks, so a flattened bundle would ship unnoticed. The script unpacks the finished archive and asserts they survived.

<br>

---

# SpriteStudio Player for Ren'Py のリリース手順

維持者向けです。コントリビューターがこの手順を実行することはありません（[CONTRIBUTING.md](./CONTRIBUTING.md) を参照してください）。

## リリースの手順

このリポジトリの Write ロールを持つ人なら誰でもリリースできます。どの手順もブランチ・プルリクエスト・タグ・ワークフローの実行・Release のいずれかで、描画を目視で確認する GUI の実行を除けば、誰の手元で実行しても結果は変わりません。必要なのは `git`、`gh` 2.87 以降（最初に一度 `gh auth login`）、Python 3 で、SDK のスキーマが変わったときは `flatc` も要ります。リポジトリ側では、GitHub Pages を有効にしてソースを GitHub Actions にし、`github-pages` environment に `v*` のタグのルールを足しておく必要があります。どちらかが欠けると、Release を公開しても何もデプロイされません。どちらもリポジトリの admin が行う設定です。コマンドは bash です。zsh では、`#` のコメントが引数として渡されないよう、先に `setopt interactive_comments` を実行します。Windows では Git Bash を使います。手順 1・4・7 はブランチを切り替えるので、ほかの作業をしていない専用のチェックアウト（クローンか、`git worktree add` で作ったもの）で実行してください。

リリースは `main` 上のタグです。先にタグを push し、ビルドはその後です。バージョンが書かれているのは `game/spritestudio/python/ss_renpy/__init__.py` の `__version__` の 1 か所だけで、PEP 440 の形（`7.0.0b1`、`7.0.0rc1`、`7.0.0`。`-` は使いません）です。`scripts/release-version.sh` がそれを出力し、タグはその頭に `v` を付けたものです。食い違うタグはリリースビルドが拒否します。この値はクリエイターがゲームに入れるフォルダの中に入るので、`scripts/SDK_VERSION.txt` ではなくこちらがリリースの名前になります。ブランチは git-flow です。`develop` が統合ブランチで、`main` にはリリース済みのコミットだけが入ります。`release/X.Y` は 1 回のリリースの間だけ使います。`develop` の作業を出すリリースなら `develop` から、タグの上に修正だけを載せるリリースならその系統の最新のタグから切り、リリースが済んだら消します。

どのブロックも、新しいシェルで書かれたとおりに実行できます。必要なものはチェックアウト・git・GitHub から求めます。手で設定する値は 2 つで、どちらも埋めるプレースホルダとして書いてあります。手順 1 と 2 の `<version>` はリリースするバージョン（`7.0.1` など）、手順 2 の `<sdk-tag>` は同梱する SpriteStudio-SDK のリリース（`v7.0.0` など）です。埋めずに実行すると、その行は構文エラーで止まります。空でもそれだけでは止まらない値は `${VAR:?}` で読みます。手順 3 の `BRANCH` が空だと QA ビルドを `develop` から実行し、手順 6 の `TAG` が空だと、どのタグをビルドしたかに関係なくいちばん新しい Pages の run を見てしまうためです。

どのブロックもエージェントに実行させられます。手順 3 の照合の一致は人が仕分け、描画の確認は目で判断するので人が行い、2 つの手順は人が判断します。リリースを `main` に入れる手順 4 のマージと、取り消せない公開を行う手順 6 です。

### 1. ブランチ

`develop` の作業を出すリリースは `develop` から切ります。新しい `X.Y` や、`7.0.0b1` の後の `7.0.0` がこれに当たります。パッチリリースは修正だけを出すもので、その系統の最新のタグから切り、修正をそこへコミットするか cherry-pick します。どちらの場合も、以前の `release/X.Y` が残っていれば置き換えます。当てはまる方のブロックを実行します。

`develop` の作業を出すとき:

```bash
VERSION=<version>
BRANCH=release/$(echo "${VERSION:?}" | cut -d. -f1,2)
git fetch origin
git switch -C "$BRANCH" origin/develop
```

パッチのとき:

```bash
VERSION=<version>
BRANCH=release/$(echo "${VERSION:?}" | cut -d. -f1,2)
git fetch origin --tags
BASE=$(git -c versionsort.suffix=a -c versionsort.suffix=b -c versionsort.suffix=rc tag --list "v${BRANCH#release/}.*" --sort=-v:refname | head -n 1)   # その系統の最新のタグ
git switch -C "$BRANCH" "${BASE:?}"
```

パッチのブロックは、`a`・`b`・`rc` の付いたバージョンを、それが目指すリリースより前に並べます。`v7.0.0` は `v7.0.0rc1` より後と数えます。

### 2. SDK、バージョン、CHANGELOG

1 コミットで行います。同梱する SpriteStudio-SDK のリリースを、読まれる 2 か所の両方で固定します。`download-sdk.sh` がネイティブライブラリを取得するときに使うタグ `scripts/SDK_VERSION.txt` と、`deploy-examples.sh` がテストプロジェクトを変換する `SpriteStudio-SDK` submodule です。`<sdk-tag>` はそのリリースのタグです。ブロックの最後のコマンドは、前回固定したときから変わった SDK の `.fbs` スキーマを並べます。何か並んだら、`scripts/generate-fbs-code.sh` でバインディングを生成し直します。

```bash
SDK_TAG=<sdk-tag>
printf '%s\n' "${SDK_TAG:?}" >| scripts/SDK_VERSION.txt
git submodule update --init SpriteStudio-SDK && git -C SpriteStudio-SDK fetch --tags origin && git -C SpriteStudio-SDK checkout "${SDK_TAG:?}"
git -C SpriteStudio-SDK diff --stat "$(git rev-parse HEAD:SpriteStudio-SDK)" HEAD -- libs/ssab/fbs libs/ssruntime/fbs   # 何か出たら scripts/generate-fbs-code.sh を実行する
```

続けて `__version__` をリリースするバージョンにします。

```bash
VERSION=<version>
VERSION="${VERSION:?}" perl -pi -e 's/^__version__ = ".*"$/__version__ = "$ENV{VERSION}"/' game/spritestudio/python/ss_renpy/__init__.py
scripts/release-version.sh                       # そのバージョンが出力されること
```

`CHANGELOG.md` のそのバージョンの見出しに日付を入れて `## [X.Y.Z] - YYYY-MM-DD` とし（見出しがまだ無ければ足します）、コミットします。

```bash
git add scripts/SDK_VERSION.txt SpriteStudio-SDK game/spritestudio/python CHANGELOG.md
git commit -m "chore(release): v$(scripts/release-version.sh)"
```

### 3. プルリクエスト、QA ビルド、描画の確認

`main` へのプルリクエストを作ります。その CI が、SDK の submodule からビルドしたランタイムでヘッドレステストと Ren'Py の lint を回し、Linux・macOS・Windows・Web 向けにプロジェクトを書き出し、ドキュメントをビルドします。

```bash
BRANCH=$(git branch --show-current | grep '^release/')
git push -u origin "${BRANCH:?}"
gh pr create -B main -H "${BRANCH:?}" --title "Release v$(scripts/release-version.sh)" --body ""
```

続けて、ブランチからリリースワークフローを実行します。こちらは固定した SDK リリースで、ヘッドレステストと Ren'Py の lint をもう一度回し、リリースと同じもの — プラグイン zip、Web デモ、`SHA256SUMS` — をビルドして run に残し（`SSPlayerForRenPy-release-dist`）、Release は作りません。問題があればブランチで直し、この run とプルリクエストの CI が緑になるまでこのブロックを繰り返します。

```bash
BRANCH=$(git branch --show-current | grep '^release/')
git push origin "${BRANCH:?}" &&
  RUN=$(gh workflow run release.yml --ref "${BRANCH:?}" | sed 's|.*/||')
gh run watch "${RUN:?}" --exit-status
```

**描画の確認は人が行います。** GL2 の描画 — 乗算済みアルファ、メッシュ、ブレンド、マスク、`ss-*` シェーダ — にはヘッドレスの検査が無いので、ブランチ上で、手順 2 の SDK リリースを使ってデモを目で見て判断します。Windows で bash を使わないのはここだけです。`fetch-renpy-sdk.sh` は Git Bash では実行を拒否し、`run-demo.sh` は macOS / Linux 用の起動スクリプトを使うので、[CONTRIBUTING.md](./CONTRIBUTING.md) と同じく、3 つのスクリプトの `.ps1` 版を PowerShell で実行してください。

```bash
scripts/download-sdk.sh && scripts/deploy-examples.sh && scripts/run-demo.sh   # Shift+B で Asset Browser を開く
```

最後に、他者のコードを写した箇所が無いかを、ブランチで照合します。`scripts/scan-snippets.sh` は、`HEAD` で追跡しているファイルを、SCANOSS で公開されているオープンソースのコードと照合します。送るのはコードではなく指紋です。報告を `qa/scanoss-<commit>.json` に書き、一致を表示します。このスクリプトは手元で実行し、Python 3 が要ります。SCANOSS の無料のサービスはアドレスごとに回数を制限していて、GitHub のランナーはすでに制限されたアドレスを共有していることが多いためです。`provenance.yml` は ScanCode で著作権表示とライセンスの記述を見つけ、報告と一覧を run に残します（`provenance`）。ブロックはそれを `qa/<run ID>` にダウンロードし、一覧を表示します。**一致は人が仕分けます。** 以前の SpriteStudio の Player・SDK との一致は、自社のコードです。このリポジトリが同梱するライブラリとの一致は、`THIRD_PARTY_NOTICES.md` に載っていなければなりません。それ以外は書き直します。残せるのは、出所で確かめたライセンスが BSD-3-Clause と両立し、そのライセンスが求める表示をコードに残すときだけです。ブランチを変えたら、このブロックをもう一度実行します。

```bash
BRANCH=$(git branch --show-current | grep '^release/')
git push origin "${BRANCH:?}" &&
  RUN=$(gh workflow run provenance.yml --ref "${BRANCH:?}" | sed 's|.*/||') &&
  scripts/scan-snippets.sh &&
  gh run watch "${RUN:?}" --exit-status &&
  gh run download "${RUN:?}" -n provenance -D "qa/$RUN" &&
  cat "qa/$RUN/summary.md"
```

### 4. マージとタグ

マージはマージコミットで行い、squash や rebase は使いません。QA ビルドしたコミットの写しではなく、そのものを `main` に残すためです。マージの前に、ブランチの先頭を QA の run が緑でビルドしていること、マージしてもブランチのツリーが変わらないことを確かめます。変わるなら `main` にブランチの持たない変更があり、どの QA の run もビルドしていないツリーにタグが付きます。そのときは `main` をブランチへマージして手順 3 に戻ります。

```bash
BRANCH=$(git branch --show-current | grep '^release/')
git fetch origin
SHA=$(git rev-parse --verify -q "origin/${BRANCH:?}")
gh run list -w release.yml -c "${SHA:?}" -s success -L 1                                             # run が 1 つ表示されること
git diff --stat "origin/${BRANCH:?}" "$(git merge-tree --write-tree origin/main "origin/$BRANCH")"   # 何も出力されないこと
```

**マージは人が行います。** リリースが `main` に入るためです。プルリクエストのページで **Create a merge commit** を選ぶか、次を実行します。

```bash
BRANCH=$(git branch --show-current | grep '^release/')
gh pr merge "${BRANCH:?}" --merge
```

続けて `main` にタグを打ちます。タグはマージコミットのツリーがブランチと同じときにだけ打たれます。`git diff` が何も出力しないことがその確認です。

```bash
git switch main && git pull --ff-only &&
  git diff --stat --exit-code HEAD^2 HEAD &&
  TAG=v$(scripts/release-version.sh) &&
  git tag -a "$TAG" -m "$TAG" && git push origin "$TAG"
```

### 5. Release のビルド

`main` 上のタグからワークフローを実行します。テストとビルドをもう一度行い、`SpriteStudio Player for Ren'Py <タグ>` という名前の**下書き**の Release を、すべての zip と `SHA256SUMS`、自動生成のリリースノート付きで作ります。まだ何も公開されていません。

```bash
git fetch origin --tags
TAG=$(git describe --exact-match --tags --match 'v[0-9]*' origin/main)
RUN=$(gh workflow run release.yml --ref "${TAG:?}" -f upload_release=true | sed 's|.*/||')
gh run watch "${RUN:?}" --exit-status
```

タグは受け渡されません。`build-release.sh` が `GITHUB_REF_NAME`（ローカルでは `HEAD` のタグ）を読み、`__version__` と食い違うタグを拒否します。`v1.2.3` という Release に `SSPlayerForRenPy-1.2.4.zip` が入っているくらいなら、Release が無い方がましだからです。Release がすでにあるタグでは、下書きでも公開済みでも、その Release に触れません。run はビルドして notice を出すだけなので、もう一度実行するときは先に下書きを消します（[リリースの取り消し](#リリースの取り消し)）。`-f upload_release=false` を付けると、タグからの実行でもビルドだけを行い、成果物を run に残します。

### 6. 公開

**この手順は人が行います。** リリースノートの中身は判断が要り、公開した Release は取り消せないためです。[Releases](https://github.com/cri-middleware/SSPlayerForRenPy/releases) ページで下書きを開き、添付を確かめます。`SSPlayerForRenPy-X.Y.Z.zip` とそのエイリアス `SSPlayerForRenPy.zip`、`SSPlayerForRenPy-web-demo-X.Y.Z.zip` と `SSPlayerForRenPy-web-demo.zip`、`SHA256SUMS` の 5 つです。リリースノートを編集し、**Set as the latest release** を選びます。**ベータでも Set as a pre-release にはしません。** README と docs が案内する `releases/latest/download/SSPlayerForRenPy.zip` は、pre-release ではない Release にしか解決されないためです。最後に **Publish release** を押します。

公開すると `pages.yml` が動き、[ドキュメントサイト](https://cri-middleware.github.io/SSPlayerForRenPy/) と、この Release から取得する遊べる Web デモをデプロイします。run を最後まで見届けてから、サイトを開いて確かめます。run が失敗しても Release は公開されたままで、サイトは元のまま残ります。原因を直したら `gh run rerun "${RUN:?}"` で再実行します。再実行は同じタグをビルドします。

```bash
git fetch origin --tags
TAG=$(git describe --exact-match --tags --match 'v[0-9]*' origin/main)
RUN=$(gh run list -w pages.yml -b "${TAG:?}" -L 1 --json databaseId -q '.[0].databaseId')
gh run watch "${RUN:?}" --exit-status             # run が出るまで RUN は空。最後の 2 行を繰り返す
```

### 7. develop へ戻す

`main` を `develop` へマージします。パッチリリースの後は、`develop` が先へ進んだ箇所で衝突します。`develop` のバージョンと `Unreleased` の見出しを残し、パッチの節をその下に置いてください。次のバージョンが決まったら、`develop` の `__version__` を設定し、`## [X.Y.Z] - Unreleased` の見出しを立てます。

```bash
git fetch origin --tags
TAG=$(git describe --exact-match --tags --match 'v[0-9]*' origin/main)
git switch develop && git pull --ff-only &&
  git merge --no-ff origin/main && git push origin develop
git push origin --delete "release/$(echo "${TAG:?}" | sed 's/^v//' | cut -d. -f1,2)"
```

プルリクエストのページのボタンでリリースブランチを消してあれば、最後の行は「ブランチが無い」と出るだけです。同じ系統の次のリリースは手順 1 で切り直すので、この後ブランチが要ることはありません。

## リリースの取り消し

Release を公開するまでは取り消せます。run が下書きを作っていれば、先にそれを消します。

```bash
git fetch origin --tags
TAG=$(git describe --exact-match --tags --match 'v[0-9]*' origin/main)
gh release delete "${TAG:?}" --yes
```

一時的な理由で失敗した run は、そのあと手順 5 のブロックで同じタグからもう一度実行します。新しいコミットが要る不具合なら、タグも GitHub と手元の両方から取り下げ、ブランチで直して（消していたらプルリクエストのページから復元して）手順 3 に戻ります。

```bash
git fetch origin --tags
TAG=$(git describe --exact-match --tags --match 'v[0-9]*' origin/main)
git push origin ":refs/tags/${TAG:?}" && git tag -d "${TAG:?}"
```

**公開した後のタグとアセットは恒久的です。** クリエイターはその zip を持っていて、ゲームのフォルダの中の `__version__` がそれを名指ししているので、修正は新しいパッチバージョンで出します。

## リリースのローカルビルド

`scripts/build-release.sh` がリリースそのもので、`release.yml` のジョブはこのスクリプトを実行しているだけです。バージョン付きのプラグイン zip と Web デモ zip、それぞれのバージョン無しエイリアス、そして 4 つすべてに対する `SHA256SUMS` を作ります。

```bash
scripts/build-release.sh              # 両方の asset
scripts/build-release.sh demo=skip    # プラグイン zip だけ。かなり速い
```

`demo=skip` はプラグイン zip を反復するためのもので、リリースには使いません。`pages.yml` は Release からデモを取得して公開するため、デモの無いリリースはサイトを前のバージョンのまま残します。`.ps1` 版も同じ入力から、エントリ・内容・symlink が同じアーカイブを作ります。どちらも PATH 上の `zip` と `unzip` が必要です（`Compress-Archive` は symlink を格納できず、アーカイブは展開して確かめるためです）。ただし、どちらのアーカイブもバイト単位では再現せず、同じスクリプトを 2 回実行しても一致しません。`zip` は各エントリの更新時刻を記録し、実行中にコピーするファイル（`README.md`、ライセンスのファイル、`docs/`）と `spritestudio/`・`spritestudio/docs/` フォルダーには実行時の時刻が付くためです。そのコピーに `cp` は実行時の時刻を付け、`Copy-Item` はコピー元の時刻を保つので、双子のアーカイブはここでも違います。

**macOS の framework はバンドルのままでなければなりません。** `libs/macos/libssruntime.framework` はバージョン付きで、`Versions/Current` とバンドルルートのエイリアスは symlink です。`zip` は `-y` を付けない限り symlink を辿ります。これを平坦化するとコード署名が無効になり、展開した framework を同梱したゲームは署名も公証もできなくなります。利用者がこの framework を受け取る経路はこの zip だけで、ここの作業ツリーには常に本物の symlink があるため、平坦化されたバンドルは気づかれずに出荷されます。スクリプトは完成したアーカイブを展開し、symlink が残っていることを確かめます。
