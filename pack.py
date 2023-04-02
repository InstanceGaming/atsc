#!/usr/bin/env python3
import os
import glob
import zipfile


# A completely standalone, drop-in script to automate
# recursively zipping up the current directory into a
# ZIP archive while skipping files matching shell-
# style wildcard filenames in each directory.

OUTPUT_FILENAME = 'atsc.zip'
BLACKLIST_PATTERNS = ['**/.idea/**', '**/.idea/**/.*', '**/env/**/.*', '**/notes/**', '**/env/**', '**/__pycache__/**',
                      '.git/**', '*.zip']

BLACKLIST_PATTERNS_DEV = ['**/env/**/.*', '**/env/**', '**/__pycache__/**', '.git/**', 'screend/frames/*.jpg',
                          'screend/frames/*.jpeg', 'screend/frames/*.png', '*.zip']

BASE_DIR = '.'


def run():
    active_blacklist = BLACKLIST_PATTERNS
    blacklisted_paths = []
    
    for pattern in active_blacklist:
        entry_names = glob.glob(pattern, recursive=True)
        
        for matched_name in entry_names:
            # print(f'pattern "{pattern}" matched on "{matched_name}"')
            
            if matched_name not in blacklisted_paths:
                blacklisted_paths.append(os.path.join(BASE_DIR, matched_name))
    
    print(f'{len(blacklisted_paths)} blacklisted files from {len(active_blacklist)} patterns')
    
    all_paths = set()
    
    for current_dir, dirs, files in os.walk(BASE_DIR):
        for file in files:
            all_paths.add(os.path.join(current_dir, file))
    
    print(f'{len(all_paths)} total files')
    
    whitelisted_paths = all_paths - set(blacklisted_paths)
    
    print(f'{len(whitelisted_paths)} whitelisted files')
    
    archive_file = zipfile.ZipFile(OUTPUT_FILENAME, mode='w', compression=zipfile.ZIP_DEFLATED)
    for whitelisted in whitelisted_paths:
        print(f'adding "{whitelisted}"')
        archive_file.write(whitelisted)
    
    print(f'created archive "{OUTPUT_FILENAME}"')


if __name__ == '__main__':
    run()
