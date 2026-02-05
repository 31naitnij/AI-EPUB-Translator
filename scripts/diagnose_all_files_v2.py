import json
import os

def diagnose():
    p = r'cache\Redeeming the Life of the Mind (John M. Frame, Wayne Grudem, John J. Hughes) (Z-Library).epub_cache.json'
    if not os.path.exists(p):
        print("File not found")
        return
    with open(p, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    files = data.get('files', [])
    print(f"Total files in cache: {len(files)}")
    
    total_chunks = 0
    translated_chunks = 0
    files_with_trans = []
    
    for f_idx, f_entry in enumerate(files):
        chunks = f_entry.get('chunks', [])
        file_total = len(chunks)
        file_trans = sum(1 for c in chunks if c.get('trans', '').strip())
        
        total_chunks += file_total
        translated_chunks += file_trans
        
        if file_trans > 0:
            files_with_trans.append((f_idx, file_trans, file_total, f_entry.get('rel_path')))
    
    print(f"Summary: {translated_chunks} / {total_chunks} chunks translated.")
    if files_with_trans:
        print("\nFiles containing translations:")
        for f_idx, f_trans, f_total, rel_path in files_with_trans:
            print(f"File {f_idx}: {f_trans}/{f_total} translated. Path: {rel_path}")
    else:
        print("\nNo translations found in ANY file entry.")

if __name__ == "__main__":
    diagnose()
