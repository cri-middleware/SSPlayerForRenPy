# Releasing SpriteStudio Player for Ren'Py

Maintainers only. Contributors do not run any of this — see [CONTRIBUTING.md](./CONTRIBUTING.md).

## Cutting a release

Anyone with the Write role on this repository can cut a release: every step is a branch, a pull request, a tag, a workflow run or a Release, so nothing depends on whose machine runs it beyond the GUI run that signs off rendering. You need `git`, `gh` (run `gh auth login` once) and Python 3, plus `flatc` when the SDK's schema changed. The commands are bash; on Windows, run them in Git Bash.

A release is a tag on `main`, pushed first and built second. The version is written in one place, `__version__` in `game/spritestudio/python/ss_renpy/__init__.py`, in PEP 440 form — `7.0.0b1`, `7.0.0rc1`, `7.0.0`, never a `-`. `scripts/release-version.sh` prints it, the tag is `v` followed by it, and the release build refuses a tag that disagrees. It ships inside the folder creators drop into their game, which is why it, and not `scripts/SDK_VERSION.txt`, names the release. Branches follow git-flow: `develop` integrates, `main` holds released commits only, and `release/X.Y` lives for one release — cut from `develop` for a new `X.Y`, or from the line's latest tag for a patch, and deleted once the release is out.

```bash
VERSION=7.0.1                                       # what is being released, PEP 440
BRANCH=release/$(echo "$VERSION" | cut -d. -f1,2)   # release/7.0
```

### 1. Branch

A new `X.Y` is cut from `develop`. A patch release is cut from the line's latest tag, whether or not an earlier `release/X.Y` is still there, and its fixes are committed or cherry-picked onto it.

```bash
git fetch origin
git switch -c "$BRANCH" origin/develop           # a new X.Y
git switch -C "$BRANCH" v7.0.0                   # a patch release: the line's latest tag
```

### 2. SDK, version and changelog

In one commit. Pin the SpriteStudio-SDK release this one ships, in both places it is read from: `scripts/SDK_VERSION.txt`, the tag `download-sdk.sh` fetches the native libraries by, and the `SpriteStudio-SDK` submodule, whose test projects `deploy-examples.sh` converts. When the SDK's `.fbs` schemas changed, regenerate the bindings. Then set `__version__`, and date the version's heading in `CHANGELOG.md` as `## [X.Y.Z] - YYYY-MM-DD`, adding the heading on a patch release.

```bash
SDK_TAG=v7.0.0                                   # the SDK release this ships
printf '%s\n' "$SDK_TAG" > scripts/SDK_VERSION.txt
git -C SpriteStudio-SDK fetch --tags origin && git -C SpriteStudio-SDK checkout "$SDK_TAG"
scripts/generate-fbs-code.sh                     # only when the SDK's schema changed
# set __version__ in game/spritestudio/python/ss_renpy/__init__.py and date the heading in CHANGELOG.md, then:
scripts/release-version.sh                       # must print $VERSION
git add scripts/SDK_VERSION.txt SpriteStudio-SDK game/spritestudio/python CHANGELOG.md
git commit -m "chore(release): v$VERSION"
```

### 3. Pull request, QA build and rendering sign-off

Open the pull request into `main`, then dispatch the release workflow from the branch. Nothing runs on a pull request here, so this run is the check suite: it runs the headless suite and Ren'Py's lint, then builds everything the release will — the plugin zip, the Web demo, `SHA256SUMS` — and keeps them on the run (`SSPlayerForRenPy-release-dist`) without creating a Release. Fix anything on the branch and repeat until it is green.

```bash
git push -u origin "$BRANCH"
gh pr create -B main --title "Release v$VERSION" --body ""
gh workflow run release.yml --ref "$BRANCH"
gh run watch                                      # the run takes a few seconds to appear
```

GL2 rendering — premultiplied alpha, mesh, blend, mask, the `ss-*` shaders — has no headless check. Sign it off in the demo, on the branch, against the SDK release from step 2. This is the one part that is not bash on Windows: `fetch-renpy-sdk.sh` refuses Git Bash and `run-demo.sh` starts the macOS / Linux launcher, so run the three scripts' `.ps1` twins in PowerShell, as [CONTRIBUTING.md](./CONTRIBUTING.md) does.

```bash
scripts/download-sdk.sh && scripts/deploy-examples.sh && scripts/run-demo.sh   # Shift+B opens the Asset Browser
```

### 4. Merge and tag

Merge with a merge commit, never a squash or a rebase, so that `main` keeps the commits the QA build built rather than copies of them. Tag `main` only when its tree is the one the QA build built. It differs only when `main` held commits the branch did not; merge `main` into the branch and go back to step 3.

```bash
gh pr merge "$BRANCH" --merge
git switch main && git pull --ff-only
git diff --stat HEAD^2 HEAD                           # must print nothing
TAG=v$(scripts/release-version.sh) && echo "$TAG"
git tag -a "$TAG" -m "$TAG" && git push origin "$TAG"
```

### 5. Build the Release

Dispatch from the tag. The run tests and builds again and creates a **draft** Release named `SpriteStudio Player for Ren'Py <tag>`, carrying every zip, `SHA256SUMS` and generated notes; nothing is public yet.

```bash
gh workflow run release.yml --ref "$TAG" -f upload_release=true
gh run watch
```

Nothing passes the tag around: `build-release.sh` reads `GITHUB_REF_NAME`, or the tag `HEAD` is checked out at, and refuses one that disagrees with `__version__` — a Release called `v1.2.3` carrying `SSPlayerForRenPy-1.2.4.zip` is worse than none. `upload_release=true` from anything but a `v*` tag fails the run rather than skipping the Release quietly.

### 6. Publish

Open the draft on the [Releases](https://github.com/cri-middleware/SSPlayerForRenPy/releases) page and check the attachments: `SSPlayerForRenPy-X.Y.Z.zip` and its alias `SSPlayerForRenPy.zip`, `SSPlayerForRenPy-web-demo-X.Y.Z.zip` and `SSPlayerForRenPy-web-demo.zip`, and `SHA256SUMS`. Edit the notes and choose **Set as the latest release** — **a beta too, never Set as a pre-release**: the README and the docs hand out `releases/latest/download/SSPlayerForRenPy.zip`, which resolves only to a release that is not a pre-release. Then **Publish release**. Publishing starts `pages.yml`, which deploys the [documentation site](https://cri-middleware.github.io/SSPlayerForRenPy/) and the playable Web demo it downloads from this Release. Watch the run through, then open the site: a failed run leaves the Release published and the site as it was. Once the cause is fixed, re-run it; a re-run builds the same tag.

```bash
gh run watch                                      # pages.yml; the run takes a few seconds to appear
```

### 7. Merge back

Merge `main` into `develop`. After a patch release this conflicts where `develop` has moved on: keep `develop`'s version and its `Unreleased` heading, with the patch's section below it. When the next version is decided, set it in `__version__` on `develop` and open a `## [X.Y.Z] - Unreleased` heading for it.

```bash
git switch develop && git pull --ff-only
git merge --no-ff main && git push origin develop
git push origin --delete "$BRANCH"
```

If the button on its pull request already deleted the release branch, the last line only reports that the branch does not exist. Nothing needs it afterwards: a patch release cuts it again from the tag.

## Undoing a release

Until the Release is published, it can be undone. A run that failed for a transient reason is dispatched again from the same tag once its draft is deleted. A fault that needs new commits takes the tag down too: delete the draft, run `git push origin ":refs/tags/$TAG" && git tag -d "$TAG"`, fix it on the branch — restore it from its pull request if it was deleted — and go back to step 3.

**Once published, the tag and its assets are permanent** — creators have the zip, and the `__version__` inside their game folder names it — so a fix is a new patch version.

## Building the release locally

`scripts/build-release.sh` is the release, and `release.yml`'s job runs exactly this script. It produces the version-pinned plugin zip and Web demo zip, a version-less alias of each, and `SHA256SUMS` over all four.

```bash
scripts/build-release.sh              # both assets
scripts/build-release.sh demo=skip    # the plugin zip only, much faster
```

`demo=skip` is for iterating on the plugin zip, never for a release: `pages.yml` publishes the playable demo by downloading it off the Release, so a release without it leaves the site on the previous one. The `.ps1` twin produces a byte-identical archive from the same inputs, and both need `zip` on PATH — `Compress-Archive` cannot store symlinks at all.

**The macOS framework must still be a bundle.** `libs/macos/libssruntime.framework` is versioned, its `Versions/Current` and bundle-root aliases are symlinks, and `zip` follows symlinks unless given `-y`. Flattening them invalidates the code signature, so a game bundling the extracted framework can no longer be signed or notarised. Consumers get that framework only through this zip, and the working tree here always has the real symlinks, so a flattened bundle would ship unnoticed. The script unpacks the finished archive and asserts they survived.

<br>

---

# SpriteStudio Player for Ren'Py のリリース手順

維持者向けです。コントリビューターがこの手順を実行することはありません（[CONTRIBUTING.md](./CONTRIBUTING.md) を参照してください）。

## リリースの手順

このリポジトリの Write ロールを持つ人なら誰でもリリースできます。どの手順もブランチ・プルリクエスト・タグ・ワークフローの実行・Release のいずれかで、描画を目視で確認する GUI の実行を除けば、誰の手元で実行しても結果は変わりません。必要なのは `git`、`gh`（最初に一度 `gh auth login`）、Python 3 で、SDK のスキーマが変わったときは `flatc` も要ります。コマンドは bash で書いています。Windows では Git Bash で実行してください。

リリースは `main` 上のタグです。先にタグを push し、ビルドはその後です。バージョンが書かれているのは `game/spritestudio/python/ss_renpy/__init__.py` の `__version__` の 1 か所だけで、PEP 440 の形（`7.0.0b1`、`7.0.0rc1`、`7.0.0`。`-` は使いません）です。`scripts/release-version.sh` がそれを出力し、タグはその頭に `v` を付けたものです。食い違うタグはリリースビルドが拒否します。この値はクリエイターがゲームに入れるフォルダの中に入るので、`scripts/SDK_VERSION.txt` ではなくこちらがリリースの名前になります。ブランチは git-flow です。`develop` が統合ブランチで、`main` にはリリース済みのコミットだけが入ります。`release/X.Y` は 1 回のリリースの間だけ使います。新しい `X.Y` なら `develop` から、パッチならその系統の最新のタグから切り、リリースが済んだら消します。

```bash
VERSION=7.0.1                                       # リリースするバージョン（PEP 440）
BRANCH=release/$(echo "$VERSION" | cut -d. -f1,2)   # release/7.0
```

### 1. ブランチ

新しい `X.Y` は `develop` から切ります。パッチリリースは、以前の `release/X.Y` が残っているかどうかに関係なく、その系統の最新のタグから切り、修正をそこへコミットするか cherry-pick します。

```bash
git fetch origin
git switch -c "$BRANCH" origin/develop           # 新しい X.Y
git switch -C "$BRANCH" v7.0.0                   # パッチリリース: その系統の最新のタグ
```

### 2. SDK、バージョン、CHANGELOG

1 コミットで行います。同梱する SpriteStudio-SDK のリリースを、読まれる 2 か所の両方で固定します。`download-sdk.sh` がネイティブライブラリを取得するときに使うタグ `scripts/SDK_VERSION.txt` と、`deploy-examples.sh` がテストプロジェクトを変換する `SpriteStudio-SDK` submodule です。SDK の `.fbs` スキーマが変わったときはバインディングを生成し直します。続けて `__version__` を設定し、`CHANGELOG.md` のそのバージョンの見出しに日付を入れて `## [X.Y.Z] - YYYY-MM-DD` とします。パッチリリースでは見出しを足します。

```bash
SDK_TAG=v7.0.0                                   # 同梱する SDK のリリース
printf '%s\n' "$SDK_TAG" > scripts/SDK_VERSION.txt
git -C SpriteStudio-SDK fetch --tags origin && git -C SpriteStudio-SDK checkout "$SDK_TAG"
scripts/generate-fbs-code.sh                     # SDK のスキーマが変わったときだけ
# game/spritestudio/python/ss_renpy/__init__.py の __version__ を設定し、CHANGELOG.md の見出しに日付を入れてから:
scripts/release-version.sh                       # $VERSION が出力されること
git add scripts/SDK_VERSION.txt SpriteStudio-SDK game/spritestudio/python CHANGELOG.md
git commit -m "chore(release): v$VERSION"
```

### 3. プルリクエスト、QA ビルド、描画の確認

`main` へのプルリクエストを作り、ブランチからリリースワークフローを実行します。このリポジトリではプルリクエストで何も走らないので、この run がチェック一式です。ヘッドレステストと Ren'Py の lint を回し、リリースと同じもの — プラグイン zip、Web デモ、`SHA256SUMS` — をビルドして run に残し（`SSPlayerForRenPy-release-dist`）、Release は作りません。問題があればブランチで直し、緑になるまで繰り返します。

```bash
git push -u origin "$BRANCH"
gh pr create -B main --title "Release v$VERSION" --body ""
gh workflow run release.yml --ref "$BRANCH"
gh run watch                                      # run が一覧に出るまで数秒かかる
```

GL2 の描画 — 乗算済みアルファ、メッシュ、ブレンド、マスク、`ss-*` シェーダ — にはヘッドレスの検査がありません。ブランチ上で、手順 2 の SDK リリースを使ってデモで確認します。Windows で bash を使わないのはここだけです。`fetch-renpy-sdk.sh` は Git Bash では実行を拒否し、`run-demo.sh` は macOS / Linux 用の起動スクリプトを使うので、[CONTRIBUTING.md](./CONTRIBUTING.md) と同じく、3 つのスクリプトの `.ps1` 版を PowerShell で実行してください。

```bash
scripts/download-sdk.sh && scripts/deploy-examples.sh && scripts/run-demo.sh   # Shift+B で Asset Browser を開く
```

### 4. マージとタグ

マージはマージコミットで行い、squash や rebase は使いません。QA ビルドしたコミットの写しではなく、そのものを `main` に残すためです。タグは、`main` のツリーが QA ビルドしたものと同じときにだけ打ちます。違うのは `main` にブランチが持たないコミットがあった場合だけで、そのときは `main` をブランチへマージして手順 3 に戻ります。

```bash
gh pr merge "$BRANCH" --merge
git switch main && git pull --ff-only
git diff --stat HEAD^2 HEAD                           # 何も出力されないこと
TAG=v$(scripts/release-version.sh) && echo "$TAG"
git tag -a "$TAG" -m "$TAG" && git push origin "$TAG"
```

### 5. Release のビルド

タグからワークフローを実行します。テストとビルドをもう一度行い、`SpriteStudio Player for Ren'Py <タグ>` という名前の**下書き**の Release を、すべての zip と `SHA256SUMS`、自動生成のリリースノート付きで作ります。まだ何も公開されていません。

```bash
gh workflow run release.yml --ref "$TAG" -f upload_release=true
gh run watch
```

タグは受け渡されません。`build-release.sh` が `GITHUB_REF_NAME`（ローカルでは `HEAD` のタグ）を読み、`__version__` と食い違うタグを拒否します。`v1.2.3` という Release に `SSPlayerForRenPy-1.2.4.zip` が入っているくらいなら、Release が無い方がましだからです。`v*` タグ以外からの `upload_release=true` は、Release を黙って飛ばさずに実行を失敗させます。

### 6. 公開

[Releases](https://github.com/cri-middleware/SSPlayerForRenPy/releases) ページで下書きを開き、添付を確かめます。`SSPlayerForRenPy-X.Y.Z.zip` とそのエイリアス `SSPlayerForRenPy.zip`、`SSPlayerForRenPy-web-demo-X.Y.Z.zip` と `SSPlayerForRenPy-web-demo.zip`、`SHA256SUMS` の 5 つです。リリースノートを編集し、**Set as the latest release** を選びます。**ベータでも Set as a pre-release にはしません。** README と docs が案内する `releases/latest/download/SSPlayerForRenPy.zip` は、pre-release ではない Release にしか解決されないためです。最後に **Publish release** を押します。公開すると `pages.yml` が動き、[ドキュメントサイト](https://cri-middleware.github.io/SSPlayerForRenPy/) と、この Release から取得する遊べる Web デモをデプロイします。run を最後まで見届けてから、サイトを開いて確かめます。run が失敗しても Release は公開されたままで、サイトは元のまま残ります。原因を直したら run を再実行します。再実行は同じタグをビルドします。

```bash
gh run watch                                      # pages.yml。run が一覧に出るまで数秒かかる
```

### 7. develop へ戻す

`main` を `develop` へマージします。パッチリリースの後は、`develop` が先へ進んだ箇所で衝突します。`develop` のバージョンと `Unreleased` の見出しを残し、パッチの節をその下に置いてください。次のバージョンが決まったら、`develop` の `__version__` を設定し、`## [X.Y.Z] - Unreleased` の見出しを立てます。

```bash
git switch develop && git pull --ff-only
git merge --no-ff main && git push origin develop
git push origin --delete "$BRANCH"
```

プルリクエストのページのボタンでリリースブランチを消してあれば、最後の行は「ブランチが無い」と出るだけです。パッチリリースはタグから切り直すので、この後ブランチが要ることはありません。

## リリースの取り消し

Release を公開するまでは取り消せます。一時的な理由で失敗した run は、下書きを消してから同じタグでもう一度実行します。新しいコミットが要る不具合ならタグも取り下げます。下書きを消し、`git push origin ":refs/tags/$TAG" && git tag -d "$TAG"` を実行し、ブランチで直して（消していたらプルリクエストのページから復元して）手順 3 に戻ります。

**公開した後のタグとアセットは恒久的です。** クリエイターはその zip を持っていて、ゲームのフォルダの中の `__version__` がそれを名指ししているので、修正は新しいパッチバージョンで出します。

## リリースのローカルビルド

`scripts/build-release.sh` がリリースそのもので、`release.yml` のジョブはこのスクリプトを実行しているだけです。バージョン付きのプラグイン zip と Web デモ zip、それぞれのバージョン無しエイリアス、そして 4 つすべてに対する `SHA256SUMS` を作ります。

```bash
scripts/build-release.sh              # 両方の asset
scripts/build-release.sh demo=skip    # プラグイン zip だけ。かなり速い
```

`demo=skip` はプラグイン zip を反復するためのもので、リリースには使いません。`pages.yml` は Release からデモを取得して公開するため、デモの無いリリースはサイトを前のバージョンのまま残します。`.ps1` 版は同じ入力からバイト一致のアーカイブを作りますが、どちらも PATH 上の `zip` が必要です（`Compress-Archive` は symlink を格納できません）。

**macOS の framework はバンドルのままでなければなりません。** `libs/macos/libssruntime.framework` はバージョン付きで、`Versions/Current` とバンドルルートのエイリアスは symlink です。`zip` は `-y` を付けない限り symlink を辿ります。これを平坦化するとコード署名が無効になり、展開した framework を同梱したゲームは署名も公証もできなくなります。利用者がこの framework を受け取る経路はこの zip だけで、ここの作業ツリーには常に本物の symlink があるため、平坦化されたバンドルは気づかれずに出荷されます。スクリプトは完成したアーカイブを展開し、symlink が残っていることを確かめます。
