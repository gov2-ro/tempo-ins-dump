#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Romanian Text Word Frequency Counter
Analyzes word frequency in Romanian titles while filtering out common stopwords.
"""

import re
from collections import Counter
import argparse
import sys
import csv

# Romanian stopwords (common ligature words and articles)

ROMANIAN_STOPWORDS = {
    'a',  'ai', 'al', 'ale', 'am', 'ar', 'are', 'as', 'asa', 'asemenea', 'asta', 'astea', 'astei','asupra', 'atare', 'atat', 'atata', 'atatea', 'atatia', 'ati', 'avea', 'aveam', 'avem', 'avut','azi', 'bine', 'bucur', 'buna', 'ca', 'cam', 'care', 'carei', 'caror', 'catre', 'caut', 'ce','cea', 'ceea', 'cei', 'ceilalti', 'cel', 'cele', 'celor', 'ceva', 'chiar', 'cinci', 'cine','cineva', 'cit', 'cita', 'cite', 'citeva', 'citi', 'citiva', 'combinat', 'combinata', 'conform', 'cu', 'cum', 'cumva','curând', 'da', 'daca', 'dar', 'dat', 'dată', 'datorita', 'de', 'decât','deci', 'deja', 'deoarece', 'departe', 'desi', 'despre', 'din', 'dupa', 'ea', 'ei', 'el', 'ele','era', 'eram', 'este', 'eu', 'exact', 'fără', 'fata', 'fi', 'fie', 'fiind', 'foarte', 'fost','frumos', 'geaba', 'halbă', 'iar', 'ieri', 'ii', 'îi', 'il', 'îl', 'imi', 'îmi', 'împotriva', 'in','în', 'inainte', 'înainte', 'înaintea', 'inapoi', 'inca', 'încât', 'încotro','incotro', 'insa', 'intr', 'între', 'întrucât', 'întrucît', 'isi', 'îsi', 'îti''iti', 'la', 'langa','le', 'li', 'luat', 'ma', 'mă', 'mai', 'majore', 'majoritar', 'mare', 'mea', 'mei', 'mele', 'mereu', 'meu', 'mi', 'mult','multa', 'multe', 'multi', 'ne', 'nevoie', 'ni', 'nici', 'nimeni', 'nimic', 'niste','noi', 'nostra', 'nostre', 'nostri', 'nostru', 'nu', 'numai', 'numarul', 'o', 'opt', 'ori', 'oricând', 'oricare','orice', 'oricine', 'oricum', 'oriunde', 'pai', 'parca', 'pare', 'pe', 'pentru', 'poate', 'pot','prea', 'prima', 'primul', 'prin', 'sa', 'sai', 'sale', 'sau', 'său', 'se', 'si','și', 'sua', 'sub', 'sunt', 'suntem', 'sunteți', 'sus', 'ta', 'tale', 'ti', 'timp', 'tine', 'toata','toate', 'toți', 'totul', 'tu', 'un', 'una', 'unde', 'undeva', 'unei', 'unele', 'uneori','unor', 'unora', 'unu', 'unui', 'unul', 'uri', 'va', 'vi', 'vii', 'voastre', 'vostru', 'vrea','vreo', 'vreun' 
}

def clean_text(text):
    """
    Clean and normalize text for word frequency analysis.
    
    Args:
        text (str): Input text
        
    Returns:
        str: Cleaned text
    """
    # Convert to lowercase
    text = text.lower()
    
    # Remove punctuation and special characters, keep only letters and spaces
    text = re.sub(r'[^a-zA-ZăîâțșĂÎÂȚȘ\s]', ' ', text)
    
    # Replace multiple spaces with single space
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()

def extract_words(text):
    """
    Extract words from text, filtering out stopwords.
    
    Args:
        text (str): Input text
        
    Returns:
        list: List of filtered words
    """
    words = text.split()
    
    # Filter out stopwords and very short words
    filtered_words = [
        word for word in words 
        if word not in ROMANIAN_STOPWORDS and len(word) > 2
    ]
    
    return filtered_words

def analyze_word_frequency(file_path, min_frequency=1, top_n=None):
    """
    Analyze word frequency in a text file containing Romanian titles.
    
    Args:
        file_path (str): Path to the input text file
        min_frequency (int): Minimum frequency threshold for words to include
        top_n (int): Number of top words to return (None for all)
        
    Returns:
        Counter: Word frequency counter
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found.")
        return None
    except UnicodeDecodeError:
        print(f"Error: Unable to decode file '{file_path}'. Please ensure it's UTF-8 encoded.")
        return None
    
    # Process text
    cleaned_content = clean_text(content)
    words = extract_words(cleaned_content)
    
    # Count word frequencies
    word_freq = Counter(words)
    
    # Filter by minimum frequency
    if min_frequency > 1:
        word_freq = Counter({word: count for word, count in word_freq.items() 
                           if count >= min_frequency})
    
    return word_freq

def display_results(word_freq, top_n=None):
    """
    Display word frequency results.
    
    Args:
        word_freq (Counter): Word frequency counter
        top_n (int): Number of top words to display
    """
    if not word_freq:
        print("No words found or file could not be processed.")
        return
    
    print(f"\nWord Frequency Analysis")
    print("=" * 50)
    print(f"Total unique words: {len(word_freq)}")
    print(f"Total word occurrences: {sum(word_freq.values())}")
    print("=" * 50)
    
    # Get most common words
    most_common = word_freq.most_common(top_n)
    
    print(f"\nTop {len(most_common)} words:")
    print("-" * 30)
    
    for i, (word, count) in enumerate(most_common, 1):
        print(f"{i:3d}. {word:<20} : {count:>4d}")

def save_results(word_freq, output_file, top_n=None):
    """
    Save word frequency results to a file.
    
    Args:
        word_freq (Counter): Word frequency counter
        output_file (str): Output file path
        top_n (int): Number of top words to save
    """
    try:
        with open(output_file, 'w', encoding='utf-8') as file:
            file.write("Word Frequency Analysis\n")
            file.write("=" * 50 + "\n")
            file.write(f"Total unique words: {len(word_freq)}\n")
            file.write(f"Total word occurrences: {sum(word_freq.values())}\n")
            file.write("=" * 50 + "\n\n")
            
            most_common = word_freq.most_common(top_n)
            file.write(f"Top {len(most_common)} words:\n")
            file.write("-" * 30 + "\n")
            
            for i, (word, count) in enumerate(most_common, 1):
                file.write(f"{i:3d}. {word:<20} : {count:>4d}\n")
                
        print(f"\nResults saved to: {output_file}")
        
    except Exception as e:
        print(f"Error saving results: {e}")

def save_results_csv(word_freq, output_file, top_n=None):
    """
    Save word frequency results to a CSV file.
    
    Args:
        word_freq (Counter): Word frequency counter
        output_file (str): Output CSV file path
        top_n (int): Number of top words to save
    """
    try:
        with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            
            # Write header
            writer.writerow(['Rank', 'Word', 'Frequency'])
            
            # Write data
            most_common = word_freq.most_common(top_n)
            for i, (word, count) in enumerate(most_common, 1):
                writer.writerow([i, word, count])
                
        print(f"\nResults saved to CSV: {output_file}")
        
    except Exception as e:
        print(f"Error saving CSV results: {e}")

def main():
    """Main function with command line interface."""
    parser = argparse.ArgumentParser(
        description="Analyze word frequency in Romanian titles, filtering out common stopwords."
    )
    parser.add_argument("input_file", help="Input text file containing titles")
    parser.add_argument("-n", "--top", type=int, help="Number of top words to display")
    parser.add_argument("-m", "--min-freq", type=int, default=1, 
                       help="Minimum frequency threshold (default: 1)")
    parser.add_argument("-o", "--output", help="Output file to save results")
    parser.add_argument("--csv", help="Output CSV file to save results")
    
    args = parser.parse_args()
    
    # Analyze word frequency
    word_freq = analyze_word_frequency(args.input_file, args.min_freq, args.top)
    
    if word_freq is None:
        sys.exit(1)
    
    # Display results
    display_results(word_freq, args.top)
    
    # Save results if output file specified
    if args.output:
        save_results(word_freq, args.output, args.top)
    
    # Save results to CSV if specified
    if args.csv:
        save_results_csv(word_freq, args.csv, args.top)

# Example usage function
def example_usage():
    """Example of how to use the script programmatically."""
    # Example for direct usage in code
    file_path = "repository/labels.txt"  # Replace with your file path
    
    print("Analyzing word frequency...")
    word_freq = analyze_word_frequency(file_path, min_frequency=2)
    
    if word_freq:
        display_results(word_freq, top_n=20)
        # Optionally save results
        # save_results(word_freq, "word_frequency_results.txt", top_n=50)

if __name__ == "__main__":
    main()