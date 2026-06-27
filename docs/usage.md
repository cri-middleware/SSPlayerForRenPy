# 再生と制御 (Usage Guide)

SSPlayer for Ren'Py では、SpriteStudioのアニメーションをRen'Py上で非常に柔軟に制御できます。画面への単純な描画から、キャラクターの立ち絵としての統合、イベントコールバックまで、目的に応じた使い方を解説します。

---

## 1. 最も簡単な再生（Screenからの呼び出し）
`SSPlayer` クラスは Ren'Py の Displayable（描画オブジェクト）として振る舞うため、スクリーン内に `add` して直接表示するのが最もシンプルです。

```renpy
screen demo():
    # 画面の中央に配置
    add SSPlayer("Ringo/Ringo.ssab") xalign 0.5 yalign 0.5
```

### 基本パラメータ
- **第1引数 (`"Ringo/Ringo.ssab"`)**: 再生するアニメーションのファイル名。
- **`sprites_subdir` (省略可能)**: `.ssab` が置かれているベースフォルダのパス。**デフォルトは `"ss_assets"`** です。オートインポーターを利用して `game/ss_assets/` 以下に出力されている場合、この引数は省略できます。
- **`animation` (省略可能)**: 初期状態で再生するアニメーション名を指定します。省略時はデータ内の最初のアニメーションが再生されます。

---

## 2. 立ち絵としての利用 (image 宣言と Character 連携)
Ren'Pyの `image` ステートメントと組み合わせることで、ノベルゲームにおける**キャラクターの立ち絵**として強力に機能します。`aliases` 引数を使うと、Ren'Pyのアトリビュート名とSpriteStudio内のモーション名を紐付けることができます。

```renpy
# キャラクターの定義
image ringo = SSPlayer(
    "Ringo/Ringo.ssab", 
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
    "ParticleEffect/e038.ssab", 
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
$ player = SSPlayer("Hero/Hero.ssab")

# 収録されているすべてのアニメーション名リストを取得
$ anim_names = player.ss_animation_names()

# 現在再生中のアニメーション名を取得
$ current_anim = player.ss_get_animation()

# 任意のアニメーションへの切り替え
$ player.ss_play("run")
```

---

## 5. アニメーションイベント（ユーザーデータ / シグナル）の処理
SpriteStudio側で設定した「ユーザーデータ」や「シグナル」の情報をRen'Py側で受け取ることができます。これにより、特定のフレームで効果音を鳴らしたり、スクリプトの進行を同期させたりすることが可能です。

### コールバック（イベント駆動）による受け取り
`SSPlayer` のインスタンス生成時に、各イベントに対応した関数を渡すことで、特定のタイミングで処理を発火させることができます。

```python
init python:
    def my_signal_handler(signal):
        print(f"シグナルを受信: コマンド={signal.command_id}, 引数={signal.params}")

    def my_finish_handler():
        print("アニメーションが最後まで再生されました")
```
```renpy
# コールバックを登録して再生
image boss = SSPlayer(
    "Boss/Boss.ssab",
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

※ 各イベントの詳細な取得方法や、ポーリングベース（`ss_poll_events()`）での受け取り方については、デモプロジェクトの `script.rpy` 内 `ss_drain_events()` などの実装をご参照ください。
