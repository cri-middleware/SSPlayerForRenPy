# 再生と制御 (Usage Guide)

Ren'Pyのスクリプト(`script.rpy`など)から、SpriteStudioのアニメーションを再生する方法を解説します。

## 基本的な再生
`SSPlayer` クラスを利用して、指定した `.ssab` アニメーションを画面に描画（追加）します。

```renpy
screen demo():
    # 画面の中央に配置
    add SSPlayer("Hero/Hero.ssab") xalign 0.5 yalign 0.5
```

### パラメータ解説
- **第1引数 (`"Hero/Hero.ssab"`)**: 再生するアニメーションのファイル名。デフォルトのベースフォルダからの相対パスで指定します。
- **`sprites_subdir` (省略可能)**: `.ssab` が置かれているベースフォルダのパス。**デフォルトは `"ss_assets"` です。** オートインポーターを利用して `game/ss_assets/` 以下に出力されている場合、この引数は省略できます。

## 画面への表示と非表示
スクリーンを使って表示・非表示を切り替えるのが基本となります。
```renpy
label start:
    # スクリーンを表示してアニメーション再生開始
    show screen my_animation_screen
    
    "アニメーションを再生しています。"
    
    # スクリーンを非表示
    hide screen my_animation_screen
    
    return
```

## 注意点
- **原点とアンカー**: アニメーションの原点設定や表示位置については、Ren'Pyの標準機能である `xalign`, `yalign`, `xpos`, `ypos` などのTransformプロパティを組み合わせて調整してください。
- 現行バージョンでの制限事項（表示できないパーツ等）については [limitations.md](limitations.md) を確認してください。
