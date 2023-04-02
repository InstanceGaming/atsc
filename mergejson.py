import sys
import json
from argparse import ArgumentParser
from collections import ChainMap


def get_cla():
    ap = ArgumentParser(description='Merge two or more JSON files together.')
    ap.add_argument(dest='json_files', nargs='+', help='Two or more JSON file paths')
    return ap.parse_args()


def run():
    cla = get_cla()
    json_files = cla.json_files
    
    cm = ChainMap()
    for json_file in json_files:
        with open(json_file, 'r') as jf:
            data = json.load(jf)
            cm.update(data)
    
    json.dump(dict(cm), fp=sys.stdout, indent=True)


if __name__ == '__main__':
    run()
