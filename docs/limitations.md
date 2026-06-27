# 仕様と制約事項 (Limitations & Scope)

現在提供されている SSPlayer for Ren'Py における、サポート機能と制限事項の一覧です。

## 現在のステータス (M1 / M2)

現在は主に **M1レベル（Normalパーツの基本描画）** をサポートしています。

### サポートされている機能 (Supported)
- **Normalパーツ**: 基本的な描画
- **トランスフォーム**: 位置 (Position)、回転 (Rotation)、非均等スケール (Non-uniform scale)、水平/垂直フリップ (H/V flip)
- **階層構造**: 親子階層の連動 (Pre-baked world matrices in `RenderMode::Direct`)
- **アルファとブレンド**: パーツごとの透明度 (Alpha)、Mixブレンドモード

### 制限事項・未サポート (Not Yet Supported)
- **Mesh / 自由変形**: フリーフォームやシアー（歪み）が適用されたセルは、現段階では変形されていない矩形(Box)として近似レンダリングされます（ピクセル誤差については `renpy.log` に出力されます）。完全な再現には M2 (モデルベースメッシュ) の実装が必要です。
- **一部のブレンドモード**: 加算(Add)、乗算(Mul) などのMix以外のブレンドモードは未対応です。
- **頂点カラー (`parts_color`)**: 描画に反映されません。
- **その他の特殊パーツ**: Effect, Mask, Shape, Instance, Text, NineSlice には現状対応していません。

## パフォーマンス・プラットフォーム固有の注意
- 描画は `ctypes` と Creator-Defined Displayable を介して行われるため、オブジェクト数や複雑なアニメーションが多数重なるとフレームレートに影響が出る可能性があります。
- デスクトップ版 (Windows, macOS, Linux) でのみネイティブライブラリがロードされる想定です。モバイル (Android, iOS) や Webプラットフォーム向けの実装は今後の課題となります。
