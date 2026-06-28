# 再生と制御 (Usage Guide)

SpriteStudio Player for Ren'Py では、SpriteStudioのアニメーションをRen'Py上で非常に柔軟に制御できます。画面への単純な描画から、キャラクターの立ち絵としての統合、イベントコールバックまで、目的に応じた使い方を解説します。

> **`.ssab` の置き場所について**: コンバート済みの `.ssab` とそのテクスチャ（`.png`）、および参照する外部インスタンスパックは、すべて **同じフォルダに同居** します（オートインポーターは `game/ss_assets/<プロジェクト名>/` に出力します）。プレイヤーは関連リソースを `.ssab` と同じフォルダから解決するため、テクスチャ用のフォルダを別途指定する必要はありません。

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
- **`loop` (省略可能)**: 再生回数。`-1`（既定）で無限ループ、`1` で1回再生、`N` でN回再生。
- **`speed` (省略可能)**: 再生速度の倍率（既定 `1.0`）。
- **`size` (省略可能)**: `(w, h)`（または正方形なら数値1つ）を渡すと、その**箱サイズの普通の画像**として振る舞い、`xalign`/`xpos`/`pos` やコンテナ配置がそのまま効きます（アニメは箱の中央に描画）。省略時は画面全体を占有するので `xoffset`/`yoffset` で位置調整します。どちらの場合も `zoom`/`Transform` での拡大縮小は効きます。

```renpy
# size を指定すれば align で配置できる
add SSPlayer("ss_assets/Ringo/Ringo.ssab", size=(400, 600)) xalign 0.5 yalign 1.0
```

> どんな `.ssab` パックが入っているか分からないときは、開発者モードで **Shift+B**（アセットブラウザ）を開くと、一覧・ライブプレビュー・スニペット生成ができます。
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
$ player = SSPlayer("ss_assets/Hero/Hero.ssab")

# 収録されているすべてのアニメーション名リストを取得
$ anim_names = player.ss_animation_names()

# 現在再生中のアニメーション名を取得
$ current_anim = player.ss_get_animation()

# 任意のアニメーションへの切り替え（読み込み＋頭出し → 再生）
$ player.ss_play("run")
```

- **読み込みと再生の分離**: `ss_set_animation("run")` はアニメーションを読み込んでポーズ（頭出し）するだけで、再生は開始しません。`ss_play()` で再生を開始します。
- **再生制御**: `ss_pause()` / `ss_resume()` / `ss_stop()`、フレーム操作 `ss_set_frame()` / `ss_get_frame()`、速度 `ss_set_speed()`、ループ `ss_set_loop()` などが利用できます。
- **パーツ照会**: `ss_part_transform("part名")` で直近フレームのパーツのローカル変換（x/y/回転/スケール）を取得できます。

---

## 5. アニメーションイベント（ユーザーデータ / シグナル）の処理
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
- `on_finished`: 再生終了時（`loop`到達時など）に呼ばれる
- `on_looped`: ループ完了ごと（1周回るごと）に呼ばれる
- `on_started`: アニメーション再生開始時に呼ばれる

> コールバックは描画スレッドから `cb(player, ...)`（開始/終了/ループ系は `cb(player)`）の形で呼ばれます。ロールバック（rollback）時のピクル化のため、ラムダやローカル関数ではなくモジュールレベルの関数を渡してください。

※ ポーリングベース（`ss_poll_events()`）での受け取り方については、デモプロジェクトの `script.rpy` 内 `ss_drain_events()` などの実装をご参照ください。
