#!/usr/bin/env python3
"""
Simple verification script for the static site
"""

import json
import requests
import sys

def test_static_site():
    base_url = "http://localhost:8080"
    
    try:
        # Test main page
        print("Testing main page...")
        response = requests.get(f"{base_url}/index-static.html")
        assert response.status_code == 200
        assert "INS Data Explorer - Static" in response.text
        print("✅ Main page loads correctly")
        
        # Test datasets index
        print("Testing datasets index...")
        response = requests.get(f"{base_url}/data/datasets-index.json")
        assert response.status_code == 200
        datasets = response.json()
        assert len(datasets) > 0
        print(f"✅ Datasets index loads correctly ({len(datasets)} datasets)")
        
        # Test flags index
        print("Testing flags index...")
        response = requests.get(f"{base_url}/data/flags-index.json")
        assert response.status_code == 200
        flags = response.json()
        assert "counts" in flags
        print(f"✅ Flags index loads correctly ({len(flags['counts'])} flags)")
        
        # Test a specific dataset
        print("Testing dataset detail...")
        test_dataset = datasets[0]["id"]
        response = requests.get(f"{base_url}/data/datasets/{test_dataset}.json")
        assert response.status_code == 200
        dataset_detail = response.json()
        assert "columns" in dataset_detail
        print(f"✅ Dataset detail loads correctly ({test_dataset})")
        
        # Test static files
        print("Testing static files...")
        for file in ["explorer-static.js", "csv-parser.js", "explorer.css"]:
            response = requests.get(f"{base_url}/{file}")
            assert response.status_code == 200
        print("✅ All static files load correctly")
        
        print("\n🎉 All tests passed! Static site is working correctly.")
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        return False

if __name__ == "__main__":
    if not test_static_site():
        sys.exit(1)
