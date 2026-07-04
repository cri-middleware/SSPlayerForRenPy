# 仕様と制約事項 (Limitations & Scope)

現在の SpriteStudio Player for Ren'Py における制限事項・未実装の機能の一覧です。（サポートしている機能の一覧は利用ガイドを参照してください。）

## 未実装 (Not Yet Implemented)

> [!WARNING]
> - **Text / NineSlice パーツ** — 描画されません（空表示になります）。
> - **アニメーションのブレンド / ミキシング** — アニメーション間のクロスフェードや重み付き合成。
> - **Instance / Effect パーツ内の入れ子タイムラインイベント** — ルートアニメーションの UserData / Signal / Audio のみ対応。

## 部分的にサポート (Partially Supported)

> [!WARNING]
> - **ブレンドモード** — ブレンドは Ren'Py の `config.gl_blend_func` を経由するため、GL に相当がないモード（Division, Overlay）は Mix にフォールバックします。
> - **Mesh / Instance パーツのパーツ全体カラー** — `parts_color` は Normal / Shape パーツでは各頂点に適用されますが、Mesh パーツ全体への色味付けは現状アルファのみの近似です。

## オーディオ再生 (Audio Playback)

> [!NOTE]
> 通常の使い方（順再生で、スプライトを普通に表示 / 非表示する）ではそのまま鳴ります（`sfx` ミキサー上で再生されるため、プレイヤーの音量・ミュート設定も効きます）。注意が要るのは次のエッジケースだけです。
> - **逆再生の音は鳴らない** — アニメーションが逆方向（逆再生 / 負の速度）に進むとき、その音はスキップされます（音声は逆再生できないため）。
> - **シークで音はスクラブされない** — 音は再生中に再生ヘッドがそのフレームを通過した瞬間のみ発火します。フレームのジャンプ（`ss_set_frame`）ではスクラブも、飛ばした音の再発火もしません。
> - **手動管理のプレイヤーの停止** — `hide` / `scene` なら音は即座に止まります。`SSPlayer` を変数に保持して自分で差し替える場合は、`ss_stop_audio()`（または `ss_stop()`）を呼ぶと即停止します（呼ばなくても画面から外れて約 0.25 秒以内に自動停止）。
> - **サウンドファイルを `.ssab` と同梱** — テクスチャ同様、`.ssab` からの相対で解決します。存在しないファイルはスキップされます。

## パフォーマンス・プラットフォーム (Performance & Platform)

> [!NOTE]
> **パフォーマンスについて** — 描画は `ctypes` と Creator-Defined Displayable を介して行われるため、メッシュの頂点数が極端に多いアニメーションや、大量のパーティクルが多数重なるエフェクトでは、フレームレートに影響が出る可能性があります。

> [!WARNING]
> **プラットフォーム** — デスクトップ (Windows, macOS, Linux) は現状動作します。モバイルは目前、Web は JS/WASM でサポートされています。
> - ネイティブランタイム（Rust の "Brain"）は全ターゲット向けにビルドされます — SDK のリリースワークフローが `macos` / `windows/x86_64` / `linux/x86_64` / `android/{arm64,arm32,x86_64}` / `ios`（`.xcframework`） を生成します。
> - ライブラリローダ（`ss_renpy/ssruntime.py`）はこれらのレイアウトを既に解決します（Android → `android/<abi>`、iOS はアプリへ静的リンクされたイメージにフォールバック）。**Android / iOS** で残るのは、ネイティブビルドの同梱と Ren'Py のモバイルパッケージングの配線（iOS は `.xcframework` を Xcode プロジェクトへリンク）です。
> - **Web 対応について**:
>   Web (WASM) は `ctypes` ではロードできないため、Pyodide の機能を利用した非 ctypes バインディング（`ssruntime_web.py`）で統合されています。
>   ブラウザ上で実行する場合は、WASM モジュールを Ren'Py (Pyodide) 起動前にロードしておく必要があります。ゲームの Web ビルド後、`index.html` に以下のスクリプトブロックを追加してください。
>   ```html
>   <script type="module">
>     import init, * as ss from './game/spritestudio/libs/web/ssruntime.js';
>     window.ssruntime = ss;
>     window.ssruntime_wasm = await init('./game/spritestudio/libs/web/ssruntime_bg.wasm');
>   </script>
>   ```
