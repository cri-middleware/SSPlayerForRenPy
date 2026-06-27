# 仕様と制約事項 (Limitations & Scope)

現在提供されている SpriteStudio Player for Ren'Py における、サポート機能と制限事項の一覧です。

## 現在のステータス

現在はSpriteStudio 7の主要な機能（Mesh, Effect, Instanceを含む）をサポートしています。

### サポートされている機能 (Supported)
- **Normalパーツ**: 基本的な描画
- **トランスフォーム**: 位置 (Position)、回転 (Rotation)、非均等スケール (Non-uniform scale)、水平/垂直フリップ (H/V flip)
- **階層構造**: 親子階層の連動 (Pre-baked world matrices in `RenderMode::Direct`)
- **アルファとブレンド**: パーツごとの透明度 (Alpha)、主要なブレンドモード（Mix, Add, Multiply 等）
- **頂点カラー (`parts_color`)**: 各頂点カラーの適用、およびカラーブレンド（Mix, Add, Multiply, Sub 等）
- **Mesh / 自由変形**: GL2メッシュベースのフリーフォーム変形およびボーン連携による重み付き変形
- **特殊パーツ**:
  - **Effect** (パーティクルエフェクト)
  - **Instance** (アニメーションの入れ子再生)
- **ユーザーデータ / イベント**: スクリプト側でのコールバックによるシグナル処理（アニメーションイベント）

### 制限事項・未サポート (Not Yet Supported)
- **一部の特殊なパーツ**: Mask, Shape, Text, NineSlice には現状対応していません。
- **一部の特殊なブレンド**: Ren'Pyの `config.gl_blend_func` に依存しているため、非常に特殊なブレンドモードは標準では近似表示または Mix となる場合があります。

## パフォーマンス・プラットフォーム固有の注意
- 描画は `ctypes` と Creator-Defined Displayable を介して行われるため、メッシュの頂点数が極端に多いアニメーションや、大量のパーティクルが飛び交うエフェクトが多数重なると、フレームレートに影響が出る可能性があります。
- デスクトップ版 (Windows, macOS, Linux) でのみネイティブライブラリがロードされる想定です。モバイル (Android, iOS) や Webプラットフォーム向けの実装は今後の課題となります。
