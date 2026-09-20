# Releasing SpriteStudio Player for Ren'Py

Maintainers only. Contributors do not run any of this — see [CONTRIBUTING.md](./CONTRIBUTING.md).

## Building the documentation site

```bash
scripts/prepare-docs.sh              # once: .venv + the pins in docs/requirements.txt
scripts/build-docs.sh                # English then Japanese, both --strict
scripts/build-pages.sh serve=yes     # + the released Web demo -> http://localhost:8000/
```

Both locales, English first: it clears `site/`, which contains `site/ja`, so an English-only build
leaves a stale Japanese site behind and a page you just broke still looks fine. `mkdocs.base.yml`
sets `strict: true`; `serve` validates nothing, and nothing builds the docs on a pull request.

`build-pages.sh` is the whole published site, and `pages.yml`'s build job **is** this script with
every option spelled out. `demo=download` needs `gh` and a Release carrying
`SSPlayerForRenPy-web-demo.zip`; `zip=<path>` feeds one by hand, and `demo=build` runs the export
here instead — the only option until that first Release exists. `sdk=` picks `download-sdk` or
`build-runtime` and is consulted for `demo=build` only, since a downloaded demo brings its own
runtime. An existing `renpy-sdk/` is never re-fetched.

Note that `game/options.rpy` excludes `site/**`: the docs build copies the screencasts into
`site/*/assets/`, and Ren'Py would otherwise classify every `**.webm` into every package.

## Cutting a release

A release is a tag, pushed first and built second: push `v$__version__`, then dispatch **Release**
from that tag with `upload_release=true`. The tag names the Release, and `upload_release=true`
from anything else fails the run rather than quietly producing none; the default dispatch is a QA
build and creates no Release. What comes out is a draft — a human reviews the assets and the
generated notes and publishes from the UI. **A beta is still published as the *latest* release**,
because `releases/latest/download/…` is the link the README and the docs hand out, and that only
resolves for a non-prerelease.

The tag must agree with `ss_renpy.__version__`, which is the single source of truth: it ships
inside the folder creators get, and the release reads it for the tag and the zip name.

`scripts/build-release.sh` is the release, and `release.yml`'s job **is** this script with every
option spelled out. It produces the version-pinned plugin zip and Web demo zip, a version-less
alias of each, and `SHA256SUMS` over all four.

```bash
scripts/build-release.sh              # both assets
scripts/build-release.sh demo=skip    # the plugin zip only, much faster
```

`demo=skip` is for iterating on the plugin zip, never for a release: `pages.yml` publishes the
playable demo by downloading it off the Release, so a release without it leaves the site on the
previous one. The `.ps1` twin produces a byte-identical archive from the same inputs, and both
need `zip` on PATH — `Compress-Archive` cannot store symlinks at all.

**The macOS framework must still be a bundle.** `libs/macos/libssruntime.framework` is versioned,
its `Versions/Current` and bundle-root aliases are symlinks, and `zip` follows symlinks unless
given `-y`. Flattening them invalidates the code signature, so a game bundling the extracted
framework can no longer be signed or notarised. Consumers get that framework only through this
zip, and the working tree here always has the real symlinks, so a flattened bundle would ship
unnoticed. The script unpacks the finished archive and asserts they survived.

<br>

---

# SpriteStudio Player for Ren'Py のリリース手順

維持者向けです。コントリビューターがこの手順を実行することはありません（[CONTRIBUTING.md](./CONTRIBUTING.md) を参照してください）。

## ドキュメントサイトのビルド

```bash
scripts/prepare-docs.sh              # 一度だけ: .venv と docs/requirements.txt のピン
scripts/build-docs.sh                # 英語 → 日本語の順に、どちらも --strict
scripts/build-pages.sh serve=yes     # + リリース済み Web デモ -> http://localhost:8000/
```

必ず両ロケールを、英語を先に。英語ビルドは `site/ja` を含む `site/` を消すため、英語だけ建てると
古い日本語サイトが残り、壊したページが無傷に見えます。`mkdocs.base.yml` が `strict: true` を設定
します。`serve` は何も検証せず、プルリクエストでも docs はビルドされません。

`build-pages.sh` が公開サイト全体で、`pages.yml` のビルドジョブは**このスクリプト**（オプションは
すべて明示）です。`demo=download` には `gh` と、`SSPlayerForRenPy-web-demo.zip` を持つ Release が
必要です。`zip=<path>` で手渡しもでき、`demo=build` はここでエクスポートを実行します（最初の
Release ができるまではこれだけが選択肢です）。`sdk=` は `download-sdk` と `build-runtime` の
選択で、参照されるのは `demo=build` のときだけです（ダウンロードしたデモは自前のランタイムを
持っているため）。既存の `renpy-sdk/` は再取得しません。

`game/options.rpy` が `site/**` を除外している点に注意してください。docs のビルドがスクリーン
キャストを `site/*/assets/` に複製するため、除外しないと Ren'Py が `**.webm` をすべてのパッケージに
分類します。

## リリースの手順

リリースはタグです。先にタグを push し、ビルドはその後です。`v$__version__` を push し、そのタグ
から **Release** を `upload_release=true` でディスパッチします。Release の名前はタグで決まり、
それ以外からの `upload_release=true` は、Release を作らずに済ませるのではなく実行を失敗させます。
既定のディスパッチは QA ビルドで Release を作りません。出てくるのは下書きです。人が asset と
生成された notes を確認して UI から公開してください。**ベータであっても *latest* として公開します。**
README と docs が案内するリンクが `releases/latest/download/…` で、これは pre-release では解決
しないためです。

タグは `ss_renpy.__version__` と一致している必要があります。これが唯一の正典で、クリエイターが
受け取るフォルダの中に入り、リリースはここからタグ名と zip 名を読みます。

`scripts/build-release.sh` がリリースそのもので、`release.yml` のジョブは**このスクリプト**
（オプションはすべて明示）です。バージョン付きのプラグイン zip と Web デモ zip、それぞれの
バージョン無しエイリアス、そして 4 つすべてに対する `SHA256SUMS` を作ります。

```bash
scripts/build-release.sh              # 両方の asset
scripts/build-release.sh demo=skip    # プラグイン zip だけ。かなり速い
```

`demo=skip` はプラグイン zip を反復するためのもので、リリースには使いません。`pages.yml` は
Release からデモを取得して公開するため、デモの無いリリースはサイトを前のバージョンのまま残します。
`.ps1` 双子は同じ入力からバイト一致のアーカイブを作りますが、どちらも PATH 上の `zip` が必要です
（`Compress-Archive` は symlink を格納できません）。

**macOS の framework はバンドルのままでなければなりません。**
`libs/macos/libssruntime.framework` はバージョン付きで、`Versions/Current` とバンドルルートの
エイリアスは symlink です。`zip` は `-y` を付けない限り symlink を辿ります。これを平坦化すると
コード署名が無効になり、展開した framework を同梱したゲームは署名も公証もできなくなります。
利用者がこの framework を受け取る経路はこの zip だけで、ここの作業ツリーには常に本物の symlink が
あるため、平坦化されたバンドルは気づかれずに出荷されます。スクリプトは完成したアーカイブを展開し、
symlink が残っていることを表明します。
