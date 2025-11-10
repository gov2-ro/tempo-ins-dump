lang = "ro"
json_directory = 'data/2-metas/' + lang
database_file = 'data/3-db/' + lang + '/tempo-indexes.db'

import sqlite3
import json
import os


# Create or connect to the SQLite database
conn = sqlite3.connect(database_file)
cursor = conn.cursor()

# Create the "datasets" table
# filename TEXT PRIMARY KEY,
cursor.execute('''
    CREATE TABLE IF NOT EXISTS datasets (
        filename TEXT PRIMARY KEY,
        ancestors_1_code TEXT,
        ancestors_2_code TEXT,
        ancestors_3_code TEXT,
        ancestors_4_code TEXT,
        matrixName TEXT,
        periodicitati TEXT,
        definitie TEXT,
        ultimaActualizare TEXT,
        metodologie TEXT,
        observatii TEXT,
        persoaneResponsabile TEXT,
        intrerupere_lastPeriod TEXT,
        continuareSerie TEXT,
        nomJud INTEGER,
        nomLoc INTEGER,
        matMaxDim INTEGER,
        matUMSpec INTEGER,
        matSiruta INTEGER,
        matCaen1 INTEGER,
        matCaen2 INTEGER,
        matRegJ INTEGER,
        matCharge INTEGER,
        matViews INTEGER,
        matDownloads INTEGER,
        matActive INTEGER,
        matTime INTEGER,
        dim_labels TEXT
    )
''')

# Create the "fields" table
cursor.execute('''
    CREATE TABLE IF NOT EXISTS fields (
        fileid TEXT,
        dim_label TEXT,
        dimCode INTEGER,
        opt_label TEXT,
        nomItemId INTEGER,
        offset INTEGER,
        parentId INTEGER
    )
''')

# Loop through each JSON file in the directory
for json_file in os.listdir(json_directory):
    if json_file.endswith('.json'):
        with open(os.path.join(json_directory, json_file), 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except:
                print('buba')
                continue
                
        filename = os.path.splitext(json_file)[0]
        ancestors = data.get('ancestors', [])
        ancestors_1_code = ancestors[0]['code'] if len(ancestors) > 0 else None
        ancestors_2_code = ancestors[1]['code'] if len(ancestors) > 1 else None
        ancestors_3_code = ancestors[2]['code'] if len(ancestors) > 2 else None
        ancestors_4_code = ancestors[3]['code'] if len(ancestors) > 3 else None
        matrixName = data['matrixName']
        periodicitati = ', '.join(data['periodicitati'])
        try:
            definitie = data['definitie']
        except:
            breakpoint()
        ultimaActualizare = data['ultimaActualizare']
        metodologie = data['metodologie']
        observatii = data['observatii']
        persoaneResponsabile = data['persoaneResponsabile']
        # persoaneResponsabile = 'zz'
        intrerupere_data = data['intrerupere']
        intrerupere_lastPeriod = intrerupere_data['lastPeriod'] if intrerupere_data and 'lastPeriod' in intrerupere_data else ''
        # intrerupere_lastPeriod = 'x'


        # continuareSerie = data['continuareSerie']
        continuareSerie = 'kk'
        nomJud = data['details']['nomJud']
        nomLoc = data['details']['nomLoc']
        matMaxDim = data['details']['matMaxDim']
        matUMSpec = data['details']['matUMSpec']
        matSiruta = data['details']['matSiruta']
        matCaen1 = data['details']['matCaen1']
        matCaen2 = data['details']['matCaen2']
        matRegJ = data['details']['matRegJ']
        matCharge = data['details']['matCharge']
        matViews = data['details']['matViews']
        matDownloads = data['details']['matDownloads']
        matActive = data['details']['matActive']
        matTime = data['details']['matTime']

        # Extract dimension labels and store as JSON array
        dimensionsMap = data.get('dimensionsMap', [])
        dim_labels_list = [dimension['label'] for dimension in dimensionsMap]
        dim_labels_json = json.dumps(dim_labels_list, ensure_ascii=False)

        try:
            # have query in separate variable

            cursor.execute('''
                INSERT INTO datasets (filename, ancestors_1_code, ancestors_2_code, ancestors_3_code, ancestors_4_code, matrixName, periodicitati, definitie, ultimaActualizare, metodologie, observatii, persoaneResponsabile, intrerupere_lastPeriod, continuareSerie, nomJud, nomLoc, matMaxDim, matUMSpec, matSiruta, matCaen1, matCaen2, matRegJ, matCharge, matViews, matDownloads, matActive, matTime, dim_labels)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (filename, ancestors_1_code, ancestors_2_code, ancestors_3_code, ancestors_4_code, matrixName, periodicitati, definitie, ultimaActualizare, metodologie, observatii, persoaneResponsabile, intrerupere_lastPeriod, continuareSerie, nomJud, nomLoc, matMaxDim, matUMSpec, matSiruta, matCaen1, matCaen2, matRegJ, matCharge, matViews, matDownloads, matActive, matTime, dim_labels_json))
        except sqlite3.Error as e:
            print(f"E 116 inserting into 'datasets' table: {e}")
            print(filename, intrerupere_lastPeriod, continuareSerie, nomJud)

        # Extract data for the "fields" table
        # dimensionsMap already extracted above for dim_labels
        optionsCount = 0
        for dimension in dimensionsMap:
            dimCode = dimension['dimCode']
            dim_label = dimension['label']
            options = dimension['options']
            for option in options:
                optionsCount += 1
                opt_label = option['label']
                nomItemId = option['nomItemId']
                offset = option['offset']
                parentId = option['parentId']
                
                # Insert data into the "fields" table
                cursor.execute('''
                    INSERT INTO fields (fileid, dim_label, dimCode, opt_label, nomItemId, offset, parentId)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (filename, dim_label, dimCode, opt_label, nomItemId, offset, parentId))
            # TODO: insert 'optionsCount' into 'datasets'
# Commit changes and close the database connection
conn.commit()
conn.close()
