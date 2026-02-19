# Pokemon TCG Card Scraper

自動でポケモンカードのデータを取得するCLIツールです。Limitless TCGから詳細情報をスクレイピングして構造化されたJSONファイルに保存します。

## 使用方法

### 基本的な使い方
```bash
# カードIDを直接指定（複数指定可能）
./scripts/scrape_cards.py --cards "OBF 125" "MEG 114" "PAL 190"

# ファイルからカードリストを読み込み
./scripts/scrape_cards.py --file data/target_cards.txt

# 出力先を指定
./scripts/scrape_cards.py --cards "OBF 125" -o /path/to/output.json

# レートリミット調整（デフォルト1.0秒）
./scripts/scrape_cards.py --cards "OBF 125" --rate-limit 0.5

# 既存カードを強制再取得
./scripts/scrape_cards.py --cards "OBF 125" --force

# 詳細ログ表示
./scripts/scrape_cards.py --cards "OBF 125" -v
```

### カードID形式
以下の形式に対応：
- `OBF 125` - セット名 番号
- `OBF-125` - セット名-番号
- `Charizard ex (OBF 125)` - カード名 (セット名 番号)

### 差分更新
既存のJSONファイルがある場合、自動で差分のみ取得します：
```bash
# 最初の実行
./scripts/scrape_cards.py --file data/deck1.txt

# 追加カードのみ取得（重複は自動スキップ）
./scripts/scrape_cards.py --cards "TWM 130" "SCR 111"
```

## 出力データ構造

### ポケモンカード
```json
{
  "id": "OBF-125",
  "name": "Charizard ex",
  "set": "OBF",
  "number": "125",
  "category": "pokemon",
  "type": "Dark",
  "hp": 330,
  "stage": "Stage 2",
  "evolvesFrom": "Charmeleon",
  "isEx": true,
  "abilities": [{"name": "Infernal Reign", "text": "..."}],
  "attacks": [{"name": "Burning Darkness", "cost": ["Fire", "Fire"], "damage": "180+", "text": "..."}],
  "weakness": "Grass",
  "retreatCost": 2
}
```

### トレーナーカード
```json
{
  "id": "MEG-114",
  "name": "Boss's Orders",
  "set": "MEG",
  "number": "114",
  "category": "trainer",
  "trainerType": "Supporter",
  "text": "Switch 1 of your opponent's Benched Pokémon with their Active Pokémon."
}
```

### エネルギーカード
```json
{
  "id": "PAL-190",
  "name": "Jet Energy",
  "set": "PAL",
  "number": "190",
  "category": "energy",
  "energyType": "special",
  "text": "As long as this card is attached to a Pokémon, it provides [C] Energy. When you attach this card from your hand to 1 of your Benched Pokémon, switch that Pokémon with your Active Pokémon."
}
```

## 実行環境

- Python 3.12 (仮想環境使用)
- 依存パッケージ: requests, beautifulsoup4
- データソース: Limitless TCG (https://limitlesstcg.com/)

## トラブルシューティング

### よくあるエラー
1. **レート制限エラー**: `--rate-limit` の値を大きく（1.0以上）
2. **ネットワークエラー**: インターネット接続を確認
3. **パース失敗**: 新しいカードセットの場合、HTMLパーサーの更新が必要な可能性

### スクリプトの更新
新しいセットに対応するため、HTMLパース処理を適宜更新してください。