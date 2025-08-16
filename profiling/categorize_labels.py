import pandas as pd
import re

def categorize_label(label):
    """
    Categorize labels based on their content and patterns
    """
    label_lower = label.lower()
    
    # Geographic/Administrative categories
    if any(word in label_lower for word in ['judete', 'regiuni', 'macroregiuni', 'localitati', 'municipii', 'orase', 'tari', 'romania', 'uniunea europeana', 'zone']):
        return 'Geographic/Administrative'
    
    # Demographic categories
    if any(word in label_lower for word in ['ani', 'sexe', 'grupe de varsta', 'varsta', 'populatie', 'persoane', 'nascuti', 'decedati', 'casatorii', 'divorturi']):
        return 'Demographics'
    
    # Time-related categories
    if any(word in label_lower for word in ['perioade', 'luni', 'trimestre', 'ani/', 'ani de']):
        return 'Time Period'
    
    # Economic/Business categories
    if any(word in label_lower for word in ['caen', 'activitati', 'intreprinderi', 'salariati', 'sectoare', 'industrie', 'comert', 'servicii']):
        return 'Economic/Business'
    
    # Education categories
    if any(word in label_lower for word in ['educatie', 'invatamant', 'scolare', 'nivel de pregatire', 'pregatire']):
        return 'Education'
    
    # Measurement units
    if label_lower.startswith('um:'):
        return 'Units of Measurement'
    
    # Health/Medical categories
    if any(word in label_lower for word in ['sanatate', 'medical', 'boli', 'maladii', 'sanitare', 'medic']):
        return 'Health/Medical'
    
    # Agriculture/Environment
    if any(word in label_lower for word in ['agricol', 'paduri', 'ape', 'mediu', 'terenuri', 'culturi', 'animale', 'productie agricola']):
        return 'Agriculture/Environment'
    
    # Transport/Infrastructure
    if any(word in label_lower for word in ['transport', 'vehicule', 'drumuri', 'cai ferata', 'nave', 'aeronave']):
        return 'Transport/Infrastructure'
    
    # Social categories
    if any(word in label_lower for word in ['forme de proprietate', 'statut', 'categorii sociale', 'ocupational', 'profesional']):
        return 'Social Status'
    
    # Tourism/Culture
    if any(word in label_lower for word in ['turistic', 'turisti', 'cultura', 'muzee', 'biblioteci', 'spectacol', 'arte']):
        return 'Tourism/Culture'
    
    # Technology/Communication
    if any(word in label_lower for word in ['internet', 'computer', 'telefonie', 'comunicatii', 'tehnolog']):
        return 'Technology/Communication'
    
    # Finance/Economic indicators
    if any(word in label_lower for word in ['lei', 'euro', 'dolari', 'milioane lei', 'cheltuieli', 'venituri', 'investitii', 'credite']):
        return 'Finance/Economic Indicators'
    
    # Living conditions/Housing
    if any(word in label_lower for word in ['locuinte', 'gospodarii', 'confort', 'dotarea', 'camere']):
        return 'Housing/Living Conditions'
    
    # Categories/Classifications (general)
    if any(word in label_lower for word in ['categorii de', 'tipuri de', 'clase de', 'grupe de']):
        return 'Categories/Classifications'
    
    # Default category for unmatched labels
    return 'Other'

# Read the CSV file
df = pd.read_csv('/Users/pax/devbox/gov2/tempoins/repository/labels.csv')

# Apply categorization
df['categories'] = df['label'].apply(categorize_label)

# Display category distribution
print("Category Distribution:")
print(df['categories'].value_counts())
print(f"\nTotal labels: {len(df)}")

# Save to new file
output_file = '/Users/pax/devbox/gov2/tempoins/repository/labels_with_categories.csv'
df.to_csv(output_file, index=False)
print(f"\nNew file saved as: {output_file}")

# Show sample of categorized data
print("\nSample of categorized data:")
print(df[['label', 'categories']].head(20))
