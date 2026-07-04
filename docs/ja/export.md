# ゲームのエクスポート

SpriteStudio Player for Ren'Py を組み込んだゲームを各プラットフォーム向けにエクスポートする手順です。

## Web (ブラウザ) 向けエクスポート

Ren'Py の標準 Web エクスポート機能（Pyodide / WASM）を利用して、ブラウザ上で動作するゲームを出力できます。
本ライブラリは内部で `ssruntime_web.py` による非 ctypes な JS バインディングを自動的に使用するため、Python コードの変更は不要です。

> **⚠️ Ren'Py の Web エクスポートは、そのままでは動きません。**
> Web レンダラは別の WASM モジュール（`ssruntime.js` / `ssruntime_bg.wasm`）を読み込みます。
> Ren'Py のエクスポータはこれを認識しないため、**エクスポートのたびに 2 つの後処理が必須**です
> ——`index.html` の編集（手順3）と、WASM アセットの実ファイル配置（手順4）。
> これを行わないと、ブラウザの console に
> `Cannot read properties of undefined (reading 'SSRuntimeContext')`
> （＝ `window.ssruntime` が未ロード）が出て、何も描画されません。
> エクスポータは**実行のたびに `index.html` を作り直し `game.zip` を再パッケージ**するため、
> この 2 手順は**毎回のエクスポート後に再適用**する必要があります。

### 自動ビルド（推奨）

エクスポートと 2 つの後処理（手順3・4）をまとめて行うヘルパースクリプトを用意しています。冪等なので何度実行しても安全です:

```bash
scripts/deploy-web.sh [dest_dir]      # 省略時の出力先: web_out
# Windows:
scripts\deploy-web.ps1 [dest_dir]
```

その後、出力先を HTTP で配信してください（後述の[動作確認](#動作確認)参照）。手作業で行いたい場合は、以下の手順に従ってください。

### 手動の手順

1. **Web エクスポート環境のセットアップ**
   Ren'Py で Web エクスポートを行うためのパッケージをインストールします。
   （Ren'Py ランチャーからダウンロードするか、プロジェクトの `scripts/fetch-renpy-web.sh` を使用してください）

2. **エクスポートの実行**
   Ren'Py ランチャーの「Web (Beta)」メニューから「Build Web Application」を選択し、エクスポートを実行します。
   （CLI の場合は `./renpy.sh launcher web_build <project_dir> --dest <out>` を実行します）

3. **⚠️ 必須: `index.html` への JS/WASM ロード用スクリプトの追加**
   生成されたフォルダ内の `index.html` を開き、Ren'Py の起動処理の**前**
   （`<script src="renpy-pre.js"></script>` の直前の行）に以下のコードを追記してください。
   これにより、SSPlayer のレンダリングを担う WASM バインディングがゲーム起動前に読み込まれます。
   **この追記は必須で、再エクスポートのたびに消えます——毎回追記し直してください。**

   ```html
   <script type="module">
     import init, * as ss from './game/spritestudio/libs/web/ssruntime.js';
     window.ssruntime = ss;
     window.ssruntime_wasm = await init('./game/spritestudio/libs/web/ssruntime_bg.wasm');
   </script>
   ```

4. **⚠️ 必須: Web アセット (`ssruntime.js` / `ssruntime_bg.wasm`) の配置**
   エクスポート時に `game` ディレクトリは `game.zip` に圧縮されるため、`index.html` 内の
   ブラウザネイティブの ES モジュール `import` からは `game.zip` 内のランタイムを読み込めません。
   そのため、`game/spritestudio/libs/web/` の `ssruntime.js` と `ssruntime_bg.wasm` を、
   出力先フォルダの同じパス（`web_out/game/spritestudio/libs/web/` 等）に**実ファイルとしてコピー**してください。
   手順3の import パスは、この配置先と**完全に一致**させる必要があります。

### 動作確認

* **`file://` ではなく HTTP で配信してください。** ES モジュールと WASM はファイルシステムからは読み込めません。
  静的サーバなら何でも構いませんが、MIME を正しく返す必要があります:
  `.js` → `application/javascript`、`.wasm` → `application/wasm`。
  Ren'Py 純正の web サーバ（`renpy.sh launcher web_build <dir> --launch`、または
  ランチャーの「Web (Beta)」ページ）はこれを満たします。
* **再テスト時は Service Worker をクリアしてください。** Ren'Py の Web ビルドは `game.zip` を
  キャッシュする service worker を登録します。再エクスポート後、ブラウザが**古い**ビルドを
  返すことがあります。DevTools → Application で service worker を **Unregister** し、
  **Clear site data** してからハードリロード（またはシークレットウィンドウ）してください。

### 仕様に関する注意点

* **`.ssab` / `.wav` / `.mp3` のパッケージング**
  Ren'Py は Web エクスポート時に、デフォルトでは `.png` や `.ogg` など限られた拡張子のファイルしか出力用アーカイブ (`game.zip`) に含めません。
  本ライブラリでは `spritestudio.rpy` 内にて `build.classify('**.ssab', 'all')`・`build.classify('**.wav', 'all')`・`build.classify('**.mp3', 'all')` を定義しているため、開発者が自身で `options.rpy` 等を変更しなくても、必要なアセットが正しくパッケージングされます。

## モバイル (Android / iOS) および デスクトップ

*(後日追加予定)*
