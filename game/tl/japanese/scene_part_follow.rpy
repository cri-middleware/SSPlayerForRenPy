# Japanese translations for the part-tracking sample (game/scene_part_follow.rpy).
# The animation names (run / walk / …) are shown untranslated, like the asset
# picker's. "Close" is translated globally in tl/japanese/asset_picker.rpy, so it
# is not repeated here (a duplicate string translation is an error).

translate japanese strings:

    old "Part tracking — attach a marker to a live part"
    new "パーツ追従 — 動いているパーツにマーカーを貼る"

    old "⚠ parts are skinned (bone-bound) meshes: the marker snaps near the character root, not onto the art. Not forbidden — check ss_is_part_skinned_mesh() and prefer a NULL / bone / joint part (bone_14 is the default)."
    new "⚠ の付いたパーツはスキン（ボーンバインド）メッシュです。マーカーは絵ではなくキャラのルート付近に吸い寄せられます。禁止はしません — ss_is_part_skinned_mesh() で確認し、NULL／ボーン／ジョイントパーツ（既定は bone_14）を追従先にするのがおすすめです。"

    old "Animation"
    new "アニメーション"

    old "Options"
    new "オプション"

    old "Attached: ON"
    new "追従: ON"

    old "Attached: OFF"
    new "追従: OFF"

    old "Scale follow: ON"
    new "スケール追従: ON"

    old "Scale follow: OFF"
    new "スケール追従: OFF"

    old "On hide: HIDE"
    new "非表示なら: 消す"

    old "On hide: FOLLOW"
    new "非表示なら: 追従継続"

    old "(Ringo failed to load)"
    new "(Ringo の読み込みに失敗しました)"

    old "⚠ '[ss_pf_part]' is a skinned mesh — the marker sits near the root, not on the art. Place a NULL part there in SpriteStudio (or follow a bone / joint) for accurate tracking."
    new "⚠ '[ss_pf_part]' はスキンメッシュです — マーカーは絵ではなくルート付近に留まります。正確に追従させるには、SpriteStudio でその位置に NULL パーツを置く（またはボーン／ジョイントを追従先にする）でください。"

    old "Following '[ss_pf_part]' — a good target (its node moves with the art)."
    new "'[ss_pf_part]' に追従中 — 良い追従先です（ノードが絵と一緒に動きます）。"

    old "Follow target"
    new "追従先パーツ"

    old "scroll: wheel / drag  ·  ⚠ = skinned"
    new "スクロール: ホイール / ドラッグ  ·  ⚠ = スキン"
