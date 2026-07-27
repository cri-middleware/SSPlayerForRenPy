# 再生と制御 (Usage Guide)

SpriteStudio Player for Ren'Py では、SpriteStudioのアニメーションをRen'Py上で非常に柔軟に制御できます。画面への単純な描画から、キャラクターの立ち絵としての統合、イベントコールバックまで、目的に応じた使い方を解説します。

> [!IMPORTANT]
> **`.ssab` の置き場所について**
> コンバート済みの `.ssab` とそのテクスチャ（`.png`）、および参照する外部インスタンスパックは、すべて **同じフォルダに同居** します（オートインポーターは `game/ss_assets/<プロジェクト名>/` に出力します）。プレイヤーは関連リソースを `.ssab` と同じフォルダから解決するため、テクスチャ用のフォルダを別途指定する必要はありません。

---

## 1. 最も簡単な再生（Screenからの呼び出し）
`SSPlayer` クラスは Ren'Py の Displayable（描画オブジェクト）として振る舞うため、スクリーン内に `add` して直接表示するのが最もシンプルです。

```renpy
screen demo():
    # 第1引数は .ssab のパス（game/ からの相対パス）
    add SSPlayer("ss_assets/Ringo/Ringo.ssab") xalign 0.5 yalign 0.5
```

### 基本パラメータ
- **第1引数**: 再生する `.ssab` のパス（`game/` からの相対、例 `"ss_assets/Ringo/Ringo.ssab"`）。`.ssab` とそのテクスチャ・外部インスタンスパックは同居しているので、これだけで関連リソースも解決されます。**`.rpa` アーカイブ内の `.ssab` も読み込めます**（Ren'Py のローダ経由）。
- **`animation` (省略可能)**: 初期状態で再生するアニメーション名。省略時はデータ内の最初のアニメーションが再生されます。**存在しない名前を渡すと初回表示時にエラー**（有効なアニメーション名の一覧つき）になります。
- **`loop` (省略可能)**: 再生回数。`-1`（既定）で無限ループ、`1` で1回再生、`N` でN回再生。`0` は `-1`（無限）の別名で、「再生しない」ではありません。
- **`speed` (省略可能)**: 再生速度の倍率（既定 `1.0`）。
- **`size` (省略可能)**: `(w, h)`（または正方形なら数値1つ）を渡すと、その**箱サイズの普通の画像**として振る舞い、`xalign`/`xpos`/`pos` やコンテナ配置がそのまま効きます（アニメは箱の中央に描画）。省略時は画面全体を占有するので `xoffset`/`yoffset` で位置調整します。どちらの場合も `zoom`/`Transform` での拡大縮小は効きます。

```renpy
# size を指定すれば align で配置できる
add SSPlayer("ss_assets/Ringo/Ringo.ssab", size=(400, 600)) xalign 0.5 yalign 1.0
```

> [!TIP]
> どのパック／アニメーションを使えばいいか分からないときは、開発者モードで **Shift+B** から **アセットブラウザ** を開けば、全 `.ssab` を一覧・ライブプレビューし、貼り付け可能なスニペットをコピーできます。詳細は下の **アセットブラウザ**（§9）を参照。

> [!NOTE]
> 旧 `sprites_subdir` 引数は後方互換のために残っていますが、パス指定で不要（非推奨）です。

---

## 2. 立ち絵としての利用 (image 宣言と Character 連携)
Ren'Pyの `image` ステートメントと組み合わせることで、ノベルゲームにおける**キャラクターの立ち絵**として強力に機能します。`aliases` 引数を使うと、Ren'Pyのアトリビュート名とSpriteStudio内のモーション名を紐付けることができます。

```renpy
# キャラクターの定義（.ssab パスを指定）
image ringo = SSPlayer(
    "ss_assets/Ringo/Ringo.ssab",
    aliases={
        "idle": "wait1",    # 'idle' が呼ばれたら 'wait1' モーションを再生
        "happy": "joy",
        "walk": "walk",
        "attack": ["attack1", "wait1"] # リストを渡すと順番に連続再生！
    }
)

define r = Character("Ringo", image="ringo")

label start:
    # デフォルトの立ち絵を表示（idleモーション）
    show ringo idle:
        yoffset 200

    r happy "アトリビュートを変えるだけでモーションが切り替わるよ！"

    # Transform (移動) と組み合わせて歩かせる
    show ringo walk:
        xoffset -400 yoffset 200
    with move

    r attack "攻撃！ (attack1 が終わると自動的に wait1 に戻ります)"
```

### もっと簡単に：喋るキャラ (`SSCharacter`)
`SSCharacter` を使うと、**台詞を喋っている間は talk、止まれば idle に自動で切り替わる**“生きたキャラ”を1行で定義できます。`image` 宣言と `Character` の準備、しゃべりへの同期がまとめて行われ、行ごとの Python は不要です。

```renpy
# 画像登録 + Character + 口パク連動をまとめて定義（タグは .ssab の stem = "ringo"）
define ringo = SSCharacter(
    "ss_assets/Ringo/Ringo.ssab",
    talk="talk",     # 喋っている間に再生するアニメ名
    idle="wait1",    # 無音時のアニメ名
)

label start:
    show ringo            # タグ "ringo" で表示
    ringo "やあ。喋っている間は talk、終わると idle に戻るよ。"
```

- 画像タグは `.ssab` のファイル名 stem を小文字化したもの（例 `"ringo"`）。`tag=` で上書き可。
- `aliases=`（感情など）や `size=`（`xalign` を効かせる箱サイズ）も渡せます。
- 口パクの開始/終了タイミングは `start` / `stop`（Character のコールバックイベント名）で調整可能。

> [!WARNING]
> **v1の制限**: 喋っている間は talk/idle が属性を置き換えるため、`show ringo happy` のような感情属性は talk 中は反映されず、終了後 `idle` に戻ります（感情別の talk は今後対応）。

---

## 3. エフェクトとしての利用 (ループ回数の制御)
魔法の爆発やヒットエフェクトなど、一度だけ再生して終わるアニメーションの場合は、`loop` 引数で再生回数を制限できます。

```renpy
image hit_effect = SSPlayer(
    "ss_assets/ParticleEffect/e038.ssab",
    animation="hit",
    loop=1 # 1回再生したら終了して画面から消える（または最後のフレームで止まる）
)

label battle:
    # 攻撃に合わせて指定位置にエフェクトを表示
    show hit_effect:
        xoffset -150 yoffset 50
    "ドガァン！"
```

---

## 4. Pythonコードからの動的制御
ゲーム中の処理に応じてPython（スクリプト）から直接アニメーションを切り替えたり、情報を取得したりすることも可能です。

```renpy
$ player = SSPlayer("ss_assets/Ringo/Ringo.ssab")

# 収録されているすべてのアニメーション名リストを取得
$ anim_names = player.ss_animation_names()

# 現在再生中のアニメーション名を取得
$ current_anim = player.ss_get_animation()

# 任意のアニメーションへの切り替え（読み込み＋頭出し → 再生）
$ player.ss_play("run")
```

- **読み込みと再生の分離**: `ss_set_animation("run")` はアニメーションを読み込んでポーズ（頭出し）するだけで、再生は開始しません。`ss_play()` で再生を開始します。
- **再生制御**: `ss_pause()` / `ss_resume()` / `ss_stop()`、フレーム操作 `ss_set_frame()` / `ss_get_frame()`、速度 `ss_set_speed()`、ループ `ss_set_loop()` などが利用できます。
- **パーツ照会**: `ss_part_transform("part名")` で直近フレームのパーツのローカル変換（x/y/回転/スケール）を取得できます。パーツ照会 API の全体と、表示物をパーツに追従させる方法は下の **パーツトラッキング**（§5）を参照。

---

## 5. パーツトラッキング（指定パーツへの追従）

指定したパーツに、ユーザーが用意した表示物（武器・エフェクト・当たり判定の目印など）を毎フレーム追従させる機能です。本プレーヤーには追従先を差し込むシーンツリーが無いため、子はそのパーツの位置で**プレイヤー自身の描画結果に合成**されます。子とその中身はユーザーが所有し、プレイヤーはそれを描画するだけです。またプレイヤーの描画に内包されるので、プレイヤーに掛けた `at` 節・`Transform`・`zoom` はそのまま子にも及びます。

> 子には任意の Ren'Py 表示物を指定できます。画像名でも `"file.png"` でも `Text(...)`・`Solid(...)`・`Transform(...)` でも、別の `SSPlayer` でも構いません。

コンストラクタの `attachments=` に `{パーツ名: 子}` の辞書を渡して設定します。

```renpy
image ringo = SSPlayer(
    "ss_assets/Ringo/Ringo.ssab",
    attachments={"head": Text("！", size=40), "hand_r": "sword.png"},
)
```

| 設定 | 説明 |
|---|---|
| **part** | 追従対象のパーツ名（`.ssab` の PartData 名）。`ss_part_names()` で一覧でき、アセットブラウザ (Shift+B) でもパックごとに確認できます |
| **child** | 追従させる表示物 |
| **anchor** | 子のどの点をパーツに合わせるか。子のサイズに対する 0〜1 の割合で指定します。`(0.5, 0.5)` で中心（既定）、`(0.5, 1.0)` なら下端がパーツ位置に来ます（持ち物の握り）。回転・拡縮の基準点も兼ねます |
| **angle** | パーツ自身の回転に加算する固定の回転オフセット（度、時計回りが正）。子の基準の向きをパーツのローカル軸に合わせるために使います |
| **drive_scale** | ON でパーツの拡縮も反映。OFF（既定）は位置と回転のみです |
| **on_hide** | パーツが hide のフレームでの挙動。`"follow"`（描画を継続。既定）/ `"hide"`（そのフレームは子を消す） |

### スクリプトからの登録

コンストラクタを使わず、実行時に追加・解除することもできます。

```renpy
# 剣を下端（握り）で持たせ、指の向きに沿わせる
$ sword = ringo.ss_attach("hand_r", "sword.png", anchor=(0.5, 1.0), angle=-90)

# パーツの拡縮も反映し、hide のフレームでは描画しない
$ ringo.ss_attach("head", "aura.png", drive_scale=True, on_hide="hide")

# 解除（子を指定 / パーツを指定 / 全解除）
$ ringo.ss_detach(child=sword)
$ ringo.ss_detach(part="hand_r")
$ ringo.ss_clear_attachments()
```

| メソッド | 説明 |
|---|---|
| `ss_attach(part, child, drive_scale, on_hide, anchor, angle)` | 追従を追加し、正規化された子を返す（`ss_detach` にそのまま渡せます） |
| `ss_detach(child=None, part=None)` | その子 / そのパーツに一致する追従をすべて削除し、削除件数を返す。両方を省略した場合は何も削除しません |
| `ss_clear_attachments()` | すべての追従を削除し、削除件数を返す |
| `ss_attachments()` | 現在の追従を `(パーツ名, 子)` の組で取得 |
| `ss_part_names()` / `ss_part_index(part_name)` | パックのパーツ名一覧 / パーツインデックス（アセットに無ければ `-1`） |
| `ss_is_part_hidden(part_name)` | そのパーツが直近の描画フレームで hide かを取得 |
| `ss_part_transform(part_name)` | そのパーツの直近の描画フレームの変換を取得（無ければ `None`） |

> 常時追従させるまでもなく「その瞬間のパーツ位置だけ知りたい」場合（弾の発射位置を取るなど）は、 `ss_part_transform()` を直接呼ぶ方が簡潔です。

> **`show <タグ>` は複製を描画します。** `image` で登録した `SSPlayer` は show のたびに複製されるため、コンストラクタに渡した `attachments=` は複製にも引き継がれますが、後から変数に対して `ss_attach()` を呼んでも編集されるのはテンプレート側で、画面に出ているものには効きません。実行中に貼りたい場合はインスタンスを 1 つ保持し、`show expression player as tag` でそのオブジェクト自体を表示してください。

### 追従のタイミングと精度

追従の合成はプレイヤー自身の `render()` の中、そのフレームの姿勢を計算するのと同じパスで行われます。そのため**子がアニメーションから遅れることはありません**。誤ったタイミングで走り得る別の駆動ステップが存在しないからです。

`ss_part_transform()` は合成そのものが使う姿勢を返します。単位はプレイヤーローカルのピクセルで、アニメーション原点がプレイヤーの描画ボックス中心に来る座標系です。

| キー | 意味 |
|---|---|
| `x` / `y` | アニメーション原点を基準とした位置（px）。Y は**下方向が正** |
| `rotation` | 角度（度、**時計回りが正**） |
| `xscale` / `yscale` | 拡縮。**絶対値（常に正）** |

最初のフレームが描画されるまでの間、および描画中のフレームに含まれないパーツについては `None` を返します。パーツが `None` を返した子は、そのフレームでは単に描画されません。

`anchor` は回転・拡縮の基準点も兼ねます。子の回転前サイズは毎フレーム測るので、サイズが変わる子でも anchor は維持されます。手のパーツは手首の角度を持つため、持ち物はまっすぐ立ってしまわないよう、通常は `angle` オフセットを指定して指の向きに沿わせます。

`xscale` / `yscale` が絶対値であるため、**反転（マイナススケール）したパーツでも子は反転しません**。`drive_scale` を有効にした場合、反転したパーツは子を反転させるのではなく絶対値の分だけ拡縮します。

### 注意点

- **子はスプライト全体の手前に描画されます。** パーツ間に差し込むことはできないため、子をキャラクターの体の後ろに回すことはできません。
- パーツ名は、その時点で存在していなくても構いません。現在のアニメーションに無いパーツに対する子は単に描画されず、そのパーツが現れた時点で自動的に追従を始めます。
- パーツ名は、そのプレイヤー自身が再生しているパックのパーツから解決されます。**インスタンスパーツの内部（子アニメーション）のパーツは指定できません**（インスタンスパーツ自体は指定できます）。
- 同名のパーツが複数ある場合は、パック内で**最後**のものが使われます。特定のパーツを狙う必要がある場合は SpriteStudio 側で名前を変えてください。
- 追従先には**通常（画像）パーツ**を選ぶことを推奨します。メッシュパーツのピボットは変形前の位置に留まるため、そこに貼った子は画面上の変形後の形状からずれていきます。
- 1 つのパーツに複数の子を貼ることができ、1 つのプレイヤーが持てる追従の数にも制限はありません。
- 追従の設定は単純なデータなので、**セーブに保存され、ロールバックしても維持されます**。ロード後に登録し直す必要はありません。
- 描画に失敗した子はそのフレームで読み飛ばされ、スプライト本体を壊すことはありません。

---

## 6. パーツオーバーライド（パーツカラー / セル / 表示指定）

パーツ単位のランタイムオーバーライドは、「このパーツを**今**この色に / このセルに / 非表示に」とスクリプトから指示する機能です。オーバーライドはキーフレームやアニメーションのブレンドよりも優先されるので、アニメーションと取り合いになりません。

```renpy
$ ringo = SSPlayer("ss_assets/Ringo/Ringo.ssab", animation="wait1")

# パーツを赤く着色（1 = Mul）。通常（画像）パーツに適用されます。
$ ringo.ss_set_part_color_override("apple", "#f00", blend_op=1)

# 別のセルを描画させる（セルマップ名は ".ssce" を付けずに指定）。
$ ringo.ss_set_part_cell_override("apple", "Ringo", "effect3")

# パーツを強制非表示にする（子孫にもカスケード）。
$ ringo.ss_set_part_visibility_override("apple_base", True, cascade=True)

# 解除
$ ringo.ss_clear_part_color_override("apple")
$ ringo.ss_clear_all_part_overrides()
```

| メソッド | 説明 |
|---|---|
| `ss_part_index(part_name)` | パーツインデックス。アセットに無ければ `-1` |
| `ss_set_part_color_override(part, color, blend_op=0, priority=1)` | パーツカラーオーバーライド（単色） |
| `ss_set_part_color_override_corners(part, corners, blend_op=0, priority=1)` | 四隅指定版（左上・右上・左下・右下） |
| `ss_set_part_cell_override(part, cellmap_name, cell_name, priority=1)` | 別のセルで描画する |
| `ss_set_part_visibility_override(part, hide=True, cascade=False)` | 強制非表示（`hide=False` でアニメーションに戻す） |
| `ss_clear_part_color_override` / `ss_clear_part_cell_override` / `ss_clear_part_visibility_override` | 1 パーツの 1 オーバーライドを解除 |
| `ss_clear_all_part_overrides()` | そのプレイヤーの全オーバーライドを解除 |
| `ss_cellmap_names()` / `ss_cell_names(cellmap_name)` | セルオーバーライドに指定できるセルマップ名 / セル名の列挙 |

各メソッドの `part` 引数は、**パーツ名**と**パーツインデックス**のどちらでも受け付けます。パーツが不明な場合やランタイムが受け付けなかった場合は `False` を返します。

**色**は Ren'Py の任意の色表現を受け付けます（`"#f00"`、`(255, 0, 0)`、`Color(...)`、パックされた `0xRRGGBBAA` の int）。

セルオーバーライドに指定できるセルマップ名 / セル名は、パック側から列挙できます。

```renpy
$ print(ringo.ss_cellmap_names())       # → ["Ringo", ...]
$ print(ringo.ss_cell_names("Ringo"))   # → ["effect3", ...]
```

> **パーツインデックスの使い方について**: パーツインデックスは同一アセット（同じ `.ssab`）内では安定しているので、頻繁にオーバーライドするなら `ss_part_index()` で一度パーツ名をパーツインデックスに解決して、そのインデックスを使い回すことを推奨します。

### 合成モード（blend_op）

`ss_set_part_color_override()` の `blend_op` は、キーフレームのパーツカラーと同じ 4 種です。

| 値 | 合成モード |
|---|---|
| `0` | Mix（既定） |
| `1` | Mul（乗算） |
| `2` | Add（加算） |
| `3` | Sub（減算） |

範囲外の値を渡した場合は設定に失敗し、`False` を返します。

### 優先モード（priority）

パーツカラーとセルのオーバーライドはアニメーションと競合するため、`priority` を取ります（表示指定にはありません。単なる強制非表示フラグで、アニメーションを設定し直すと必ずクリアされます）。

| 値 | 優先モード | 挙動 |
|---|---|---|
| `0` | OverwriteOnNextKeyframe | アニメーションデータが当該アトリビュートを更新するまで、オーバーライドが適用される |
| `1` | HoldUntilNextAnimation（既定） | 現在のアニメーション中は勝ち続け、新しいアニメーションを設定するとオーバーライドが解除される |
| `2` | Permanent | 同じアニメーションデータ（`.ssab`）である間、オーバーライドが適用される（アニメーション変更をまたいでも持続） |

### 注意点

- **カラー**は通常パーツ、**セル**は通常パーツとマスクパーツに適用されます。それ以外の種別のパーツでは黙って無視されます（呼び出し自体は `True` を返します）。
- 色はオーサリングされたパーツカラーと同じ 8bit sRGB 空間として解釈され、アルファはランタイム側で pre-multiply されます。自前で変換せず、オーサリングどおりの色を渡してください。
- セルオーバーライドは設定時に解決されるため、存在しないセルマップ名 / セル名はその場で失敗します（`False` を返します）。
- オーバーライドはランタイムが保持し、そのライフサイクルもランタイムが管理します。アニメーション変更後に再適用する必要はありません。意図に合った優先モードを選んでください。
- オーバーライドはセーブデータのロード時に復元されるため、着せ替えの状態がセーブ / ロードをまたいで保たれます。ただしワンショット（`priority=0`）は例外で、一時的な指定という性質上、セーブを跨いでは引き継がれません。
- インスタンスパーツ**配下**のパーツには届きません（子アニメーションは別のプレイヤーとして動作するためです）。インスタンスパーツ自体を強制非表示にした場合は、その配下もまとめて描画されなくなります。

> **オーバーライドの設定が描画に反映されるタイミングについて**: オーバーライドの設定・解除を行うと、再生の停止中 / 一時停止中でも即座に再描画されます。反映のためにフレームを動かす必要はありません。

---

## 7. アニメーションイベント（ユーザーデータ / シグナル）の処理
SpriteStudio側で設定した「ユーザーデータ」や「シグナル」の情報をRen'Py側で受け取ることができます。これにより、特定のフレームで効果音を鳴らしたり、スクリプトの進行を同期させたりすることが可能です。

### コールバック（イベント駆動）による受け取り
`SSPlayer` のインスタンス生成時に、各イベントに対応した関数を渡すことで、特定のタイミングで処理を発火させることができます。

```python
init python:
    def my_signal_handler(player, frame, signal):
        print(f"シグナルを受信: コマンド={signal.command_id}, 引数={signal.params}")

    def my_finish_handler(player):
        print("アニメーションが最後まで再生されました")
```
```renpy
# コールバックを登録して再生
image boss = SSPlayer(
    "ss_assets/Boss/Boss.ssab",
    on_signal=my_signal_handler,
    on_finished=my_finish_handler
)
```

**利用可能なコールバック引数:**
- `on_user_data`: ユーザーデータ到達時に呼ばれる
- `on_signal`: シグナル到達時に呼ばれる
- `on_audio`: 音声再生指定フレーム到達時に呼ばれる
- `on_finished`: 指定した `loop` をすべて再生し終えたときに1回呼ばれる。無限ループでは発火せず、停止操作でも発火しない
- `on_looped`: ループ完了ごと（1周回るごと）に呼ばれる。最終周はループせず `on_finished` になる
- `on_started`: アニメーション再生開始時に呼ばれる

> [!NOTE]
> コールバックは描画スレッドから `cb(player, ...)`（開始/終了/ループ系は `cb(player)`）の形で呼ばれます。ロールバック（rollback）時のピクル化のため、ラムダやローカル関数ではなくモジュールレベルの関数を渡してください。

※ ポーリングベース（`ss_poll_events()`）での受け取り方については、デモプロジェクトの `script.rpy` 内 `ss_drain_events()` などの実装をご参照ください。

---

## 8. 便利機能

### 一発再生を手軽に（`ss_play_once`）
任意の `.ssab` を一度だけ再生（エフェクトでも全画面カットシーンでも）。`wait=True` で再生し終わるまで待ってから自動で消します。待たずに出したものは `ss_hide_once(tag)` で消せます。
```renpy
$ ss_play_once("ss_assets/ParticleEffect/e038.ssab", "hit",
               at=Transform(xpos=640, ypos=360), wait=True)
```
`ss_duration("…/Ringo.ssab", "attack1")` はそのアニメ1周の秒数を返すので、表示中キャラの「再生して待つ」は `show ringo attack` ＋ `$ renpy.pause(ss_duration(...))` で書けます。

### 動作確認（診断）
開発者モードでは起動時に「runtime loaded / N pack(s)」がログ出力されます。コンソール（Shift+O）で `ss_diagnostics()` を呼ぶと、ランタイムの状態と検出済みパック一覧を確認できます。`.ssab` が読めない場合は、パス（`game/` からの相対）を含む分かりやすいエラーになります。

---

## 9. アセットブラウザ (Shift+B)：一覧・プレビュー・スニペット生成

開発者モードで **Shift+B** を押すと **アセットブラウザ** が開きます。「どのパックを、どう再生すればいいのか？」を数クリックで解決する組み込みインスペクタです。開発者モード限定（リリースビルドではホットキーが無効）で、実行中のゲームにオーバーレイ表示されるため、いつでも呼び出せます。

> [!TIP]
>
> <video autoplay loop muted playsinline width="100%">
>   <source src="../../assets/2-asset_browser.webm" type="video/webm">
> </video>
> <img src="../assets/2-asset_browser.webp" width="100%" style="display: none;">

ウィンドウは3ペイン構成です。

1. **パック一覧（左）**：リゾルバが `ss_assets/` 配下で見つけた全 `.ssab`（`.rpa` アーカイブ内も含む）。クリックで選択します。
2. **ライブプレビュー（中央）**：選択したアニメーションが実際に再生されます（静止サムネイルではありません）。あわせて `animations`（数）・`fps`・`effects` の有無・外部インスタンスパックといったメタ情報を表示。一覧のアニメをクリックすれば即座に切り替わります。
3. **スニペット（右）**：**ロール**（Character / One-shot / UI）を選ぶと、そのパック用の貼り付け可能な `.rpy` スニペットが生成されます。デフォルトのロールはパック内容から推定される（例：エフェクトのみのパックは One-shot）ため、アニメを見ながら用途を選べます。

書き出すと、スニペットはプロジェクト直下の **`ss_snippets.txt`** に追記され、クリップボードにもコピーされるので、そのままスクリプトへ貼り付けられます。**Esc** で閉じます。

ブラウザは `SSPlayer` と同じゼロコンフィグのリゾルバ経由で読み込むため、一覧に出たものは表示パスそのままで確実にロードできます（[Auto Importer](import.md) が生成した直後のパックも、インポート時に索引が更新されるため含まれます）。

### Auto Importer と連動する

新しいパックを取り込むのに再起動は不要です。`SpriteStudio_Source/` に新規プロジェクトを置いて **Shift+R** でリロードすると、[Auto Importer](import.md) が変換して索引を更新します。ブラウザを開き直せば（**Shift+B**）、新しいパックが一覧に現れ、その場でプレビューできます。

> [!TIP]
>
> <video autoplay loop muted playsinline width="100%">
>   <source src="../../assets/3-asset_browser_autoimport.webm" type="video/webm">
> </video>
> <img src="../assets/3-asset_browser_autoimport.webp" width="100%" style="display: none;">
