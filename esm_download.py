import json
import os
import time
import glob
import pickle

import requests
from tqdm import tqdm
import numpy as np

from data_loading import read_csvs


def pickle_dump(obj, file_path):
    with open(file_path, "xb") as f:
        pickle.dump(obj, f)


def pickle_load(file_path):
    with open(file_path, "rb") as f:
        obj = pickle.load(f)
    return obj


def load_json(path):
    with open(path, 'r') as json_file:
        obj = json.load(json_file)
    return obj


def dump_json(obj, path, **kwargs):
    with open(path, 'w') as json_file:
        json.dump(obj, json_file, **kwargs)


def update_fetched_ids():
    fetched_ids = load_json('./StructuredDatasets/fetched_ids.json')
    files = glob.glob('./StructuredDatasets/*.json')
    for file in files:
        if 'fetched_ids.json' in file:
            continue
        json_content = load_json(file)
        for protein_id in json_content.keys():
            fetched_ids[protein_id] = 1116
    dump_json(fetched_ids, './StructuredDatasets/fetched_ids.json', indent=4)
    return set(fetched_ids.keys())


def merge_data():
    key_words = ('test2_dataset', 'train_dataset')
    for key_word in key_words:
        files = glob.glob(f'./StructuredDatasets/{key_word}*.json')
        if len(files) == 1 and files[0].endswith(f'{key_word}.json'):
            continue
        data = {}
        for file in files:
            data.update(load_json(file))
            os.remove(file)
        dump_json(data, f'./StructuredDatasets/{key_word}.json')


def main(species_filter=()):
    if isinstance(species_filter, str):
        species_filter = (species_filter,)
    url = 'https://api.esmatlas.com/foldSequence/v1/pdb'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36 Edg/111.0.1661.41',
        'Accept': 'application/json, text/plain, */*',
        'origin': 'https://esmatlas.com',
        'content-type': 'text/plain'}
    # 准备工作, 加载已爬取的protein_id
    csvs_data = read_csvs(data_filter=lambda x: len(x[2]) <= 400)
    csv_name, extra_data = None, {}
    print('updating fetched protein ids')
    fetched_ids = update_fetched_ids()
    print('finish')

    try:
        for csv_name, csv_data in csvs_data.items():
            extra_data = {}
            # 筛选物种
            csv_data = csv_data[np.isin(csv_data[:, 3], species_filter)]
            # 计算剩余条目的数量
            num_rest = len(set(csv_data[:, 1]) - fetched_ids)
            if num_rest == 0:
                continue
            # 爬数据
            with tqdm(desc=f'downloading {csv_name}', total=num_rest, unit='proteins') as pbar:
                for i in range(len(csv_data)):
                    # 原始数据
                    protein_id = csv_data[i, 1]
                    simple_fasta = csv_data[i, 2]
                    species = csv_data[i, 3]
                    Tm = csv_data[i, 4]
                    # 过长序列打咩!
                    if len(simple_fasta) > 400:
                        print('sequence too long')
                        continue
                    # 跳过已爬过的数据
                    if protein_id in fetched_ids:
                        continue
                    # 不断尝试爬取直至成功
                    pbar.set_postfix({'protein_id': protein_id, 'state': 'fetching...'})
                    wait = 1
                    num_try = 1
                    while True:
                        result = requests.post(url, data=simple_fasta, headers=headers)
                        result = result.text
                        # 成功爬取的报文以'HEADER'开头
                        if result[:6] == 'HEADER':
                            pbar.set_postfix({'protein_id': protein_id, 'state': 'success'})
                            time.sleep(1.0)
                            break
                        # 失败报文可能包含'INTERNAL SERVER ERROR', 'forbidden'
                        else:
                            pbar.set_postfix({'protein_id': protein_id, 'state': f'{result}: try{num_try}'})
                            wait = wait * 1.2 if wait * 1.2 <= 10 else wait
                            time.sleep(wait)
                            num_try += 1
                    # 定位到有效数据区
                    cut_idx = result.find('ATOM      1')
                    result = result[cut_idx:]
                    structure = {'atom_name': [], 'residue_name': [],
                                 'chain_id': [], 'residue_idx': [],
                                 'x': [], 'y': [], 'z': [], 'occupancy': [],
                                 'temperature_factor': [], 'chemical_symbol': []}
                    # 保存结构信息
                    for j, line in enumerate(result.split('\n')):
                        line = line.replace('-', ' -')  # 防止报文中出现'-100.3-98.3'这样的粘连数字
                        parts = list(filter(lambda x: x != '', line.split(' ')))
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
                    # 添加数据
                    extra_data[protein_id] = {'simple_fasta': simple_fasta, 'species': species,
                                              'Tm': Tm, 'structure': structure}
                    pbar.update(1)
            # 保存为json
            k = 1
            while True:
                if not os.path.exists(f'./StructuredDatasets/{csv_name}_{k}.json'):
                    dump_json(extra_data, f'./StructuredDatasets/{csv_name}_{k}.json')
                    break
                else:
                    k += 1
    except:
        # 程序意外终止时, 如KeyBoardInterrupt, 则保存已爬取的数据
        # 由于数据量大, json.dump耗时较久, 约十几秒, 切勿强行结束程序, 导致保存中断, 数据丢失
        if csv_name is not None and extra_data != {}:
            print('saving data, please do not kill process')
            k = 1
            while True:
                if not os.path.exists(f'./StructuredDatasets/{csv_name}_{k}.json'):
                    dump_json(extra_data, f'./StructuredDatasets/{csv_name}_{k}.json')
                    break
                else:
                    k += 1
            print('finish')
    finally:
        print('updating fetched protein ids')
        update_fetched_ids()
        print('finish')
        print('merging data, please do not kill process')
        merge_data()
        print('finish')


if __name__ == '__main__':
    """
    A.thaliana      B.subtilis      C.elegans               D.melanogaster
    D.rerio         E.coli          G.stearothermophilus    H.sapiens
    M.musculus      O.antarctica    P.torridus              S.cerevisiae
    T.thermophilus  thermophilus
    """
    main(species_filter=('M.musculus', 'O.antarctica', 'P.torridus'))
