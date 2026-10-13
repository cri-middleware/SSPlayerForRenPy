# Japanese translations for the animation blending sample (game/scene_blend.rpy).
# The animation names (wait1 / walk / …) are shown untranslated, like the part
# tracking sample's. "Animation" is translated in tl/japanese/scene_part_follow.rpy
# and "Close" in tl/japanese/asset_picker.rpy, so neither is repeated here (a
# duplicate string translation is an error).

translate japanese strings:

    old "Animation blending — crossfade and layering on one player"
    new "アニメーションのブレンド — 1 つのプレイヤーでクロスフェードと重ね合わせ"

    old "Pick an animation to crossfade track 0 into it. The current animation switches as you click, not when the fade ends."
    new "アニメーションを選ぶと、トラック 0 がそこへクロスフェードします。現在のアニメーションは、フェードの終わりではなくクリックした時点で切り替わります。"

    old "Switch by: crossfade"
    new "切り替え方: クロスフェード"

    old "Switch by: ss_set_animation"
    new "切り替え方: ss_set_animation"

    old "Track 0"
    new "トラック 0"

    old "Speed: [ss_bl_speed]×"
    new "速度: [ss_bl_speed]×"

    old "Loop: once"
    new "ループ: 1 回"

    old "Loop: forever"
    new "ループ: 無限"

    old "Pause"
    new "一時停止"

    old "Resume"
    new "再開"

    old "Play from the top"
    new "先頭から再生"

    old "Track 1 (overlay: attack1)"
    new "トラック 1（重ねるアニメ: attack1）"

    old "Overlay: on"
    new "重ね合わせ: オン"

    old "Overlay: off"
    new "重ね合わせ: オフ"

    old "Alpha: 1.0"
    new "強さ（alpha）: 1.0"

    old "Alpha: 0.5"
    new "強さ（alpha）: 0.5"

    old "Blend: mix"
    new "重ね方: ミックス"

    old "Blend: additive"
    new "重ね方: 加算"

    old "Start: from the top"
    new "開始位置: 先頭から"

    old "Start: in step with track 0"
    new "開始位置: トラック 0 に揃える"

    old "Events (overall/UserData)"
    new "イベント（overall/UserData）"

    old "Crossfade it into itself (1s)"
    new "同じアニメへクロスフェード（1 秒）"

    old "Outgoing side: silent"
    new "出ていく側のイベント: 出さない"

    old "Outgoing side: fires in the first half"
    new "出ていく側のイベント: フェードの前半は出す"

    old "Switch by ss_set_animation folds the stack back to track 0; the overlay is laid again."
    new "ss_set_animation で切り替えるとスタックはトラック 0 だけに戻るので、重ねるアニメは載せ直しています。"

    old "Current animation: %s"
    new "現在のアニメーション: %s"

    old "Track 0  main source %s  speed %s  loop %s  finished %s"
    new "トラック 0  主ソース %s  速度 %s  ループ %s  終了 %s"

    old "Track 0  fade %s  outgoing events from %s"
    new "トラック 0  フェード %s  出ていく側のイベントのしきい値 %s"

    old "Track 1  frame %s  loop %s  finished %s  alpha %s"
    new "トラック 1  フレーム %s  ループ %s  終了 %s  強さ %s"
