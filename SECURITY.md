# Security Policy

## Supported Versions

SpriteStudio Player for Ren'Py is pre-release: nothing is published yet, and fixes are issued against `develop`.
Once there are releases, this becomes "the latest one".

| Version | Supported |
|---|---|
| `develop` | ✅ |
| Anything else | ❌ |

## Reporting a Vulnerability

**Please do not open a public GitHub Issue for a security problem.** Report it privately through the
official inquiry form:

👉 [**CRI Middleware Inquiry Form (English)**](https://www.webtech.co.jp/contact/en.html)

The English form has no file upload. If you need to send a reproduction, use the
[Japanese Help Center form](https://www.webtech.co.jp/help/ja/spritestudio7/inquiries/ssplayer_tool/),
which takes a zip of up to 8 MB.

Please include:

- What the impact is — crash, out-of-bounds read, arbitrary code execution, information disclosure.
- Steps to reproduce, ideally with a minimal `.ssab` and the smallest `.rpy` script needed.
- The player version or commit, the SpriteStudio SDK version (`scripts/SDK_VERSION.txt`), your Ren'Py
  version, and the platform.
- Whether the input that triggers it comes from a trusted source in your project or from somewhere
  untrusted (downloaded content, user-supplied files).

We will confirm receipt, tell you whether we can reproduce it, and let you know when a fix ships.
Please give us a chance to release that fix before disclosing publicly.

### Which repository to report to

Playback is driven by the runtime shared with the other SpriteStudio players, which lives in
SpriteStudio-SDK. If the same problem reproduces on a different SpriteStudio player, it is most likely
in that shared core. Report it here all the same and say so; we will route it.

## Scope Notes

The player reads binary animation data (`.ssab`) from your game's files through Ren'Py's loader —
loose or inside an `.rpa` — and hands it to the native runtime, or to its WebAssembly build on the web.
Instance parts load further packs by the names stored inside the `.ssab`. There is no network loader.

**The pack is checked, but not fully verified.** Before the runtime sees the bytes, the player checks the
`"SSAB"` identifier and walks the pack's metadata, rejecting a pack whose walk fails or that has no parts
or animations. Python's FlatBuffers library has no verifier, so this is not a structural check: a
deliberately crafted `.ssab` can still reach the runtime, which parses without validating, and cause
out-of-bounds reads in native code.

Treat `.ssab` files as part of your game, like its scripts. Loading one from an untrusted source is not a
supported configuration.

Reports about the known gap above are welcome, but it is already known — a report that demonstrates
impact beyond it is more useful.

---

# セキュリティポリシー

## サポート対象バージョン

SpriteStudio Player for Ren'Py はリリース前です。まだ何も公開されておらず、修正は `develop` に対して提供されます。リリースが始まった時点で「最新リリース」に切り替わります。

| バージョン | サポート |
|---|---|
| `develop` | ✅ |
| それ以外 | ❌ |

## 脆弱性の報告

**セキュリティに関する問題は、公開の GitHub Issue に投稿しないでください。** 再現データ（8 MB までの zip ファイル）の添付も可能なヘルプセンターより、非公開でご報告ください。

👉 [**ヘルプセンター（お問い合わせフォーム）**](https://www.webtech.co.jp/help/ja/spritestudio7/inquiries/ssplayer_tool/)

ご報告には以下を含めてください。

- 影響の内容（クラッシュ、境界外読み取り、任意コード実行、情報漏洩など）
- 再現手順。可能であれば最小限の `.ssab` と、必要最小限の `.rpy` スクリプト
- プレイヤーのバージョンまたはコミット、SpriteStudio SDK のバージョン（`scripts/SDK_VERSION.txt`）、Ren'Py のバージョン、対象プラットフォーム
- 引き金となる入力が、プロジェクト内の信頼できるデータか、信頼できない経路（ダウンロードコンテンツ、ユーザーが用意したファイル）由来か

受領の確認、再現可否、修正版の公開時期についてご連絡します。修正を公開するまでの間、公表をお待ちいただけますようお願いします。

### 報告先リポジトリの判断

再生処理は、他の SpriteStudio Player と共通のランタイムが担っており、SpriteStudio-SDK で開発されています。他の SpriteStudio Player でも同じ問題が再現する場合、共通コア側の問題である可能性が高いため、その旨を添えて本リポジトリへご報告ください。こちらで振り分けます。

## 既知の注意点

本プレイヤーは、ゲームのファイル（単体のファイル、または `.rpa` 内）から Ren'Py のローダーを通じてバイナリのアニメーションデータ（`.ssab`）を読み込み、ネイティブランタイム（Web では WebAssembly 版）へ渡します。インスタンスパーツは、`.ssab` 内に記録された名前で別のパックを読み込みます。ネットワークから読み込む仕組みはありません。

**パックは確認していますが、完全には検証していません。** ランタイムに渡す前に、`"SSAB"` 識別子を確認し、パックのメタデータをたどって、失敗したものやパーツ・アニメーションを持たないものを拒否します。Python の FlatBuffers ライブラリには verifier が無いため、これは構造の検証ではありません。意図的に細工された `.ssab` は、検証を行わないランタイムまで届き、ネイティブコードで境界外読み取りを引き起こす可能性があります。

`.ssab` はスクリプトと同じく、ゲームの一部として扱ってください。信頼できない入手元の `.ssab` の読み込みはサポート対象外です。

上記の既知の課題に関するご報告も歓迎しますが、すでに把握している内容です。これを超える影響を示すご報告のほうが有用です。
