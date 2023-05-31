import json
import time

import requests
from tqdm import tqdm

from data_loading import read_csvs

url = 'https://api.esmatlas.com/foldSequence/v1/pdb'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36 Edg/111.0.1661.41',
    'Accept': 'application/json, text/plain, */*',
    'origin': 'https://esmatlas.com',
    'content-type': 'text/plain'}

csvs_data = read_csvs(data_filter=lambda x: len(x[2]) <= 400)
for key, csv_data in csvs_data.items():
    extra_data = {}
    with tqdm(desc=f'downloading {key}', total=len(csv_data), unit='proteins') as pbar:
        for i in range(len(csv_data)):
            protein_id = csv_data[i, 1]
            simple_fasta = csv_data[i, 2]
            if len(simple_fasta) > 400:
                pbar.update(1)
                continue
            species = csv_data[i, 3]
            Tm = csv_data[i, 4]
            while True:
                result = requests.post(url, data=simple_fasta, headers=headers)
                result = result.text
                # 可能会返回'INTERNAL SERVER ERROR'
                if result[:6] == 'HEADER':
                    break
                elif result == 'INTERNAL SERVER ERROR':
                    print(f'{protein_id}, INTERNAL SERVER ERROR')
                time.sleep(1)
            cut_idx = result.find('ATOM      1')
            assert cut_idx == 1501
            result = result[cut_idx:]
            structure = {'atom_name': [],
                         'residue_name': [],
                         'chain_id': [],
                         'residue_idx': [],
                         'x': [],
                         'y': [],
                         'z': [],
                         'occupancy': [],
                         'temperature_factor': [],
                         'chemical_symbol': []}
            for j, line in enumerate(result.split('\n')):
                parts = line.split(' ')
                parts = list(filter(lambda x: x != '', parts))
                assert parts[0] == 'ATOM'
                assert int(parts[1]) == j + 1
                structure['atom_name'].append(parts[2])
                structure['residue_name'].append(parts[3])
                structure['chain_id'].append(parts[4])
                structure['residue_idx'].append(int(parts[5]))
                structure['x'].append(float(parts[6]))
                structure['y'].append(float(parts[7]))
                structure['z'].append(float(parts[8]))
                structure['occupancy'].append(float(parts[9]))
                structure['temperature_factor'].append(float(parts[10]))
                structure['chemical_symbol'].append(parts[11])
            extra_data[protein_id] = {'simple_fasta': simple_fasta,
                                      'species': species,
                                      'Tm': Tm,
                                      'structure': structure}
            pbar.update(1)
    with open(f'{key}.json', 'w') as json_file:
        json.dump(extra_data, json_file)
