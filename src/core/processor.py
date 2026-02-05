import os
import json
import shutil
from src.core.epub_anchor_processor import EPubAnchorProcessor
from src.core.docx_anchor_processor import DocxAnchorProcessor
from bs4 import BeautifulSoup

class Processor:
    def __init__(self, cache_dir):
        self.cache_dir = cache_dir
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        self.status = "idle" # idle, running, stopped
        self.epub_anchor_processor = EPubAnchorProcessor()
        self.docx_anchor_processor = DocxAnchorProcessor()

    def save_cache(self, filename, data):
        path = os.path.join(self.cache_dir, filename)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def load_cache(self, filename):
        path = os.path.join(self.cache_dir, filename)
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None

    def get_cache_filename(self, input_filename):
        base = os.path.basename(input_filename)
        return f"{base}_cache.json"

    def get_working_dir(self, input_filename):
        base = os.path.basename(input_filename)
        return os.path.join(self.cache_dir, f"{base}_extracted")

    def process_epub_anchor_init(self, input_path, max_chars, only_load=False, callback=None):
        """
        基于锚点标记的 EPUB 初始化。
        """
        cache_file = self.get_cache_filename(input_path)
        cached_data = self.load_cache(cache_file)
        
        if cached_data and cached_data.get("source_type") == "epub_anchor":
            return cached_data

        if only_load:
            return None

        # 1. 解压 EPUB
        temp_dir = self.epub_anchor_processor.extract_epub(input_path, callback=callback)
        
        # 2. 遍历 XHTML 文件并提取块
        if callback: callback("正在遍历 XHTML 文件并提取文本块...")
        xhtml_files = self.epub_anchor_processor.get_xhtml_files()
        all_blocks = []
        files_info = []
        
        for xhtml_file in xhtml_files:
            rel_path = os.path.relpath(xhtml_file, temp_dir)
            with open(xhtml_file, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f, 'html.parser')
            
            file_blocks = self.epub_anchor_processor.create_blocks_from_soup(soup)
            if not file_blocks:
                continue
                
            # 记录文件中的块索引范围
            start_idx = len(all_blocks)
            all_blocks.extend(file_blocks)
            end_idx = len(all_blocks)
            
            files_info.append({
                "rel_path": rel_path,
                "block_range": [start_idx, end_idx],
                "finished": False
            })

        # 3. 分组
        if callback: callback("正在进行逻辑分组与分块...")
        groups = []
        current_group = []
        current_size = 0
        for i, block in enumerate(all_blocks):
            if current_size + block['size'] > max_chars and current_group:
                groups.append(current_group)
                current_group = []
                current_size = 0
            current_group.append(i)
            current_size += block['size']
        if current_group:
            groups.append(current_group)

        # 4. 构造持久化结构
        # 为方便 process_run 统一处理，我们模拟 chunk 结构
        # 每个 group 对应一个 chunk
        chunks = []
        for g_indices in groups:
            group_blocks = [all_blocks[idx] for idx in g_indices]
            original_text = self.epub_anchor_processor.format_for_ai(group_blocks)
            chunks.append({
                "orig": original_text,
                "trans": "",
                "block_indices": g_indices,
                "is_error": False
            })

        cached_data = {
            "source_type": "epub_anchor",
            "working_dir": temp_dir,
            "input_path": input_path,
            "input_ext": ".epub",
            "current_flat_idx": 0,
            "files": [
                {
                    "rel_path": "all_groups", # 统一管理
                    "chunks": chunks,
                    "finished": False
                }
            ],
            "all_blocks": [ # 需要保存 blocks 的元数据用于还原
                {
                    "text": b['text'],
                    "formats": b['formats'],
                    # 提示：BeautifulSoup 元素无法直接序列化，我们在还原时会基于 position 重新解析
                } for b in all_blocks
            ],
            "finished": False
        }
        
        # 记录每个 block 所属的文件路径，方便还原
        block_to_file = {}
        for f_info in files_info:
            for b_idx in range(f_info['block_range'][0], f_info['block_range'][1]):
                block_to_file[b_idx] = f_info['rel_path']
        cached_data["block_to_file"] = block_to_file
        
        self.save_cache(cache_file, cached_data)
        return cached_data

    def process_docx_anchor_init(self, input_path, max_chars, only_load=False, callback=None):
        """
        基于锚点标记的 DOCX 初始化。
        """
        cache_file = self.get_cache_filename(input_path)
        cached_data = self.load_cache(cache_file)
        
        if cached_data and cached_data.get("source_type") == "docx_anchor":
            return cached_data

        if only_load:
            return None

        # 1. 解压 DOCX
        temp_dir = self.docx_anchor_processor.extract_docx(input_path, callback=callback)
        
        # 2. 遍历 XML 文件并提取块
        if callback: callback("正在遍历 XML 文件并提取文本块...")
        xml_files = self.docx_anchor_processor.get_xml_files()
        all_blocks = []
        files_info = []
        
        for xml_file in xml_files:
            rel_path = os.path.relpath(xml_file, temp_dir)
            with open(xml_file, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f, 'xml') # 使用 xml 解析器
            
            file_blocks = self.docx_anchor_processor.create_blocks_from_soup(soup)
            if not file_blocks:
                continue
                
            start_idx = len(all_blocks)
            all_blocks.extend(file_blocks)
            end_idx = len(all_blocks)
            
            files_info.append({
                "rel_path": rel_path,
                "block_range": [start_idx, end_idx],
                "finished": False
            })

        # 3. 分组
        if callback: callback("正在进行逻辑分组与分块...")
        groups = []
        current_group = []
        current_size = 0
        for i, block in enumerate(all_blocks):
            if current_size + block['size'] > max_chars and current_group:
                groups.append(current_group)
                current_group = []
                current_size = 0
            current_group.append(i)
            current_size += block['size']
        if current_group:
            groups.append(current_group)

        # 4. 构造持久化结构
        chunks = []
        for g_indices in groups:
            group_blocks = [all_blocks[idx] for idx in g_indices]
            original_text = self.docx_anchor_processor.format_for_ai(group_blocks)
            chunks.append({
                "orig": original_text,
                "trans": "",
                "block_indices": g_indices,
                "is_error": False
            })

        cached_data = {
            "source_type": "docx_anchor",
            "working_dir": temp_dir,
            "input_path": input_path,
            "input_ext": ".docx",
            "current_flat_idx": 0,
            "files": [
                {
                    "rel_path": "all_groups",
                    "chunks": chunks,
                    "finished": False
                }
            ],
            "all_blocks": [
                {
                    "text": b['text'],
                    "formats": b['formats'],
                } for b in all_blocks
            ],
            "finished": False
        }
        
        block_to_file = {}
        for f_info in files_info:
            for b_idx in range(f_info['block_range'][0], f_info['block_range'][1]):
                block_to_file[b_idx] = f_info['rel_path']
        cached_data["block_to_file"] = block_to_file
        
        self.save_cache(cache_file, cached_data)
        return cached_data

    def process_run(self, input_path, translator, context_rounds=1, callback=None, target_indices=None):
        """
        翻译运行循环。
        """
        cache_file = self.get_cache_filename(input_path)
        cached_data = self.load_cache(cache_file)
        
        if not cached_data:
            return False

        # Build flat list
        flat_list = []
        for f_i, f_data in enumerate(cached_data["files"]):
            for c_i, c_data in enumerate(f_data["chunks"]):
                flat_list.append((f_i, c_i))

        # Determine loop range
        if target_indices is not None:
            loop_range = sorted(target_indices)
        else:
            start_idx = cached_data["current_flat_idx"]
            loop_range = range(start_idx, len(flat_list))

        self.status = "running"
        
        # Main Loop
        for i in loop_range:
            if self.status != "running":
                if target_indices is None:
                    cached_data["current_flat_idx"] = i 
                self.save_cache(cache_file, cached_data)
                return False 

            f_idx, c_idx = flat_list[i]
            file_data = cached_data["files"][f_idx]
            chunk = file_data["chunks"][c_idx]
            
            # Context builder
            history = []
            hist_start = max(0, i - context_rounds)
            for hi in range(hist_start, i):
                hf, hc = flat_list[hi]
                h_chunk = cached_data["files"][hf]["chunks"][hc]
                if h_chunk["trans"]:
                    history.append((h_chunk["orig"], h_chunk["trans"]))

            # Translate with streaming
            full_translation = ""
            for partial in translator.translate_chunk(chunk["orig"], history):
                full_translation += partial
                if callback:
                    callback(i, len(flat_list), chunk["orig"], full_translation, False)
            
            # 校（锚点模式）
            g_indices = chunk.get("block_indices", [])
            group_blocks = [{"text": cached_data["all_blocks"][idx]["text"], "formats": cached_data["all_blocks"][idx]["formats"]} for idx in g_indices]
            
            # 根据 source_type 选择校验器
            if cached_data.get("source_type") == "docx_anchor":
                _, ok = self.docx_anchor_processor.validate_and_parse_response(full_translation, group_blocks)
            else:
                _, ok = self.epub_anchor_processor.validate_and_parse_response(full_translation, group_blocks)
                
            if not ok:
                if not full_translation.startswith("【结构校验失败，请手动检查】"):
                    full_translation = f"【结构校验失败，请手动检查】\n{full_translation}"
                chunk["is_error"] = True
            else:
                chunk["is_error"] = False

            chunk["trans"] = full_translation
            
            if callback:
                callback(i, len(flat_list), chunk["orig"], full_translation, True)
            
            if target_indices is None:
                cached_data["current_flat_idx"] = i + 1
            self.save_cache(cache_file, cached_data)

        if target_indices is None:
            cached_data["finished"] = True
            self.save_cache(cache_file, cached_data)
        
        self.status = "idle"
        return True

    def finalize_translation(self, input_path, output_path, target_format=None):
        ext = os.path.splitext(input_path)[1].lower()
        if ext == ".docx":
            return self.finalize_docx_anchor_translation(input_path, output_path)
        else:
            return self.finalize_epub_anchor_translation(input_path, output_path)

    def finalize_epub_anchor_translation(self, input_path, output_path):
        """
        基于锚点的 EPUB 完成逻辑：还原 HTML 并原封不动解压。
        """
        cache_file = self.get_cache_filename(input_path)
        cache_data = self.load_cache(cache_file)
        if not cache_data:
            raise RuntimeError("No cache found for finalization.")
            
        temp_dir = cache_data.get("working_dir")
        if not temp_dir or not os.path.exists(temp_dir):
            # 如果临时目录丢失（例如被清理了），需要重新解压（虽然这种可能性较小）
            temp_dir = self.epub_anchor_processor.extract_epub(input_path)
        
        self.epub_anchor_processor.temp_dir = temp_dir
        
        # 1. 整理所有翻译后的块
        all_translated_blocks = {} # index -> text
        for chunk in cache_data["files"][0]["chunks"]: # epub_anchor 只有一个文件 all_groups
            g_indices = chunk.get("block_indices", [])
            full_trans = chunk.get("trans", "")
            if chunk.get("is_error"):
                # 移除错误标记前缀
                full_trans = full_trans.replace("【结构校验失败，请手动检查】\n", "")
            
            group_blocks = [{"text": cache_data["all_blocks"][idx]["text"], "formats": cache_data["all_blocks"][idx]["formats"]} for idx in g_indices]
            translated_texts, ok = self.epub_anchor_processor.validate_and_parse_response(full_trans, group_blocks)
            
            if ok:
                for idx, text in zip(g_indices, translated_texts):
                    all_translated_blocks[idx] = text
            else:
                # 如果校验仍失败，尝试简单回退或按原样
                pass

        # 2. 按文件处理还原
        block_to_file = cache_data.get("block_to_file", {})
        file_to_blocks = {}
        for b_idx, rel_path in block_to_file.items():
            b_idx_int = int(b_idx)
            if rel_path not in file_to_blocks:
                file_to_blocks[rel_path] = []
            file_to_blocks[rel_path].append(b_idx_int)
            
        for rel_path, b_indices in file_to_blocks.items():
            abs_path = os.path.join(temp_dir, rel_path)
            with open(abs_path, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f, 'html.parser')
            
            # 重新定位 soup 中的 blocks
            soup_blocks = self.epub_anchor_processor.create_blocks_from_soup(soup)
            
            # 安全检查：如果当前文件解析出的块数量与缓存记录的不一致，
            # 说明提取逻辑发生了变化或文件被错误索引，必须跳过以防内容串位（错位到封面等）
            if len(soup_blocks) != len(b_indices):
                print(f"WARNING: Block count mismatch in {rel_path}. Cache: {len(b_indices)}, File: {len(soup_blocks)}. Skipping file to prevent corruption.")
                continue

            # 匹配并还原
            for i, b_idx in enumerate(b_indices):
                if b_idx in all_translated_blocks:
                    # print(f"DEBUG: Restoring block {b_idx} (local {i})")
                    self.epub_anchor_processor.restore_html(soup_blocks[i], all_translated_blocks[b_idx], soup)
            
            # 保存修改后的 XHTML
            with open(abs_path, 'w', encoding='utf-8') as f:
                f.write(str(soup))

        # 3. 重新打包
        self.epub_anchor_processor.repack_epub(output_path)
        return f"Successfully exported to EPUB via Anchor Strategy: {output_path}"

    def finalize_docx_anchor_translation(self, input_path, output_path):
        """
        基于锚点的 DOCX 完成逻辑。
        """
        cache_file = self.get_cache_filename(input_path)
        cache_data = self.load_cache(cache_file)
        if not cache_data:
            raise RuntimeError("No cache found for finalization.")
            
        temp_dir = cache_data.get("working_dir")
        if not temp_dir or not os.path.exists(temp_dir):
            temp_dir = self.docx_anchor_processor.extract_docx(input_path)
        
        # 1. 整理所有翻译后的块
        all_translated_blocks = {}
        for chunk in cache_data["files"][0]["chunks"]:
            g_indices = chunk.get("block_indices", [])
            full_trans = chunk.get("trans", "")
            if chunk.get("is_error"):
                full_trans = full_trans.replace("【结构校验失败，请手动检查】\n", "")
            
            group_blocks = [{"text": cache_data["all_blocks"][idx]["text"], "formats": cache_data["all_blocks"][idx]["formats"]} for idx in g_indices]
            translated_texts, ok = self.docx_anchor_processor.validate_and_parse_response(full_trans, group_blocks)
            
            if ok:
                for idx, text in zip(g_indices, translated_texts):
                    all_translated_blocks[idx] = text

        # 2. 按文件处理还原
        block_to_file = cache_data.get("block_to_file", {})
        file_to_blocks = {}
        for b_idx, rel_path in block_to_file.items():
            b_idx_int = int(b_idx)
            if rel_path not in file_to_blocks:
                file_to_blocks[rel_path] = []
            file_to_blocks[rel_path].append(b_idx_int)
            
        for rel_path, b_indices in file_to_blocks.items():
            abs_path = os.path.join(temp_dir, rel_path)
            with open(abs_path, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f, 'xml')
            
            soup_blocks = self.docx_anchor_processor.create_blocks_from_soup(soup)
            
            if len(soup_blocks) != len(b_indices):
                print(f"WARNING: Block count mismatch in {rel_path}. Cache: {len(b_indices)}, File: {len(soup_blocks)}.")
                continue

            for i, b_idx in enumerate(b_indices):
                if b_idx in all_translated_blocks:
                    self.docx_anchor_processor.restore_xml(soup_blocks[i], all_translated_blocks[b_idx], soup)
            
            # 保存修改后的 XML
            with open(abs_path, 'w', encoding='utf-8') as f:
                f.write(str(soup))

        # 3. 重新打包
        self.docx_anchor_processor.repack_docx(output_path)
        return f"Successfully exported to DOCX via Anchor Strategy: {output_path}"
