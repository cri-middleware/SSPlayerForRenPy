# 🔘 ボタン

`SSButton` は、アニメーションをボタンにします。ボタンの状態（idle・hover・insensitive）ごとにアニメーションの別の部分を再生し、マウスを受ける範囲を一部のパーツに絞れるので、形の不揃いなボタンが箱全体でクリックを受けることはありません。Ren'Py のボタンなので、`action`・`alt`・`hovered`・スタイル・サウンド・キーボード操作は `imagebutton` と同じように使えます。

```renpy
screen title_menu():
    add SSButton("ss_assets/ui/start.ssab", action=Start(), parts=["face"], alt=_("Start")):
        xalign 0.5
        yalign 0.7
```

最初の引数は `.ssab` のパスか、自分で作った `SSPlayer` です。プレイヤー自身の引数（`size=` やコールバック）を使いたいときや、変数に持っておきたいときは、`SSPlayer` を渡します。

`SSButton` は `spritestudio/ss_ui.rpy` にあります。使わないゲームでは、このファイルを消してかまいません。

## 状態とラベル

SpriteStudio で、1 つのアニメーションに状態と同じ名前のラベルを置きます。

| ボタンの状態 | ラベル |
|---|---|
| idle | `normal` |
| hover（マウスが乗っているとき、キーボードで選んでいるとき） | `hover` |
| insensitive | `disabled` |

各状態は、そのラベルから次のラベル（名前は問いません）の 1 フレーム手前までをループ再生します。最後のラベルはアニメーションの終わりまでです。ラベルは完全一致で引くので、小文字で書いてください。

- ラベルの無い状態は `normal` を再生します。`normal` も無ければ、アニメーション全体を再生します。
- ラベルは、ボタンを最初に表示したときにプレイヤーが選んでいるアニメーションから読みます（パスを渡したときはパックの最初のアニメーション）。`animation="button"` で別のアニメーションを指定できます。
- 選択中のボタン（`selected_idle`・`selected_hover`）は、選択していないときと同じ表示になります。

## 別のアニメーションを使う（`clips`）

`clips` は、状態にラベルの代わりのものを再生させます。値はアニメーション全体の名前か、`"animation"` と `"label"` の一方または両方を持つ dict です。dict のときは、そのアニメーション（省略したときはラベルを読むアニメーション）のラベルの区間を再生します。

```renpy
# Ringo には状態の名前のラベルが無いので、状態ごとにアニメーションを再生する
add SSButton("ss_assets/Ringo/Ringo.ssab", action=Start(),
             clips={"normal": "wait1", "hover": "joy", "disabled": "sitdown_wait"})

# hover では "effects" アニメーションの "glow" ラベルの区間を再生する
add SSButton(menu_player, clips={"hover": {"animation": "effects", "label": "glow"}})
```

`clips` は、その状態に落ちてくる状態にも効きます。hover と insensitive に自分のラベルも `clips` も無ければ、`normal` の `clips` を再生します。パックに無いアニメーションやラベルを指す `clips` は `log.txt` に 1 度だけ書き出し、その状態は `clips` が無いものとして再生します。

## マウスを受ける範囲

| 渡すもの | マウスを受ける範囲 |
|---|---|
| 何も渡さない | 箱全体 |
| `focus_mask=True` | 描いた画素（画像のボタンと同じ） |
| `parts=["face", "hand"]` | それらのパーツを描いた輪郭。フレームごとに追います（[輪郭と当たり判定](usage.md#outlines-and-hit-testing)） |

どれを選んでも、キーボードではボタンに届きます。箱はプレイヤーの箱（アニメーションのキャンバスか `size=`）なので、その外に描いた絵はクリックを受けません。ボタンに `at` で `zoom` を掛けると、範囲も絵と一緒に拡大縮小します。

## 動きを減らす（reduced motion）

`reduced_motion=True` にすると、各状態は区間の先頭フレームで止まります。プレイヤーは停止するので、イベントもサウンドも出ません。アニメーションに `reduced_motion` ラベルがあれば、idle だけは代わりにそのラベルの区間を再生するので、穏やかなループを残せます。

Ren'Py にはこの設定が無いので、ゲームの設定として持ってください。

```renpy
default persistent.reduced_motion = False

screen title_menu():
    add SSButton("ss_assets/ui/start.ssab", action=Start(),
                 reduced_motion=persistent.reduced_motion)

# 設定画面で
textbutton _("Reduce motion") action ToggleField(persistent, "reduced_motion")
```

## 読み上げ

読み上げ（セルフボイシング）を有効にすると、ボタンは `alt` のテキストを読みます（画像のボタンと同じです）。`alt` が無ければ、アニメーション自体は何も読みません。

## 注意点

- **ボタンがプレイヤーを再生します。** アニメーション・区間・ループ回数を選び、再生と停止もボタンが行うので、そのプレイヤーで `ss_play()` などを呼んだり、ほかの場所に表示したりしないでください。
- **押している間の状態はありません。** Ren'Py のボタンには、マウスを押し続けている間の状態がありません。
- `parts` に指定できるのは、プレイヤー自身が再生しているパックのパーツです。インスタンスパーツの中のパーツは指定できません。
