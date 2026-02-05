import json
import os
import sys
from src.core.processor import Processor
from src.core.epub_anchor_processor import EPubAnchorProcessor

def diagnose():
    cache_dir = "cache"
    # 查找最近修改的 cache json
    json_files = [f for f in os.listdir(cache_dir) if f.endswith(".json")]
    if not json_files:
        print("No cache files found.")
        return
    
    latest_file = max([os.path.join(cache_dir, f) for f in json_files], key=os.path.getmtime)
    print(f"Diagnosing latest cache file: {latest_file}")
    
    with open(latest_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    chunks = data['files'][0]['chunks']
    translated = [i for i, c in enumerate(chunks) if c['trans'].strip()]
    print(f"Found {len(translated)} translated chunks out of {len(chunks)}")
    
    if not translated:
        print("CRITICAL: No translations found in cache file!")
        return

    # 检查其中一个翻译好的块是否能通过 validate
    p = EPubAnchorProcessor()
    idx = translated[0]
    chunk = chunks[idx]
    full_trans = chunk['trans']
    g_indices = chunk['block_indices']
    
    print(f"\nChecking chunk {idx}:")
    print(f"Original text length: {len(chunk['orig'])}")
    print(f"Translation length: {len(full_trans)}")
    
    # 模拟我们的新 prefix removal 逻辑
    error_prefix = "【结构校验失败，请手动检查】"
    if full_trans.startswith(error_prefix):
        print("Found error prefix, stripping...")
        full_trans = full_trans[len(error_prefix):].lstrip()
    
    group_blocks = [{"text": data["all_blocks"][i]["text"], "formats": data["all_blocks"][i]["formats"]} for i in g_indices]
    
    texts, ok = p.validate_and_parse_response(full_trans, group_blocks)
    print(f"Validation result: {ok}")
    if not ok:
        print("Validation FAILED!")
        # 探测失败原因
        GS = "⟬"
        GE = "⟭"
        import re
        pattern = re.escape(GS) + r'([\s\S]*)' + re.escape(GE)
        match = re.search(pattern, full_trans)
        if not match:
            print(f"Pattern match FAILED! Header/Footer symbols missing? GS='{GS}', GE='{GE}'")
            print("Response start:", full_trans[:50])
            print("Response end:", full_trans[-50:])
        else:
            content = match.group(1).strip()
            print(f"Pattern matched. Content length: {len(content)}")
            # 检查分隔符
            for i in range(len(group_blocks)):
                ds, de = p.get_block_delimiters(i)
                block_pattern = re.escape(ds) + r'(.*?)' + re.escape(de)
                m = re.search(block_pattern, content)
                if not m:
                    print(f"Block delimiter {i} ({ds}) NOT found!")
                    break

if __name__ == "__main__":
    diagnose()
