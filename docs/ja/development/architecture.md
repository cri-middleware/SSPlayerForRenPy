# 🧩 プレイヤーの構成

SpriteStudio Player for Ren'Py を開発する人と、自分のゲームのために改造する人に向けたページです。部品をその役割で説明します。ビルド、変更した版をゲームで使う方法、Ren'Py での確かめ方は[ビルドガイド](build.md)にあります。

SpriteStudio の Player に共通すること（再生・モーションブレンド・サウンドキー・パーツトラッキングの振る舞い）は、SDK の [Player Porting Guide](https://github.com/cri-middleware/SpriteStudio-SDK/blob/HEAD/libs/ssruntime/docs/README.md) に一度だけ書いてあります。

## 層

ゲームに要るものはすべて `game/spritestudio/` として配布します。最上位に Ren'Py のスクリプト、`python/` の下に Python のパッケージ、`libs/` の下にネイティブライブラリがあります。

**Brain** は SpriteStudio-SDK の再生ランタイム `libssruntime` で、Rust で書かれています。タイムラインを進め、全パーツの姿勢を計算し、パーティクルをシミュレートして、各フレームを描画計画（FlatBuffers と平らな頂点バッファ）として返します。プレイヤーの残りの部分が、その計画を 4 つの層で Ren'Py の描画に変えます。

- **Brain への橋渡し**は、ネイティブライブラリを読み込み、その C API を `ctypes` で公開します。Web では代わりに、`renpy.emscripten` を通して Brain の WebAssembly 版と話します。同じ種類のバインディングが、インポーターが変換に使う `libssconverter` にも届きます。
- **エンジン非依存のコア**は 1 つのパックを再生し、その描画計画をジオメトリに変えます。インスタンスパーツ、エフェクト、マスク、イベント、そして Brain が渡さない `.ssab` の中身を扱います。どれも `renpy` を import しないので、`scripts/run-tests.sh` が素の CPython ですべて回せます。その下にある `.ssab` の読み取りは生成物で、手で編集しません。
- **Ren'Py 層**は、`init -10` で Brain を読み込み、`SS_*` の設定を持ち、Creator-Defined Displayable の `SSPlayer` を定義します。`SSPlayer` の `render()` が計画から `renpy.Render` を組み立て（GL2 のメッシュとシェーダー）、その周りにマスク・アタッチメント・音・セーブ対応があります。
- **便利機能**はその上にあり、それぞれ単独で外せます。すべてのパックを画像にするもの、`SSCharacter`、ヘルパー、ブラウザ（Shift+B）、診断です。自動インポーターもその 1 つで、`config.developer` が有効なときだけ走ります。

Brain の処理はネイティブです。Python で動くのは、計画をたどって Ren'Py のメッシュを頂点ごとに組み立てる部分なので、頂点数とパーティクル数が増えるほどフレームの負荷が上がります。`SS_PROFILE=1` を付けてゲームを起動すると、各フレームがジオメトリの組み立てと描画にどう分かれたかがログに出ます。

## ネイティブライブラリの読み込み元

プレイヤーは `game/spritestudio/libs/` の下の、プラットフォームごとのフォルダから Brain を探します。読み込み方はプラットフォームごとに違い、エクスポートに[エクスポートガイド](../export.md)の手順が要るのはそのためです。

| プラットフォーム | ファイル | 読み込み方と理由 |
|---|---|---|
| macOS | `libs/macos/libssruntime.framework` | `Versions/A/libssruntime` の絶対パスで読む。Ren'Py の `.app` へのパッケージングでフレームワークのシンボリックリンクが失われても解決できるようにするため |
| Windows | `libs/windows/<arch>/ssruntime.dll` | パスで読む |
| Linux | `libs/linux/<arch>/libssruntime.so` | パスで読む |
| Android | `libs/android/<abi>/libssruntime.so`。ABI の名前は NDK の呼び方 | soname で読む。Android のリンカがネイティブコードを読み込むのは、インストーラが APK の `lib/<abi>/` を展開する読み取り専用の `nativeLibraryDir` からだけなので（API 29 以降の W^X）、ゲームのファイルの中にある `.so` は読み込まれない。RAPT にはゲームからネイティブコードを足す仕組みが無いので、ライブラリは RAPT の `jniLibs` に一度だけ手でコピーする。 |
| iOS | `libs/ios/libssruntime.xcframework`（動的なもの） | プロセス自身から読む（`CDLL(None)`）。Ren'Py にはサードパーティのネイティブコードをリンクする仕組みも無いので、xcframework はアプリのターゲットに一度だけ **Embed & Sign** で追加する。renios が `MetalANGLE.xcframework` に行うのと同じ扱いで、これで dyld が起動時に読み込む。静的な xcframework はリンクはできても dead-strip され、`CDLL(None)` が何も見つけられなくなる。スライスは `.framework` バンドルなので、App Store の検証を通る。 |
| Web | `libs/web/` | SDK の wasm-bindgen 版。ゲームの開始時に `game.zip` から読むので、エクスポートの `index.html` を編集する必要が無い |

プレイヤー自身の `build.classify` の規則が、Android と iOS のライブラリをパッケージのゲームファイルから外しています。外さないと二重に入ります。デスクトップのライブラリが無くてもビルドは止まりません。パッケージはできあがり、ゲームが起動時に止まります。Brain を `init -10` で読み込むためです。

## この作りになっている理由

ここに挙げる理由はどれも複数のファイルにまたがります。詳細は、関わるコードのコメントにあります。

**アタッチメントは `SSPlayer.render()` の中で合成します。** そのフレームの姿勢を計算するのと同じパスです。`ss_attach` で付けた子がアニメから遅れないのはこのためです。別の駆動ステップにすると、誤ったタイミングで走り、前のフレームの姿勢に合わせて子を描くことがあり得ます。

**反転したパーツは、アタッチメントには回転として届きます。** パーツの姿勢は回転と 2 つの拡縮の大きさで表します（`ss_part_transform` が返すもの）。そのため反転を表す符号が落ち、左右に反転したパーツは半回転として読めます。反転を運ぶには姿勢を行列で表す必要があり、プレイヤーはそれを後の段階に残しています。ルートの変換がパーツの姿勢に届くようにするのは、ROADMAP の **Flip and offset** の項目です。

**マスクはステンシルではなくカバレッジのビットマップです。** Ren'Py の GL2 のモデル層はステンシルバッファを公開していないため、毎フレーム、マスクの書き手をオフスクリーンのビットマップに 1 つ 1 ビットで描き、マスクされる各パーツのシェーダーがその位置の書き手を再生してステンシルを組み立て直します。計画はエンジン非依存のコアに、描画と GLSL は Ren'Py 層にあり、ビットマップの大きさと品質は `SS_MASK_*` の設定で決まります。

**インポーターは Ren'Py の自動リロードに乗ります。** 自動インポーターは `init -10` で走るので、起動のたびとリロードのたびに走ります。ソースのフォルダを、Ren'Py 自身の画像と音の規則より先に `config.autoreload_functions` で引き受けます。そうしないと、保存した `.png` に対してキャッシュを捨てるだけでリロードしません。「変更された」の判定は、変換が成功した後にだけ書く記録で行います。失敗した変換も新しく見えるファイルを残すためです。別の場所で変換したパックには、`tools/ss_stamp_import.py` が同じ記録を書きます。
