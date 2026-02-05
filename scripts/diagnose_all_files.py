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
    for f_idx, f_entry in enumerate(files):
        chunks = f_entry.get('chunks', [])
        total_chunks += len(chunks)
        for c_idx, chunk in enumerate(chunks):
            if chunk.get('trans', '').strip():
                translated_chunks += 1
                if translated_chunks == 1:
                    print(f"First translation found in file {f_idx} ('{f_entry.get('rel_path')}'), chunk {c_idx}")
    
    print(f"Summary: {translated_chunks} / {total_chunks} chunks translated.")

if __name__ == "__main__":
    diagnose()
