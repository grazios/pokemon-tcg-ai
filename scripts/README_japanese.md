# Japanese Pokémon TCG Cards - Quick Start Guide

This directory contains tools for scraping and integrating Japanese Pokémon card data from the official pokemon-card.com website.

## 🚀 Quick Start

### 1. Test the Setup
```bash
./scripts/japanese_cards_cli.py test
```

### 2. Sample a Few Cards
```bash
./scripts/japanese_cards_cli.py sample --regulation H --limit 5
```

### 3. Full Workflow (Recommended)
```bash
# Scrape cards from regulation H and integrate with English data
./scripts/japanese_cards_cli.py workflow --regulation H --limit 100
```

This will create:
- `data/cards_ja_scraped.json` - Raw Japanese card data
- `data/cards_detailed_integrated.json` - English cards + Japanese names
- `data/ja_en_mapping.json` - English-Japanese mappings

## 📋 Available Commands

### `test`
Run comprehensive test suite to verify functionality.

### `sample`
Quick test scraping of a few cards.
```bash
./scripts/japanese_cards_cli.py sample --regulation H --limit 5 --output sample.json
```

### `scrape`
Scrape Japanese cards from pokemon-card.com.
```bash
# Scrape all cards from regulation H
./scripts/japanese_cards_cli.py scrape --regulation H --output cards_ja_h.json --limit 100

# Scrape specific card by ID
./scripts/japanese_cards_cli.py scrape --card-id 15001 --regulation XY --output single_card.json
```

### `integrate`
Merge Japanese data with existing English cards.
```bash
./scripts/japanese_cards_cli.py integrate \
  --japanese-data cards_ja_h.json \
  --english-data data/cards_detailed.json \
  --output cards_integrated.json
```

### `workflow`
Complete pipeline: scrape → integrate → report.
```bash
./scripts/japanese_cards_cli.py workflow --regulation H --limit 50
```

## 🎯 Available Regulations

- **H**: Current Pokémon cards (Scarlet & Violet era)
- **I**: Previous generation (Sword & Shield era)  
- **J**: Japan-exclusive cards
- **XY**: Legacy cards (for testing)

## 📊 Data Output

### Japanese Card Format
```json
{
  "japanese_id": "15001",
  "regulation": "XY", 
  "name_ja": "ハヤシガメ",
  "type_ja": "草",
  "type": "Grass",
  "hp": 80,
  "category": "pokemon",
  "attacks_ja": [
    {
      "name_ja": "たいあたり",
      "damage": "20",
      "text_ja": "...",
      "cost": ["Grass"]
    }
  ],
  "source_url": "https://www.pokemon-card.com/card-search/details.php/card/15001/regu/XY"
}
```

### Integrated Card Format
Existing English cards get additional Japanese fields:
```json
{
  "id": "OBF-125",
  "name": "Charizard ex - Obsidian Flames",
  "name_ja": "リザードンex",
  "set": "OBF",
  "japanese_source": {
    "japanese_id": "sv3_101",
    "regulation": "H", 
    "mapping_type": "name_similarity",
    "similarity_score": 0.85
  }
}
```

## ⚙️ Configuration

### Rate Limiting
Always respect the rate limit to avoid being blocked:
```bash
# 1 second between requests (recommended)
./scripts/japanese_cards_cli.py scrape --rate-limit 1.0

# More conservative (safer for large scrapes)
./scripts/japanese_cards_cli.py scrape --rate-limit 2.0
```

### Similarity Threshold
Control how strict the English-Japanese matching is:
```bash
# Strict matching (fewer false positives)
./scripts/japanese_cards_cli.py integrate --similarity-threshold 0.8

# Relaxed matching (more matches, some false positives)
./scripts/japanese_cards_cli.py integrate --similarity-threshold 0.4
```

## 🔧 Troubleshooting

### Common Issues

1. **No cards found**
   - Check internet connection
   - Try a different regulation (XY for testing)
   - Verify card IDs exist on pokemon-card.com

2. **Rate limiting errors**
   - Increase `--rate-limit` value
   - Wait and retry

3. **Low mapping success**
   - Lower `--similarity-threshold`
   - Check set code mappings in the integration script

### Debug Mode
Add `--verbose` flag for detailed logging:
```bash
./scripts/japanese_cards_cli.py --verbose workflow --regulation H
```

## 📁 File Structure

```
scripts/
├── japanese_cards_cli.py          # Main CLI tool (use this!)
├── scrape_cards_ja.py             # Core scraper
├── integrate_japanese_data.py     # Data integration  
├── test_japanese_scraper.py       # Test suite
└── README_japanese.md            # This file

data/
├── cards_detailed.json             # Original English cards
├── cards_detailed_integrated.json  # Output: English + Japanese
├── ja_en_mapping.json              # Output: Mapping data
└── cards_ja_*.json                # Scraped Japanese data
```

## 📈 Expected Results

Based on testing:
- **Scraping Success Rate**: ~70-90% (depends on site structure)
- **Mapping Success Rate**: ~60-80% (depends on similarity threshold)
- **Performance**: ~1 card per second (with rate limiting)

## ⚠️ Important Notes

1. **Respect Rate Limits**: Always use at least 1 second delays
2. **Data Quality**: Some cards may have incomplete data due to site structure
3. **Site Dependencies**: Scraper depends on pokemon-card.com HTML structure
4. **Legal**: For research/educational use only

## 🎯 Next Steps

1. Run the test suite to verify everything works
2. Use `sample` command to get familiar with the output
3. Run `workflow` for your target regulation
4. Integrate the resulting data into your AI training pipeline

For more detailed documentation, see `docs/japanese_cards.md`.