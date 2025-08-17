lang = 'ro'

import os, json, csv

data_path = 'data/2-metas/' + lang
output_csv_path = 'data/1-indexes/' + lang + '/matrices-list.csv'

with open(output_csv_path, mode='w', newline='', encoding='utf-8') as csv_file:
    # fieldnames = ['filename', 'context-code', 'context-name', 'matrixName', 'ultimaActualizare', 'definitie', 'periodicitati']
    fieldnames = ['filename', 'context-code',  'matrixName', 'ultimaActualizare']
    writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
    writer.writeheader()

    for filename in os.listdir(data_path):
        if filename.endswith('.json'):
            file_path = os.path.join(data_path, filename)
            
            try:
                with open(file_path, 'r', encoding='utf-8') as json_file:
                    data = json.load(json_file)
            except UnicodeDecodeError:
                with open(file_path, 'r', encoding='latin-1') as json_file:
                    data = json.load(json_file)
                
            # Extract the required data
            ancestors = data.get('ancestors', [])
            if ancestors:
                last_ancestor = ancestors[-1]
                context_code = last_ancestor.get('code', '')
                context_name = last_ancestor.get('name', '')
            else:
                context_code = ''
                context_name = ''
            
            matrix_name = data.get('matrixName', '')
            ultima_actualizare = data.get('ultimaActualizare', '')
            definitie = data.get('definitie', '')
            periodicitati = data.get('periodicitati', '')
            
            # get filename without extension
            filename = os.path.splitext(filename)[0]
            # Write the row to the CSV
            writer.writerow({
                'filename': filename,
                'context-code': context_code,
                # 'context-name': context_name,
                'matrixName': matrix_name,
                'ultimaActualizare': ultima_actualizare
                # 'definitie': definitie,
                # 'periodicitati':  periodicitati
            })

print(f'CSV file has been created at {output_csv_path}')