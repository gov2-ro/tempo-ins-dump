import os, json, csv, argparse


def main():
    parser = argparse.ArgumentParser(description='Build summary index CSV from metadata JSONs')
    parser.add_argument('--lang', default='ro', choices=['ro', 'en'], help='Language (default: ro)')
    args = parser.parse_args()
    lang = args.lang

    data_path = 'data/2-metas/' + lang
    output_csv_path = 'data/1-indexes/' + lang + '/matrices-list.csv'

    os.makedirs(os.path.dirname(output_csv_path), exist_ok=True)

    with open(output_csv_path, mode='w', newline='', encoding='utf-8') as csv_file:
        fieldnames = ['filename', 'context-code', 'matrixName', 'ultimaActualizare']
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
                else:
                    context_code = ''

                matrix_name = data.get('matrixName', '')
                ultima_actualizare = data.get('ultimaActualizare', '')

                # get filename without extension
                filename = os.path.splitext(filename)[0]
                writer.writerow({
                    'filename': filename,
                    'context-code': context_code,
                    'matrixName': matrix_name,
                    'ultimaActualizare': ultima_actualizare
                })

    print(f'CSV file has been created at {output_csv_path}')


if __name__ == '__main__':
    main()
