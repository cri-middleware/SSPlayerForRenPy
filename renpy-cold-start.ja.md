# Ren'Py Player コールドスタートガイド

> このドキュメント **単体** を読めば、新規セッションが前提知識ゼロから本プロジェクトの作業を継続できることを目標にしています（= コールドスタート）。

> [!IMPORTANT]
> **一次情報（base）は SDK の Player 移植ガイド `SpriteStudio-SDK/libs/ssruntime/docs/`（README→16, 計18本）です。** 本書はそれへの導線＋本リポジトリの現状＋訂正＋ロードマップであり、仕様の正は常に移植ガイド側にあります。本書の本文（§0 以降）は当初の「ゼロから着手」プランで、**一部は実装済み**・**一部に誤りがあり下記で訂正済み**です。作業ルールは [`AGENTS.md`](./AGENTS.md)、セットアップ/構成は [`README.md`](./README.md) を参照。

## ★ 新セッションはここから（移植ガイド準拠）

### A. まず読む（順序）— `SpriteStudio-SDK/libs/ssruntime/docs/`
- **基礎（M1 必須）**: `01_introduction` → `02_architecture`（役割分担・座標API・クラス設計・必要API）→ `03_preparation` → `05_initialization`（init・寿命・**テクスチャ解決 §3.0**）→ `06_playback_control`（**dt は ms**）→ `07_render_loop`（SoA＋バッチ契約・`RenderMode::Direct`）→ `00_limitations`（制約・必読）
- **発展（M2+）**: `10_parts_color`（合成式・α）/ `08_advanced_rendering`（Mesh/Effect/Instance, CSR）/ `09_mask`（ステンシル無し→カバレッジビットマップ）/ `12_animation_blending`
- **補助**: `15_troubleshooting` / `11_optional_features` / `16_editor_integration` / `14_no_std_integration`
- スキーマ: `libs/ssruntime/SCHEMA.md`・`fbs/framedata.fbs`・`libs/ssab/fbs/ssab.fbs`／C-API: `libs/ssruntime/target/ssruntime.h`

### B. リポジトリ現状（2026-06／再ディスカバリ不要）
- **構成**: `game/spritestudio/` = ライブラリ（ドロップイン1フォルダ：`spritestudio.rpy` + `python/{ss_renpy, ss(生成bindings), flatbuffers}` + `libs/<platform>/<arch>/`）。`game/`（`script.rpy`+`sprites/`）= デモ。SDK は **submodule `./SpriteStudio-SDK`**。`scripts/` = `build-runtime.*`（ネイティブ binary）+ `deploy-examples.*`（再生データ）。`tools/` = m0_smoke / analyze / render_png（素の CPython）。
- **実装済み**: ctypes FFI（`ssruntime.py`）、`.ssab` メタ解析（`ssab_meta.py`）、描画データ（`framedata.py`：`build_normal_quads` + `decompose_quad`）、CDD（`spritestudio.rpy`）、デモ、検証ツール、ビルド/デプロイ scripts。
- **M1 まで完了・ヘッドレス検証済み**: M0 配線 OK／`decompose_quad` は純回転拡縮反転で誤差 0px（残差は本物のせん断・自由変形のみ＝M2 領域）／`render_png.py` で Basic.ssab がエディタ相当に描画／`overall`（20 pack）audit = **10 FULL / 3 PARTIAL / 3 NOT-YET**。**移植ガイドとの突き合わせ済み＝整合**。
- **未了**: 実機 Ren'Py 起動（GUI が必要、向き符号 `SS_ROTATE_SIGN`/`SS_MIRROR_AXIS` の最終確認だけ実機）／M2 以降。

### C. 確定した訂正・gotcha（移植ガイドで裏取り済み）
1. `ss_runtime_update(ctx, delta)` は **ミリ秒**（本書 §5/§6.2 の「秒」は誤り。`06_playback_control` 準拠。ラッパ `SSRuntime.update()` は秒受け取り→×1000）。
2. `DrawBatch.texture_hash` = **cellmap 名の FNV1a**（本書 §8.3 の「画像パス」は誤り。`05_initialization §3` の Godot 例 `_textures[name_hash()]` 準拠）。
3. `parts_color` の α は**ランタイムで合成済み** → `PartState.alpha` と二重に掛けない（`10_parts_color §1-3`、式は §1-4＝Mix/Mul/Add/Sub）。
4. FNV-1a を自前実装しない → **`ss_runtime_hash_string`**（`15_troubleshooting`）。
5. Mask は Ren'Py にステンシルが無い → **カバレッジビットマップ方式**（`09_mask §3-2`、最大24writer）。
6. `RenderMode::Direct` はワールド行列を **pre-bake** 済み（親子を自前で辿らない。`02`/`07`）。座標は Context API で吸収し**二重 Y 反転をしない**（`03`）。

### D. ロードマップ（移植ガイド章 → マイルストーン）
- **M1（済）**: Normal / Mix / 基本アトリビュート＋親子（`07`,`02`,`05`）。
- **M2**: ブレンド（**必須**・`02 §4`）＋ `parts_color`（`10`）＋ **model-based mesh** でせん断/自由変形を正確化。**最大リスク = Ren'Py の任意頂点メッシュ API のスパイク**（`07` の per-element 警告 + Ren'Py `Model`/mesh ドキュメント）。
- **M3**: Mesh/Bone/Deform（`08 §4`, CSR offset）。
- **M4**: Effect/Instance/Mask（`08`,`09`）。
- **次の一手**: 実機で M1 の向き確認 → M2 着手。

### E. 動かし方
```bash
git submodule update --init --recursive
scripts/build-runtime.sh                 # host debug（速い）/ build=release で macOS universal
scripts/deploy-examples.sh               # tests を .ssab 化 → game/sprites/
python3 tools/m0_smoke.py                # 配線スモーク（batches>0）
```
実機: Ren'Py SDK で `game/` を起動（手順は `README.md`）。

---

> 以下は当初の「ゼロから着手」プラン（§0〜§12）。**上記 C の訂正を優先**。詳細仕様は移植ガイドを正とすること。

---

## 0. 30 秒サマリ

- **作るもの**: SpriteStudio 7 アニメーションを [Ren'Py](https://www.renpy.org/)（Python 製ビジュアルノベルエンジン）上で再生する **Player（=「Body」）**。
- **使うもの**: 本リポジトリの `libssruntime`（=「Brain」、計算専用ライブラリ）。**Brain は改造しない。** 公開済みの **C-API** を **Python の `ctypes`** から叩いて使う。
- **データの流れ**: `.ssab`（アニメバイナリ）→ `ctypes` で C-API に投入 → 毎フレーム `update()` → `FrameData`（描画計画 = FlatBuffers）＋ SoA バッファ（頂点・行列）を取得 → Ren'Py の `Render` に描く。
- **最初の一手**: §9 の「M0 スモークテスト」。ネイティブライブラリをビルドし、`.ssab` をロードして 1 フレーム回し、`draw_batches` の件数が出れば配線成功。
- **Ren'Py 側の鍵**: `renpy.Displayable` を継承した **Creator-Defined Displayable (CDD)** の `render()` 内で描画する。座標系は **Y-Down / 左上原点 / ピクセル単位**（SS エディタと同じ向き）。

---

## 1. 前提：Brain / Body の分離（ここが全ての出発点）

SpriteStudio-SDK は **計算（Brain）** と **描画（Body）** を完全に分離しています。

| | Brain = `libssruntime` | Body = **これから作る Ren'Py Player** |
| --- | --- | --- |
| 役割 | キーフレーム補間・座標計算・再生ステート管理・描画**計画**(`DrawBatch`)の発行 | 実際の描画、テクスチャのロード、入力・音声・イベント連携 |
| 言語/形態 | Rust（`no_std`）→ C-API を持つ動的ライブラリ | Python（Ren'Py スクリプト + `ctypes`） |
| このリポジトリでの扱い | **変更しない**（`libs/ssruntime/`） | **新規の成果物**（このリポジトリ外、または別ディレクトリ） |

> **重要な原則**: Ren'Py Player は Brain の利用者にすぎません。C-API に機能が足りないと感じたら、**Player 側で回避策を書く前に Issue で相談**してください（C-API の破壊的変更は全 Player に影響するため）。役割分担の詳細は [`../02_architecture.ja.md`](../02_architecture.ja.md) を参照。

この Player は ROADMAP 上の「Phase 2: Ecosystem & Integration（既存 Player の `ssruntime` 移行）」と同じ系統の **新規 Player** です（[`../../../../ROADMAP.md`](../../../../ROADMAP.md)）。既存の Unity / Godot Player と同じく **Brain の C-API を検証する役割** も兼ねます。

---

## 2. ゴールと非ゴール

### ゴール（v1）
- デスクトップ Ren'Py（Windows / macOS / Linux）で、**Reference 方式**の `.ssab`（外部 PNG アトラスを参照）を再生できる。
- 基本アトリビュート（位置・回転・拡縮・α）＋親子階層＋主要ブレンド（Mix/Add/Mul）＋基本的なパーツカラー。
- `play / stop / pause / setFrame / setSpeed` 等の再生制御を Ren'Py スクリプトから呼べる。

### 非ゴール（v1 では見送り、§10 で段階導入）
- メッシュ／ボーン／デフォーム、パーティクルエフェクト、ステンシルマスク、テキスト、9 スライス。
- インスタンス（サブアニメ）再生。
- Ren'Py の **Web / Android / iOS** ターゲット（後述：ネイティブライブラリの組み込み方法が desktop と異なる。§4.4）。
- Embedded 方式 `.ssab`（PNG を内包）。Reference 方式を先に。

---

## 3. Ren'Py 側の必須知識（描画モデルと座標系）

Ren'Py は Python（CPython 同梱）＋ `pygame_sdl2` 上で動き、既定で **モデルベースレンダラ（GL2）** を使います。Player が知るべき API は次の通り。

### 3.1 Creator-Defined Displayable (CDD) ― 描画の入り口
`renpy.Displayable` を継承し、`render()` を override します。

```python
class SpriteStudioDisplayable(renpy.Displayable):
    def render(self, width, height, st, at):
        # width/height : 利用可能なピクセル領域
        # st           : 表示開始からの経過秒（shown timebase）。フレーム駆動はこれを使う
        # at           : アニメーション timebase
        r = renpy.Render(width, height)
        # ... ここで子 Render を blit / mesh 描画する ...
        renpy.redraw(self, 0)   # 0 秒後に再描画を要求 → 毎フレーム render() が呼ばれ続ける（=アニメ）
        return r

    def event(self, ev, x, y, st):      # 入力（任意）
        return None

    def visit(self):                     # 子 Displayable を申告（任意）
        return []
```

押さえるべき制約・API：
- `render()` は **必ず `renpy.Render` を返す**。アニメーションを続けるには毎回 `renpy.redraw(self, 0)` を呼ぶ。
- **`Render` オブジェクトを displayable のインスタンス変数に保持してはいけない**（pickle 不可のため）。フレームごとに作り直す。
- 子 displayable をテクスチャ化する: `tex = renpy.render(child, w, h, st, at)` → `renpy.Render` を返す（キャッシュされるので破壊変更しない）。
- 単純配置: `r.blit(source, (x, y))` / `r.place(d, x, y, ...)`。
- 公式: [Creator-Defined Displayables](https://www.renpy.org/doc/html/cdd.html)

### 3.2 モデルベースレンダリング ― 任意形状を描く本命
`blit` は **平行移動配置しかできません**。SpriteStudio のパーツは回転・スキュー・自由四角形変形・メッシュを持つため、フル忠実度にはモデルベース描画が必要です。

- `Render` を mesh 化して、テクスチャ＋シェーダ＋ uniform を割り当てる（コミュニティ実績パターン）:
  ```python
  rv.mesh = True
  rv.add_shader("renpy.texture")     # 組み込みのテクスチャ描画シェーダ
  rv.add_uniform("u_...", value)
  rv.add_property("gl_blend_func", (...))   # ブレンドモード（§8）
  ```
- 高レベルには `Model()` displayable（`.texture(d)` / `.shader(name)` / `.uniform(...)` / `.property(...)` / `.grid_mesh(w,h)`）。
- **座標規約（重要・SS と一致）**: 原点 = **左上**、Y 軸 = **下向き**、単位 = **仮想ピクセル**。シェーダ属性は `a_position`（仮想ピクセル）/ `a_tex_coord`。
- 公式: [Model-Based Rendering](https://www.renpy.org/doc/html/model.html)

> **未確定事項（要スパイク）**: 「**任意の頂点座標 + 任意 UV** を持つカスタムメッシュを CPU から構築する」公開 API は公式ドキュメントに明記がありません。内部的には `renpy.gl2.gl2mesh2.Mesh2` 等が存在します。M2（§10）に入る前に、対象 Ren'Py バージョンでこのメッシュ構築 API を **最優先で技術検証（スパイク）** してください。ここが本 Player の最大の技術リスクです。

### 3.3 ネイティブライブラリ呼び出し ― `ctypes`
Ren'Py は Python を同梱しているため、`ctypes` がそのまま使えます。動的ライブラリ（`.dll` / `.so` / `.dylib`）をロードして C-API を呼びます（§5）。

---

## 4. 成果物とビルド（環境準備）

### 4.1 ネイティブライブラリ（`cdylib`）をビルドする
`ssruntime` は `cdylib` をクレートタイプに持ちます（[`Cargo.toml`](../../Cargo.toml) の `crate-type = ["rlib","staticlib","cdylib"]`）。FFI 用 `no_std` ビルドで作ります：

```bash
# リポジトリルートで
cargo build --release -p ssruntime --features libc_alloc,panic-handler
# 出力:
#   Linux   : target/release/libssruntime.so
#   macOS   : target/release/libssruntime.dylib   (universal は scripts/release-macos.sh が lipo で生成)
#   Windows : target/release/ssruntime.dll        (scripts/release-windows.ps1)
```
- `libc_alloc,panic-handler` が必要な理由・各プラットフォームの作法は [`CLAUDE.md`](../../../../CLAUDE.md) の「`ssruntime` feature layout」と `scripts/release-*.sh` を参照。
- **C/C++ ヘッダ**（関数シグネチャの一次情報）は build 時に cbindgen が生成: [`../../target/ssruntime.h`](../../target/ssruntime.h)（`target/` はビルド成果物）。`ctypes` の `argtypes/restype` はこのヘッダを正とすること。

### 4.2 テスト用 `.ssab` を作る
SpriteStudio 7 プロジェクト（`.sspj`）を `ssconverter-cli` で変換します（[`cli/README.md`](../../../../cli/README.md)）：

```bash
cargo run -p ssconverter-cli -- path/to/project.sspj -o ./out
# Reference 方式（外部 PNG 参照, 既定）。-e で Embedded（v1 では使わない）
```
SpriteStudio 公式のサンプルプロジェクト（例: ボールやキャラのデモ）を最初の素材にすると良い。

### 4.3 `FrameData` を Python で読むための FlatBuffers バインディング
`ss_runtime_get_frame_data` が返すのは **FlatBuffers バイナリ**（`draw_batches` / `draw_order` 等の描画計画）。Python 側でパースが必要：

```bash
flatc --python -o ./renpy_player/generated libs/ssruntime/fbs/framedata.fbs
# 名前空間は framedata.fbs に従う（C++ アクセサは ss::runtime::GetFrameData）
```
- 併せて純 Python の `flatbuffers` ランタイム（pip パッケージ）を Ren'Py の `game/python-packages/` 等に vendoring する。
- 効果（パーティクル）を扱う段階では [`../../fbs/effect_draw_plan.fbs`](../../fbs/effect_draw_plan.fbs) も生成。
- **メタデータ**（パーツ構成・セルマップ名・テクスチャパス）は Brain が返さないため、必要になったら [`../../../ssab/fbs/ssab.fbs`](../../../ssab/fbs/ssab.fbs) も `flatc --python` で生成して `.ssab` 本体を Player 側でパースする（§7・§8）。

### 4.4 配布時のライブラリ配置（desktop）
- Ren'Py プロジェクトの `game/` 配下にプラットフォーム別ライブラリを置き、実行時に判定してロード：
  ```python
  import os, sys, ctypes, renpy
  base = os.path.join(renpy.config.gamedir, "libs")
  if renpy.windows:   name = "ssruntime.dll"
  elif renpy.macintosh: name = "libssruntime.dylib"
  else:               name = "libssruntime.so"
  lib = ctypes.CDLL(os.path.join(base, name))
  ```
- macOS は `lipo` で universal（arm64+x86_64）にしておくと両対応（`scripts/release-macos.sh` 参照）。
- **Web/Android/iOS は別アプローチ**（WASM 版や静的リンクが必要）になるため v1 非対応（§2）。

---

## 5. C-API の最小ライフサイクル（`ctypes` 実装の骨格）

呼び出し順は [`../README.ja.md`](../README.ja.md) / `ssruntime.h` の通り。`ctypes` での最小形：

```python
import ctypes as C

lib = C.CDLL(lib_path)

# --- シグネチャ宣言（抜粋。全関数は ssruntime.h を正とする） ---
lib.ss_runtime_create.restype = C.c_void_p
lib.ss_resource_create_copy.argtypes = [C.c_char_p, C.c_size_t]
lib.ss_resource_create_copy.restype  = C.c_void_p
lib.ss_runtime_bind_resource.argtypes = [C.c_void_p, C.c_void_p]
lib.ss_runtime_bind_resource.restype  = C.c_bool
lib.ss_runtime_setup_animation.argtypes = [C.c_void_p, C.c_char_p]
lib.ss_runtime_setup_animation.restype  = C.c_bool
lib.ss_runtime_set_render_mode.argtypes = [C.c_void_p, C.c_uint8]      # 0=Direct, 1=SceneGraph
lib.ss_context_set_coordinate_system.argtypes = [C.c_void_p, C.c_int]  # 0=YUp, 1=YDown
lib.ss_runtime_play.argtypes   = [C.c_void_p]
lib.ss_runtime_update.argtypes = [C.c_void_p, C.c_float]
lib.ss_runtime_update.restype  = C.c_float
lib.ss_runtime_get_frame_data.argtypes = [
    C.c_void_p, C.c_float, C.POINTER(C.POINTER(C.c_ubyte)), C.POINTER(C.c_size_t)]

# --- ライフサイクル ---
ctx = lib.ss_runtime_create()
lib.ss_runtime_set_render_mode(ctx, 0)            # Direct（SoA + バッチ前提。§7）
lib.ss_context_set_coordinate_system(ctx, 1)      # YDown（Ren'Py 画面に合わせる。§8）

ssab_bytes = open("anim.ssab", "rb").read()       # copy 方式: Rust 側にコピーされる
res = lib.ss_resource_create_copy(ssab_bytes, len(ssab_bytes))
assert lib.ss_runtime_bind_resource(ctx, res)
assert lib.ss_runtime_setup_animation(ctx, b"Wait")
lib.ss_runtime_play(ctx)

# --- 毎フレーム ---
frame_no = lib.ss_runtime_update(ctx, dt)         # ★dt はミリ秒（秒ではない）。戻り値は現在フレーム(float)
data_ptr = C.POINTER(C.c_ubyte)()
data_len = C.c_size_t()
lib.ss_runtime_get_frame_data(ctx, frame_no, C.byref(data_ptr), C.byref(data_len))
fb = C.string_at(data_ptr, data_len.value)        # FlatBuffers を Python bytes にコピー → パース可

# --- 破棄（順序厳守） ---
lib.ss_runtime_destroy(ctx)
lib.ss_resource_destroy(res)
```

> **ライフタイムの鉄則（[`../00_limitations.ja.md`](../00_limitations.ja.md)）**
> - `bind_resource` した **resource は context より先に破棄しない**（use-after-free）。
> - v1 では **`ss_resource_create_copy`（コピー方式）を推奨**。`borrow` 方式は元の `bytes` が resource より長生きする必要があり、Python の GC で足を撃ちやすい。最適化は後回し。
> - SoA バッファ（§7 のポインタ）は **次の Brain 呼び出しまでしか有効でない**。フレームをまたいで保持しない。

主要関数の早見（全量は `ssruntime.h`）：

| 用途 | 関数 |
| --- | --- |
| 生成/破棄 | `ss_runtime_create` / `ss_runtime_destroy`, `ss_resource_create_copy`/`_borrow` / `ss_resource_destroy`, `ss_runtime_bind_resource` |
| アニメ選択 | `ss_runtime_setup_animation(name)` / `_by_hash(u32)` |
| 再生制御 | `ss_runtime_play` / `_play_with_start_frame` / `pause` / `stop` / `set_frame_no` / `next_frame` / `prev_frame` |
| 再生設定 | `set_loop(-1=無限)` / `set_animation_speed` / `set_frame_rate` / `set_playback_direction` / `set_animation_section` |
| 状態取得 | `get_frame_no` / `is_playing` / `is_end_frame_reached` / `get_total`系 / `get_fps` |
| フレーム更新 | `ss_runtime_update(dt) -> frame` |
| 描画データ | `ss_runtime_get_frame_data` ＋ SoA getter 群（§7） |
| 座標系 | `ss_context_set_coordinate_system` / `_origin` / `_unit`, `ss_runtime_set_render_mode` |
| イベント | `get_passed_event_*`, `get_active_event_instance`, `get_active_effect_event`（§? は §6） |

---

## 6. 再生制御・イベントを Ren'Py へ橋渡しする

### 6.1 利用者向け Player API（推奨インターフェース）
CDD をラップする「表向き Player クラス」を用意し、最低限これらを提供（[`../02_architecture.ja.md`](../02_architecture.ja.md) §6）：
`play(name, loop, start_frame)` / `stop()` / `pause()` / `resume()` / `is_playing()` / `set_frame()` / `get_frame()` / `set_speed()` / `get_total_frames()` / `set_part_visible(name, visible)`。

### 6.2 時間の進め方
`render(self, w, h, st, at)` の `st`（表示開始からの経過**秒**）から **前フレームとの差分**を求め、**ミリ秒に変換して（×1000）** `ss_runtime_update(ctx, dt_ms)` に渡す（C-API はミリ秒入力）。`renpy.redraw(self, 0)` で継続駆動。

### 6.3 イベント（UserData / Signal / アニメ終了）
毎フレーム、Brain からイベントをポーリングして Ren'Py 側に通知する：
- `ss_runtime_get_passed_event_count` → `ss_runtime_get_passed_event_index(i)`。
- これらを Ren'Py のコールバック（利用者が登録した Python 関数）や `renpy.restart_interaction()` 等に接続。アニメ終了は `ss_runtime_is_end_frame_reached` / `is_playing` で判定。
- **音声**は Brain が「再生指示イベント」のみ出すので、Player が `renpy.play(...)` 等で実再生（[`../00_limitations.ja.md`](../00_limitations.ja.md)）。

---

## 7. `FrameData` / `DrawBatch` の歩き方（Python）

`RenderMode::Direct`（推奨）では、描画は **「FlatBuffers で計画を読み、SoA バッファで実データを引く」** ハイブリッド方式（[`../07_render_loop.ja.md`](../07_render_loop.ja.md)）。

### 7.1 取得するもの
| データ | 取得方法 | 形 |
| --- | --- | --- |
| 描画計画 | `FrameData`(FlatBuffers) の `draw_batches` / `draw_order` / `mask_indices` | パースして読む |
| パーツ状態 | `FrameData.parts`（α/hide 等）, `FrameData.parts_color`（頂点カラー, **α 乗算済み**） | パースして読む |
| ワールド行列 | `ss_runtime_get_world_matrices` | `16 float / part`（SoA, ポインタ） |
| ローカル頂点 | `ss_runtime_get_local_vertices` | `10 float / part`（5頂点×xy。`LOCAL_VERTICES_STRIDE=10`） |
| セルメタ | `ss_runtime_get_cell_meta` | `6 float / part`：`[pivot_x, pivot_y, size_w, size_h, rect_left, rect_top]`（テクスチャピクセル空間） |
| ローカル UV | `ss_runtime_get_local_uvs` | `10 float / part` |
| メッシュ系 | `ss_runtime_get_mesh_vertices_x/_y`, `_uvs`, `_indices` ＋ `_offsets`(CSR) | M3 で使用 |

> **近道**: `cell_meta` の `[rect_left, rect_top, size_w, size_h]` は **アトラス上の切り出し矩形そのもの**。Normal パーツの UV/クロップは `.ssab` のセルテーブルをパースしなくても **runtime だけで** 得られる（M1 を素早く立ち上げられる）。テクスチャの**どのファイルか**は `DrawBatch.texture_hash` で識別する（§8.3）。

`ctypes` での SoA 取得（numpy ビューで参照、コピー回避）：
```python
def soa(getter, ctx, dtype=C.c_float):
    p = C.POINTER(dtype)(); n = C.c_size_t()
    getter(ctx, C.byref(p), C.byref(n))
    import numpy as np
    return np.ctypeslib.as_array(p, shape=(n.value,))   # 次の Brain 呼び出しまで有効
```

### 7.2 バッチ走査ループ
```python
fd = FrameData.GetRootAs(fb, 0)                 # flatc 生成バインディング
order = fd.DrawOrderAsNumpy()                   # [ushort] parts への index
wm = soa(lib.ss_runtime_get_world_matrices, ctx)   # 16/part
lv = soa(lib.ss_runtime_get_local_vertices, ctx)   # 10/part
cm = soa(lib.ss_runtime_get_cell_meta, ctx)        # 6/part

for b in range(fd.DrawBatchesLength()):
    batch = fd.DrawBatches(b)
    # batch.StartRank(), batch.Count(), batch.TextureHash(),
    # batch.BlendType(), batch.Kind(), batch.Flags()
    bind_texture(batch.TextureHash())            # §8.3
    set_blend(batch.BlendType())                 # §8.2
    for k in range(batch.Count()):
        p = order[batch.StartRank() + k]
        m = wm[p*16 : p*16+16]                   # 4x4 ワールド行列
        v = lv[p*10 : p*10+10]                   # ローカル頂点(5×xy)
        emit_quad(batch.Kind(), m, v, cm[p*6 : p*6+6])
```
- `DrawBatchKind`: `Normal / Shape / Instance / Effect / Mesh / Text / Nines / Mask`。v1 は `Normal` のみ実装し、他 kind のバッチは **スキップ**（または将来 TODO ログ）。
- `flags & 0x01 = MASK_INFLUENCE`（このスライスはマスク対象）。
- スキーマの一次情報: [`../../SCHEMA.md`](../../SCHEMA.md)（`PartState` / `DrawBatch` / `DrawBatchKind` / `UpdateAttributeFlags` 全フィールド）と [`../../fbs/framedata.fbs`](../../fbs/framedata.fbs)。

> **パフォーマンス注意**: FlatBuffers の **per-element アクセサ**（`parts_color` の入れ子等）は高水準ホストで重い（[`../07_render_loop.ja.md`](../07_render_loop.ja.md) §2.1 の実測警告）。VN 規模（数体・中程度のパーツ数）では v1 はアクセサ直読みで可。多体・高負荷化したら、固定長 struct ベクタ（`parts`/`parts_color`/`draw_batches`）を **numpy の構造化 dtype で生読み**する最適化に進む。

---

## 8. 座標系・ブレンド・テクスチャの「合わせ込み」

### 8.1 座標系（最重要・ミスの温床）
SS / `libssruntime` の標準は **Y-Up / 中心原点 / ピクセル**。Ren'Py の画面は **Y-Down / 左上原点 / ピクセル**。Player 側で手計算せず、**Context 設定 API で吸収**する（[`../02_architecture.ja.md`](../02_architecture.ja.md) §2）：

```python
lib.ss_context_set_coordinate_system(ctx, 1)  # 1=YDown → Y と回転符号を内部で反転（Ren'Py に一致）
lib.ss_context_set_origin(ctx, 0)             # 0=Center を維持し、CDD 側でキャラ配置点へ平行移動するのが VN 向き
lib.ss_context_set_unit(ctx, 0)               # 0=Pixel
```
- CDD は `render(w,h,...)` の領域中央など任意の基準点に、得られた頂点を **平行移動**して配置する。
- Y-Down にしておけば回転方向も Ren'Py と一致するため、後段の符号反転が不要。

### 8.2 ブレンドモード
SS の `BlendType`（`Mix / Mul / Add / Sub / Mulalpha / Screen / Exclusion / Invert / Mul2 / Div2 / Screen2 / Overlay2`）を Ren'Py に対応付ける：
- **Mix / Add / Mul / Screen** などの固定機能で表せるものは、`Render.add_property("gl_blend_func", (...))`、または Transform の `blend "add"`（`config.gl_blend_func` 参照）で対応。
- **Sub / Exclusion / Invert / Overlay2** 等、固定機能で表せないものは **カスタムシェーダ**が必要（`renpy.register_shader`）。v1 は Mix/Add/Mul に絞り、残りは M2 以降で TODO。

### 8.3 テクスチャ解決（`texture_hash` → 実ファイル）
`DrawBatch.texture_hash` は **セルマップ名（`.ssce` 抜き）の FNV1a ハッシュ**（＝ `CellMap.name_hash`。画像パスのハッシュではない）。実ファイルに解決するには：
1. `.ssab` メタデータ（`ssab.fbs`）をパースして **セルマップ名一覧**を取得し、各名の `ss_runtime_hash_string` を前計算 → `hash → ファイルパス` の辞書を作る。
2. ファイル参照文字列の構成規則は [`../05_initialization.ja.md`](../05_initialization.ja.md) §3.0 を参照（Reference 方式の前提）。
3. 解決した PNG を Ren'Py の `Image(path)` 等でロードし、`renpy.render(...)` でテクスチャ化。`cell_meta` の矩形でアトラスから切り出す。
- **M1 の手抜き**: アトラスが 1 枚だけのアニメなら、`texture_hash → 既知の 1 ファイル` をハードコードしてメタデータパースを後回しにできる。

### 8.4 α（重要）
`parts_color` の `rgba.a` は **パーツ階層 α が乗算済み**。Player 側で**二重に α を掛けない**（[`../../SCHEMA.md`](../../SCHEMA.md)）。`parts_color` を持たないパーツは `PartState.alpha` を使う。

---

## 9. 段階的スコープとマイルストーン（最初の一手から）

各マイルストーンは「動く成果物」を必ず持つこと。

| M | ゴール | 主な内容 | 完了判定 |
| --- | --- | --- | --- |
| **M0** | **配線確認（スモークテスト）** | `ctypes` でライブラリ load → `.ssab` を copy ロード → `setup_animation` → `update` 1 回 → `get_frame_data` → `draw_batches` 件数を print。**Ren'Py 不要**（素の Python でも可） | バッチ件数 > 0 が出る |
| **M1** | **Normal パーツが画面に出る（垂直スライス）** | CDD 実装。`Normal` バッチのみ、`Render.blit` ＋ Transform（pos/rotate/zoom/alpha）でアトラス切り出しを配置。`cell_meta` で矩形取得、テクスチャはハードコード可。Y-Down 設定 | デモが Ren'Py 画面でアニメ再生される |
| **M2** | **フル忠実度の Normal 描画** | モデルベース mesh 描画へ移行（自由四角形変形・スキュー・`gl_blend_func` ブレンド・頂点カラー）。`texture_hash` 解決を実装（メタデータパース）。再生制御 API・イベント橋渡し | エディタ/既存 Player と見た目一致 |
| **M3** | **メッシュ/ボーン/デフォーム** | `Mesh` kind、`mesh_*` SoA、CSR offset の三角形描画 | メッシュ部分が崩れず再生 |
| **M4** | **エフェクト/インスタンス/マスク** | `EffectDrawPlan`（[`../../fbs/effect_draw_plan.fbs`](../../fbs/effect_draw_plan.fbs)）、インスタンススロット、`Mask` kind（Ren'Py でのステンシル相当は要設計） | 高度アニメが再生 |

### 9.1 M0 の参考コード（literal な「最初の一手」）
§5 のライフサイクルをそのまま 1 ファイルにまとめ、最後に：
```python
fd = FrameData.GetRootAs(fb, 0)
print("frame:", frame_no, "batches:", fd.DrawBatchesLength(), "parts:", fd.PartsLength())
```
が動けば、**Brain との配線は完成**。あとは描画（M1）に集中できる。

---

## 10. 既知の制限・落とし穴（着手前に必読）

[`../00_limitations.ja.md`](../00_limitations.ja.md) の全項目に加え、Ren'Py / Python 特有の注意：

- **入力検証なし**: Brain は `.ssab` を検証しない。信頼できるアセットのみロード（ネット配布時は Player 側で整合性チェック）。
- **リソース寿命**: `resource` は `context` より先に破棄しない。`borrow` 方式なら元 `bytes` を生かし続ける（v1 は copy 推奨）。
- **`independent=true` パーツ**: 逆再生・シークで破綻。SS 制作側で避けるのが基本。
- **シーク時のイベント**: `set_frame_no` で飛ばしたフレーム間のイベントは発火しない。
- **Python のパフォーマンス**: 毎フレーム多数パーツを純 Python でループすると重い。numpy で一括処理し、per-element アクセサを避ける（§7.2）。GIL があるためマルチスレッド前提の最適化は効きにくい。
- **モデルベース mesh API の不確実性（§3.2）**: M2 着手前に対象 Ren'Py バージョンで必ずスパイク。
- **マスク**: Ren'Py はステンシルを直接公開しない。`Mask` kind の実装方式（カバレッジビットマップ等）は別途設計（[`../09_mask.ja.md`](../09_mask.ja.md) のコントラクトを参照）。
- **Web/Android/iOS**: ネイティブ `cdylib` をそのまま使えない。v1 は desktop 限定。

---

## 11. 検証（どう確かめるか）

- **M0**: 素の Python（または Ren'Py 同梱 Python）でスモークテスト実行 → バッチ件数・パーツ数・経時でフレーム番号が進むことを確認。
- **M1 以降**: Ren'Py SDK で最小プロジェクトを作り、`game/` に `.rpy`（CDD）＋ ネイティブライブラリ ＋ `.ssab` ＋ PNG を置いて Launcher から起動。画面再生を目視。フレームカウンタを画面表示しておくとデバッグしやすい。
- **正解との突き合わせ**: SpriteStudio エディタのプレビュー、または本 SDK の **Web(WASM) / Godot Player** の表示と比較（同一 `.ssab`・同一フレームで pose 一致を確認）。
- Brain 側を一切変更していないこと（`git status` で `libs/ssruntime/` に差分が無いこと）を都度確認。

---

## 12. 参照リンク

**このリポジトリ（一次情報）**
- Player 実装ガイド目次: [`../README.ja.md`](../README.ja.md)
- 役割分担・実装方針: [`../02_architecture.ja.md`](../02_architecture.ja.md)
- データロードと初期化（ファイル参照規則 §3.0）: [`../05_initialization.ja.md`](../05_initialization.ja.md)
- 再生制御とイベント: [`../06_playback_control.ja.md`](../06_playback_control.ja.md)
- レンダリングループ／バッチ契約: [`../07_render_loop.ja.md`](../07_render_loop.ja.md)
- 高度な描画（Instance/Effect/Mesh）: [`../08_advanced_rendering.ja.md`](../08_advanced_rendering.ja.md)
- マスク: [`../09_mask.ja.md`](../09_mask.ja.md)
- 制限事項: [`../00_limitations.ja.md`](../00_limitations.ja.md)
- FrameData スキーマ: [`../../SCHEMA.md`](../../SCHEMA.md) / `.fbs`: [`../../fbs/framedata.fbs`](../../fbs/framedata.fbs), [`../../fbs/effect_draw_plan.fbs`](../../fbs/effect_draw_plan.fbs)
- メタデータ(`.ssab`)スキーマ: [`../../../ssab/fbs/ssab.fbs`](../../../ssab/fbs/ssab.fbs)
- C ヘッダ（生成物）: [`../../target/ssruntime.h`](../../target/ssruntime.h)
- 変換 CLI: [`../../../../cli/README.md`](../../../../cli/README.md)
- ビルド/feature 規約: [`../../../../CLAUDE.md`](../../../../CLAUDE.md)・`scripts/release-*.sh`

**Ren'Py 公式**
- [Creator-Defined Displayables](https://www.renpy.org/doc/html/cdd.html)
- [Model-Based Rendering](https://www.renpy.org/doc/html/model.html)
- [Displayables](https://www.renpy.org/doc/html/displayables.html)
- [`ctypes` — A foreign function library for Python](https://docs.python.org/3/library/ctypes.html)
