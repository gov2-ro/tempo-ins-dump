import re

class LabelClassifier:
    """
    A classifier to guess the semantic and functional types of a dataset column label
    based on a set of ordered, keyword-based rules derived from word frequency analysis.
    """

    def __init__(self):
        """
        Initializes the classifier with a refined set of rules.
        The rules are ordered by specificity to ensure accurate classification.
        """
        self.rules = [
            # --- Rule 1: Highest Priority - Unique Identifiers ---
            {
                "name": "Unit of Measure",
                "match_type": "prefix",
                "keywords": ["um:"],
                "categories": ["Unit", "Metadata"]
            },
            {
                "name": "Value",
                "match_type": "exact",
                "keywords": ["valoare"],
                "categories": ["Value", "Measure"]
            },
            
            # --- Rule 2: Core Semantic Types (High Confidence) ---
            {
                "name": "Time Dimension",
                "match_type": "keyword",
                "keywords": ["perioade", "ani", "anul", "luni", "trimestre", "durata"],
                "categories": ["Time", "Axis", "Filter"]
            },
            {
                "name": "Economic Sector Dimension",
                "match_type": "keyword",
                "keywords": [
                    "caen", "activitati", "rev", "economiei", "sectiuni", "diviziuni", 
                    "industriei", "sectoare", "intreprinderilor", "intreprinderi", 
                    "ramuri", "ocupatii"
                ],
                "categories": ["Economic Sector", "Axis", "Filter"]
            },
            {
                "name": "Geographic Dimension",
                "match_type": "keyword",
                "keywords": [
                    "judete", "regiuni", "localitati", "macroregiuni", "urban",
                    "rural", "tari", "continente", "orase", "municipii", "rezidenta"
                ],
                "categories": ["Geo", "Axis", "Filter"]
            },
            {
                "name": "Demographic Dimension",
                "match_type": "keyword",
                "keywords": [
                    "persoane", "varsta", "sexe", "sociale", "populatiei", "salariati",
                    "ocupational", "gospodariei", "membrilor", "statut", "stare civila",
                    "educatie", "pregatire"
                ],
                "categories": ["Demographic", "Filter", "Series"]
            },
             {
                "name": "Financial Dimension",
                "match_type": "keyword",
                "keywords": [
                    "pib", "brut", "financiar", "cheltuieli", "venituri", "costului", 
                    "bani", "conturi", "investitii", "preturi"
                ],
                "categories": ["Financial", "Filter"]
            },

            # --- Rule 3: General Classification / Grouping Keywords (Medium Confidence) ---
            {
                "name": "Generic Category for Series/Grouping",
                "match_type": "keyword",
                "keywords": [
                    "categorii", "tipuri", "grupe", "clase", "forme", "nivel", 
                    "modul", "structura"
                ],
                "categories": ["Generic Category", "Filter", "Series", "Axis"]
            }
        ]

    def _normalize_label(self, label: str) -> str:
        """Normalizes a label by converting to lowercase and removing punctuation."""
        label = label.lower()
        # Replace hyphens and slashes with spaces to treat words separately
        label = re.sub(r'[-/]', ' ', label)
        # Remove other punctuation
        label = re.sub(r'[^\w\s]', '', label)
        return label

    def classify(self, label: str) -> list[str]:
        """
        Classifies a single label based on the defined rules, returning a combined list of categories.
        """
        if not label:
            return ["Unknown"]

        normalized_label = self._normalize_label(label)
        detected_categories = set()

        for rule in self.rules:
            match_found = False
            # Split the label into words to check against keywords
            label_words = set(normalized_label.split())
            
            if rule["match_type"] == "prefix":
                if any(normalized_label.startswith(kw) for kw in rule["keywords"]):
                    match_found = True
            elif rule["match_type"] == "exact":
                if any(normalized_label == kw for kw in rule["keywords"]):
                    match_found = True
            elif rule["match_type"] == "keyword":
                # Check if any keyword is a substring or a full word in the label
                if any(kw in label_words for kw in rule["keywords"]):
                    match_found = True
            
            if match_found:
                detected_categories.update(rule["categories"])

        # If a primary type was found, ensure it also has a basic functional role
        if detected_categories and not detected_categories.intersection({"Value", "Unit"}):
             detected_categories.add("Filter")

        # If no specific rules match, apply the default
        if not detected_categories:
            return sorted(["Generic Category", "Filter"])

        return sorted(list(detected_categories))

# --- Example Usage ---
if __name__ == "__main__":
    classifier = LabelClassifier()
    
    # Load the labels from your word frequency file to test the new classifier
    # In a real scenario, you would load this from the CSV.
    labels_from_file = [
        "Categorii de salariati",
        "CAEN Rev.2  (activitati ale economiei nationale)",
        "Grupe de varsta",
        "UM: Milioane lei",
        "Productia si furnizarea de energie electrica si termica, gaze, apa calda si aer conditionat",
        "Regiuni de dezvoltare",
        "Un nou label despre Finante si Buget",
        "Natura accidentelor",
        "Sisteme de pensionare"
    ]

    print("--- Testing the Upgraded Label Classifier ---")
    for label in labels_from_file:
        categories = classifier.classify(label)
        print(f"Label: '{label}'\n  -> Categories: {categories}\n")