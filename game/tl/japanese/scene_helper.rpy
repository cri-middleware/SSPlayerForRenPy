# Japanese translations for scene_helper.rpy (ringo_helper_demo).

# 1. wait1 -> joy -> wait1（ナレーションで「話していない」状態を作って見せる）
translate japanese helper_msg1:
    "ナレーションが喋っている間、Ringo は話し手ではないので、SSCharacter は待機モーション（wait1）のままにしまス。"

translate japanese helper_msg2:
    ringo_chr "私が喋った瞬間に talk モーションへ切り替わりまス。ここでは talk 専用アニメが無いので joy を使ってまス！"

translate japanese helper_msg3:
    "またナレーションに戻って Ringo が黙ると、wait1 に戻りまス。この idle → talk → idle こそ SSCharacter が自動でやってくれる仕事でス。"

# 2. アタッチメント
translate japanese helper_msg4:
    "頭の ♪ は head パーツに追従しているのです。"

# 3. ss_play_once
translate japanese helper_msg5:
    "ss_play_once(wait=True) は、再生が終わるまで“間”を取ってくれます。"

# 4. ss_duration
translate japanese helper_msg6:
    "今の dance は ss_duration で長さを測って待ちました。エフェクトと違って、キャラは画面に残ります。"

translate japanese helper_msg7:
    ringo_chr "新機能のショーケースは以上でス。よろしくでス！"
