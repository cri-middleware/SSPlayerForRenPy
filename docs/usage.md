# 再生と制御 (Usage Guide)

Ren'Pyのスクリプト(`script.rpy`など)から、SpriteStudioのアニメーションを再生する方法を解説します。

## 基本的な再生
`SpriteStudioDisplayable` クラスを利用して、指定した `.ssab` アニメーションを画面に描画（追加）します。

```renpy
screen my_animation_screen():
    # "Basic.ssab" を画面中央に表示する例
    add SpriteStudioDisplayable("Basic.ssab", sprites_subdir="sprites") xalign 0.5 yalign 0.5
```

### パラメータ解説
- **第1引数 (`"Basic.ssab"`)**: 再生するアニメーションのファイル名。
- **`sprites_subdir`**: ゲームの `game/` フォルダ直下から見た、`.ssab` ファイルが置かれているサブディレクトリのパス。

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
