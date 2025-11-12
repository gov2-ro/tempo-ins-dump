# lang = "ro"
lang = "en"
csv_filename = 'data/1-indexes/' + lang + '/matrices.csv'

import requests
import csv

url = 'http://statistici.insse.ro:8077/tempo-ins/matrix/matrices?lang=' + lang

headers = {
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-GB,en;q=0.8',
    'Connection': 'keep-alive',
    'Referer': 'http://statistici.insse.ro:8077/tempo-online/',
    'Sec-GPC': '1',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36',
}

response = requests.get(url, headers=headers)

if response.status_code == 200:
    data = response.json()

    flattened_data = [[item['name'], item['code'], item['childrenUrl'], item['comment'], item['url']] for item in data]

    with open(csv_filename, 'w', newline='') as csv_file:
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(['name', 'code', 'childrenUrl', 'comment', 'url'])  # Write header
        csv_writer.writerows(flattened_data)

    print(f'Data saved as {csv_filename}')
else:
    print(f'Failed to fetch data. Status code: {response.status_code}')
