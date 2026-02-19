# 日本語カードデータ対応

このドキュメントでは、ポケモンTCG AIプロジェクトの日本語カードデータ対応について説明します。

## 概要

- **目的**: 既存の英語カードデータに日本語名（name_ja）を追加し、日本先行カード（Jレギュ等）も取得可能にする
- **データソース**: pokemon-card.com（ポケカ公式サイト）
- **対象レギュ**: H・I・J・XYレギュレーション
- **機能**: スクレイピング、マッピング、データ統合、CLI

## ファイル構成

```
scripts/
├── scrape_cards_ja.py          # 日本語カードスクレイパー（メイン）
├── integrate_japanese_data.py  # 英語-日本語データ統合
├── test_japanese_scraper.py    # テストスイート
├── japanese_cards_cli.py       # 統合CLIツール
└── README_ja.md               # 使い方ガイド

data/
├── cards_detailed.json             # 既存の英語カードDB
├── cards_detailed_integrated.json  # 日本語名追加版（出力）
├── ja_en_mapping.json              # 英語-日本語マッピング（出力）
└── cards_ja_*.json                # スクレイプした日本語データ
```

## 主要機能

### 1. 日本語カードスクレイパー (`scrape_cards_ja.py`)

**機能:**
- pokemon-card.com からカード詳細を取得
- レギュレーション別フィルタリング（H/I/J/XY）
- レートリミット対応（1秒/リクエスト）
- 日本語カード名、ワザ、特性、タイプの抽出

**使用例:**
```bash
# 特定カードをスクレイプ
./scripts/scrape_cards_ja.py --card-id 14890 --regulation XY

# Hレギュ全カードをスクレイプ（最大100枚）
./scripts/scrape_cards_ja.py --regulation H --output data/cards_ja_h.json --limit 100
```

**データ形式:**
```json
{
  "japanese_id": "14890",
  "regulation": "XY",
  "name_ja": "リザードンex",
  "type_ja": "炎",
  "type": "Fire",
  "hp": 330,
  "category": "pokemon",
  "attacks_ja": [
    {
      "name_ja": "燃える闇",
      "damage": "180+",
      "text_ja": "相手がとったサイド1枚につき、30ダメージ追加。",
      "cost": ["Fire", "Fire"]
    }
  ],
  "source_url": "https://www.pokemon-card.com/card-search/details.php/card/14890/regu/XY"
}
```

### 2. データ統合ツール (`integrate_japanese_data.py`)

**機能:**
- 英語カードと日本語カードの自動マッピング
- 名前類似度とセット番号による照合
- 既存データにname_jaフィールド追加
- 日本先行カードの新規追加

**マッピングアルゴリズム:**
1. **完全一致**: セットコードとカード番号で照合
2. **類似度マッチング**: カード名の類似度（閾値0.6以上）
3. **パターンマッチング**: 「ex」「GX」「V」等の特殊パターン
4. **追加情報**: HP、タイプ、レアリティでの補強

**使用例:**
```bash
# 統合実行
./scripts/integrate_japanese_data.py \
  --japanese-data data/cards_ja_h.json \
  --english-data data/cards_detailed.json \
  --output data/cards_detailed_integrated.json \
  --mapping-output data/ja_en_mapping.json
```

### 3. 統合CLIツール (`japanese_cards_cli.py`)

すべての機能を統合した使いやすいコマンドラインツール。

**主要コマンド:**

```bash
# テスト実行
./scripts/japanese_cards_cli.py test

# サンプルスクレイプ（数枚テスト）
./scripts/japanese_cards_cli.py sample --regulation H --limit 5

# 本格スクレイプ
./scripts/japanese_cards_cli.py scrape --regulation H --output data/cards_ja_h.json --limit 100

# データ統合
./scripts/japanese_cards_cli.py integrate --japanese-data data/cards_ja_h.json

# ワンステップ実行（スクレイプ→統合）
./scripts/japanese_cards_cli.py workflow --regulation H --limit 50
```

## セットコード対応表

| 英語セット | 日本セット | レギュ | 備考 |
|-----------|-----------|-------|------|
| PAL | sv1S/sv1V | H | パルデア地方セット |
| OBF | sv3 | H | 黒炎の支配者 |
| MEW | sv2D | H | ポケモンカード151 |
| BST | S6 | I | 連撃・一撃マスター |
| CRE | S7 | I | 白銀・漆黒 |
| EVS | S7 | I | 摩天・蒼空 |

## 取得可能データ

### ポケモンカード
- **基本情報**: name_ja, type_ja, hp, stage, evolvesFrom_ja
- **ワザ**: attacks_ja (名前、ダメージ、効果、エネルギーコスト)
- **特性**: abilities_ja (名前、効果)
- **その他**: weakness_ja, retreatCost, 各種フラグ（ex/GX/V等）

### トレーナーカード
- **基本情報**: name_ja, trainerType, text_ja
- **カテゴリ**: サポート、グッズ、スタジアム

### エネルギーカード
- **基本情報**: name_ja, type_ja, text_ja

## 注意事項・制限

### レートリミット
- **推奨**: 1秒/リクエスト以上
- **設定**: `--rate-limit 1.0` で調整可能
- **理由**: 公式サイトへの負荷軽減

### データ品質
- **成功率**: 約70-90%（サイト構造による）
- **検証**: テストスイートで品質チェック
- **エラー処理**: 失敗したカードは記録・再試行可能

### サイト依存性
- pokemon-card.com の HTML構造に依存
- サイト更新時は修正が必要
- JavaScript必須ページは対象外

## トラブルシューティング

### よくある問題

1. **カードが見つからない**
   ```
   Failed to fetch card 14890: Card not found or redirected
   ```
   - カードIDが無効または削除済み
   - レギュレーション指定を確認

2. **レート制限エラー**
   ```
   Too many requests
   ```
   - `--rate-limit` の値を増やす（2.0以上推奨）
   - 時間をおいて再実行

3. **統合時のマッピング失敗**
   ```
   No mappings created
   ```
   - 類似度閾値を下げる（0.4-0.5）
   - セットコード対応表を確認

### デバッグ方法

```bash
# 詳細ログ出力
./scripts/japanese_cards_cli.py scrape --regulation H --verbose

# テスト実行でサイト接続確認
./scripts/japanese_cards_cli.py test

# 少数サンプルで動作確認
./scripts/japanese_cards_cli.py sample --limit 3
```

## 今後の拡張

### 予定機能
- **デッキ情報取得**: pokecabook.com等からの環境データ取得
- **画像URL取得**: カード画像の直接リンク
- **リアルタイム更新**: 新弾リリース時の自動更新
- **APIモード**: ウェブAPIとしての提供

### データベース改善
- **検索インデックス**: 日本語名での高速検索
- **バージョン管理**: データ更新履歴の管理
- **キャッシュ機能**: 重複スクレイプの防止

## ライセンス・免責

- **用途**: 研究・学習目的のみ
- **レート制限**: 必ず遵守すること
- **著作権**: ポケモン関連の著作権は各権利者に帰属
- **責任**: スクレイプによる問題は利用者の責任

---

## クイックスタート

1. **テスト実行**:
   ```bash
   cd /Users/molt/.openclaw/workspace/pokemon-tcg-ai
   ./scripts/japanese_cards_cli.py test
   ```

2. **サンプル取得**:
   ```bash
   ./scripts/japanese_cards_cli.py sample --regulation H
   ```

3. **本格運用**:
   ```bash
   ./scripts/japanese_cards_cli.py workflow --regulation H --limit 100
   ```

これで既存の `data/cards_detailed.json` に日本語名が追加された `data/cards_detailed_integrated.json` が作成されます。