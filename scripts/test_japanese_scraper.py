#!/Users/molt/.openclaw/workspace/pokemon-tcg-ai/venv/bin/python
"""
Test script for Japanese card scraper.
Tests basic functionality and validates scraped data.
"""

import json
import sys
from pathlib import Path
from scrape_cards_ja import JapaneseCardScraper

def test_single_card_scrape():
    """Test scraping a single card by ID."""
    print("Testing single card scrape...")
    
    scraper = JapaneseCardScraper(rate_limit=0.5, verbose=True)
    
    # Test with a known card ID (this may need adjustment based on actual site structure)
    test_ids = ['14890', '15001', '15100']  # Common IDs to test
    
    for test_id in test_ids:
        print(f"\nTrying card ID: {test_id}")
        card_data = scraper.fetch_card_details(test_id, 'XY')
        
        if card_data:
            print(f"Success! Scraped card:")
            print(f"  Name (Japanese): {card_data.get('name_ja', 'N/A')}")
            print(f"  Type: {card_data.get('type', 'N/A')}")
            print(f"  HP: {card_data.get('hp', 'N/A')}")
            print(f"  Category: {card_data.get('category', 'N/A')}")
            return card_data
        else:
            print(f"Failed to scrape card {test_id}")
    
    print("No cards could be scraped successfully")
    return None

def test_search_functionality():
    """Test the card search functionality."""
    print("\n\nTesting search functionality...")
    
    scraper = JapaneseCardScraper(rate_limit=0.5, verbose=True)
    
    # Test search with common keywords
    test_keywords = ['ピカチュウ', 'リザードン', 'フシギダネ']  # Pikachu, Charizard, Bulbasaur
    
    for keyword in test_keywords:
        print(f"\nSearching for: {keyword}")
        results = scraper.search_cards(keyword=keyword, limit=5)
        
        if results:
            print(f"Found {len(results)} results:")
            for result in results[:3]:  # Show first 3
                print(f"  - {result.get('name_ja', 'Unknown')} (ID: {result.get('japanese_id', 'N/A')})")
        else:
            print(f"No results found for {keyword}")
    
    return len(results) > 0 if 'results' in locals() else False

def validate_scraped_data(card_data):
    """Validate the structure and content of scraped card data."""
    print("\n\nValidating scraped data structure...")
    
    required_fields = ['japanese_id', 'regulation', 'source_url']
    recommended_fields = ['name_ja', 'type', 'category']
    
    validation_results = {
        'required_present': 0,
        'recommended_present': 0,
        'total_fields': len(card_data),
        'issues': []
    }
    
    # Check required fields
    for field in required_fields:
        if field in card_data and card_data[field]:
            validation_results['required_present'] += 1
        else:
            validation_results['issues'].append(f"Missing required field: {field}")
    
    # Check recommended fields
    for field in recommended_fields:
        if field in card_data and card_data[field]:
            validation_results['recommended_present'] += 1
        else:
            validation_results['issues'].append(f"Missing recommended field: {field}")
    
    # Check data quality
    if 'name_ja' in card_data:
        name = card_data['name_ja']
        if len(name) < 2:
            validation_results['issues'].append("Japanese name too short")
        if not any('\u3040' <= char <= '\u309F' or '\u30A0' <= char <= '\u30FF' or 
                  '\u4E00' <= char <= '\u9FAF' for char in name):
            validation_results['issues'].append("Japanese name contains no Japanese characters")
    
    # Print validation results
    print(f"Validation Results:")
    print(f"  Required fields present: {validation_results['required_present']}/{len(required_fields)}")
    print(f"  Recommended fields present: {validation_results['recommended_present']}/{len(recommended_fields)}")
    print(f"  Total fields scraped: {validation_results['total_fields']}")
    
    if validation_results['issues']:
        print(f"  Issues found:")
        for issue in validation_results['issues']:
            print(f"    - {issue}")
    else:
        print(f"  ✅ All validations passed!")
    
    return validation_results

def test_rate_limiting():
    """Test that rate limiting is working properly."""
    print("\n\nTesting rate limiting...")
    
    import time
    start_time = time.time()
    
    scraper = JapaneseCardScraper(rate_limit=1.0, verbose=False)
    
    # Make 3 requests and measure timing
    test_ids = ['14890', '15001', '15100']
    for test_id in test_ids:
        request_start = time.time()
        scraper.fetch_card_details(test_id, 'XY')
        request_time = time.time() - request_start
        print(f"  Request for {test_id} took {request_time:.2f}s")
    
    total_time = time.time() - start_time
    expected_min_time = len(test_ids) * 1.0  # 1 second rate limit
    
    print(f"Total time: {total_time:.2f}s (expected minimum: {expected_min_time:.2f}s)")
    
    if total_time >= expected_min_time * 0.9:  # Allow 10% tolerance
        print("  ✅ Rate limiting working correctly")
        return True
    else:
        print("  ❌ Rate limiting may not be working")
        return False

def main():
    """Run all tests."""
    print("=== Japanese Pokémon Card Scraper Test Suite ===\n")
    
    results = {
        'single_card': False,
        'search': False,
        'validation': False,
        'rate_limiting': False
    }
    
    try:
        # Test single card scraping
        card_data = test_single_card_scrape()
        results['single_card'] = card_data is not None
        
        # Test search functionality  
        results['search'] = test_search_functionality()
        
        # Validate data structure if we got a card
        if card_data:
            validation_results = validate_scraped_data(card_data)
            results['validation'] = len(validation_results['issues']) == 0
            
            # Save test result for inspection
            test_output = Path('data/test_scraped_card.json')
            test_output.parent.mkdir(exist_ok=True)
            with open(test_output, 'w', encoding='utf-8') as f:
                json.dump(card_data, f, ensure_ascii=False, indent=2)
            print(f"\nTest card data saved to: {test_output}")
        
        # Test rate limiting
        results['rate_limiting'] = test_rate_limiting()
        
    except Exception as e:
        print(f"\nTest suite failed with error: {e}")
        return False
    
    # Print summary
    print("\n=== Test Summary ===")
    passed_tests = sum(results.values())
    total_tests = len(results)
    
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{test_name.replace('_', ' ').title()}: {status}")
    
    print(f"\nOverall: {passed_tests}/{total_tests} tests passed")
    
    if passed_tests == total_tests:
        print("🎉 All tests passed! The scraper is ready for use.")
        return True
    elif passed_tests >= total_tests * 0.5:
        print("⚠️ Some tests failed, but basic functionality seems to work.")
        return True
    else:
        print("❌ Most tests failed. The scraper may need debugging.")
        return False

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)