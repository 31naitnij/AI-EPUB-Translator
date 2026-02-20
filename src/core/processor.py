import os
import json
import shutil
import time
import threading
from concurrent.futures import ThreadPoolExecutor
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
        self.lock = threading.Lock()

    def save_cache(self, input_path, cached_data):
        """兼容旧接口，内部转发到新逻辑"""
        self.save_metadata(input_path, cached_data)

    def load_cache(self, input_path, callback=None):
        """兼容旧接口，内部转发到新逻辑并聚合数据"""
        data = self.load_metadata(input_path)
        if not data: return None
        
        # 聚合 chunks
        cache_dir = self.get_cache_dir_path(input_path)
        chunks_dir = os.path.join(cache_dir, "chunks")
        
        # 假设 files[0]["chunks"] 是唯一的管理点（目前架构如此）
        if data.get("files") and data["files"][0].get("chunks") is not None:
             total_chunks = len(data["files"][0]["chunks"])
             new_chunks = []
             for i in range(total_chunks):
                 if callback and i % 5 == 0: 
                     callback(f"正在加载缓存分块: {i+1}/{total_chunks}")
                 chunk_data = self.load_chunk(input_path, i)
                 if chunk_data:
                     new_chunks.append(chunk_data)
                 else:
                     new_chunks.append({"orig": "", "trans": "", "block_indices": [], "is_error": False})
             data["files"][0]["chunks"] = new_chunks
             
        # 缓存加载后，自动验证所有已翻译块的格式
        self.validate_all_chunks(input_path, data, callback=callback)
        return data
    
    def validate_all_chunks(self, input_path, cached_data, callback=None):
        """
        遍历所有已翻译的块，验证格式并更新 is_error 标志。
        """
        if not cached_data or not cached_data.get("files"):
            return
            
        for f_data in cached_data["files"]:
            chunks = f_data.get("chunks", [])
            total = len(chunks)
            for i, chunk in enumerate(chunks):
                if callback and i % 10 == 0:
                    callback(f"正在验证翻译格式: {i+1}/{total}")
                trans_text = chunk.get("trans", "")
                if not trans_text:
                    chunk["is_error"] = False
                    continue
                    
                # 实时检查格式
                error_type = self.check_chunk_format(input_path, trans_text, expected_count=len(chunk.get("block_indices", [])))
                chunk["is_error"] = (error_type != "ok")
                chunk["error_type"] = error_type

    def get_cache_dir_path(self, input_path):
        """获取书籍的缓存文件夹路径"""
        base = os.path.basename(input_path)
        return os.path.join(self.cache_dir, f"{base}_cache")

    def ensure_cache_dir(self, input_path):
        """确保缓存文件夹存在"""
        path = self.get_cache_dir_path(input_path)
        if not os.path.exists(path):
            os.makedirs(path)
        return path

    def get_legacy_cache_path(self, input_path):
        """获取旧版单文件缓存路径"""
        base = os.path.basename(input_path)
        return os.path.join(self.cache_dir, f"{base}_cache.json")

    def ensure_source_mirror(self, input_path, processor_type, callback=None):
        """
        确保书籍被解压到缓存目录下的 source/ 文件夹。
        如果已存在则跳过解压。
        """
        cache_dir = self.ensure_cache_dir(input_path)
        source_dir = os.path.join(cache_dir, "source")
        if not os.path.exists(source_dir):
            if callback: callback(f"正在建立永久源码镜像: {source_dir}")
            if processor_type == "epub":
                self.epub_anchor_processor.extract_epub(input_path, callback=callback)
                # 将临时目录移动到 source_dir
                shutil.move(self.epub_anchor_processor.temp_dir, source_dir)
                self.epub_anchor_processor.temp_dir = source_dir
            else:
                self.docx_anchor_processor.extract_docx(input_path, callback=callback)
                shutil.move(self.docx_anchor_processor.temp_dir, source_dir)
                self.docx_anchor_processor.temp_dir = source_dir
        return source_dir

    def save_metadata(self, input_path, data):
        """保存结构性元数据，排除大的 chunk 数据以免冗余"""
        cache_dir = self.ensure_cache_dir(input_path)
        
        # Deep copy logic for files to avoid modifying the in-memory data object
        # We only need to copy the structure we are about to modify (the files list)
        meta = data.copy()
        if meta.get("files"):
            # Create a new list for files to avoid modifying the original list in 'data'
            new_files_list = []
            for f_info in meta["files"]:
                # Create a copy of the file info dict
                new_f_info = f_info.copy()
                if "chunks" in new_f_info:
                    # Replace actual chunk list with empty dicts to preserve count
                    # This is CRITICAL for load_cache to know how many chunks to load
                    new_f_info["chunks"] = [{} for _ in new_f_info["chunks"]]
                new_files_list.append(new_f_info)
            meta["files"] = new_files_list
        
        path = os.path.join(cache_dir, "metadata.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=4)

    def load_metadata(self, input_path):
        base = os.path.basename(input_path)
        path = os.path.join(self.cache_dir, f"{base}_cache", "metadata.json")
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None

    def save_chunk(self, input_path, flat_idx, chunk_data):
        """原子化保存单个块"""
        cache_dir = self.ensure_cache_dir(input_path)
        chunks_dir = os.path.join(cache_dir, "chunks")
        if not os.path.exists(chunks_dir):
            os.makedirs(chunks_dir)
            
        path = os.path.join(chunks_dir, f"chunk_{flat_idx}.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(chunk_data, f, ensure_ascii=False, indent=4)

    def load_chunk(self, input_path, flat_idx):
        base = os.path.basename(input_path)
        path = os.path.join(self.cache_dir, f"{base}_cache", "chunks", f"chunk_{flat_idx}.json")
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None

    def get_cache_filename(self, input_filename):
        """保持兼容性，但实际不再使用单文件逻辑"""
        return self.get_cache_dir_path(input_filename)

    def process_epub_anchor_init(self, input_path, max_chars, only_load=False, callback=None):
        cached_data = self.load_metadata(input_path)
        if cached_data and cached_data.get("source_type") == "epub_anchor":
            return self.load_cache(input_path, callback=callback)

        if only_load: return None

        # 使用永久镜像目录
        temp_dir = self.ensure_source_mirror(input_path, "epub", callback=callback)
        self.epub_anchor_processor.temp_dir = temp_dir
        
        xhtml_files = self.epub_anchor_processor.get_xhtml_files()
        total_files = len(xhtml_files)
        all_blocks = []
        files_info = []
        
        for idx, xhtml_file in enumerate(xhtml_files):
            if callback: callback(f"正在解析文件: {idx+1}/{total_files} ({os.path.basename(xhtml_file)})")
            rel_path = os.path.relpath(xhtml_file, temp_dir)
            with open(xhtml_file, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f, 'html.parser')
            
            # 核心改进：打标并分配全局索引
            file_blocks = self.epub_anchor_processor.create_blocks_from_soup(soup, start_global_idx=len(all_blocks))
            if not file_blocks: continue
            
            # 保存带标签的源码到镜像
            with open(xhtml_file, 'wb') as f:
                f.write(soup.encode(formatter='html'))
                
            start_idx = len(all_blocks)
            all_blocks.extend(file_blocks)
            files_info.append({
                "rel_path": rel_path,
                "block_range": [start_idx, len(all_blocks)],
                "finished": False
            })

        groups = []
        for f_info in files_info:
            current_group = []
            current_size = 0
            start, end = f_info['block_range']
            
            for i in range(start, end):
                block = all_blocks[i]
                if current_size + block['size'] > max_chars and current_group:
                    groups.append(current_group)
                    current_group = []
                    current_size = 0
                current_group.append(i)
                current_size += block['size']
            
            # Ensure the last group of the file is added before moving to the next file
            if current_group:
                groups.append(current_group)

        chunks = []
        for i, g_indices in enumerate(groups):
            group_blocks = [all_blocks[idx] for idx in g_indices]
            chunk = {
                "orig": self.epub_anchor_processor.format_for_ai(group_blocks),
                "trans": "",
                "block_indices": g_indices,
                "is_error": False
            }
            chunks.append(chunk)
            self.save_chunk(input_path, i, chunk)

        cached_data = {
            "source_type": "epub_anchor",
            "working_dir": temp_dir,
            "input_path": input_path,
            "input_ext": ".epub",
            "current_flat_idx": 0,
            "files": [{"rel_path": "all_groups", "chunks": chunks, "finished": False}],
            "all_blocks": [{"text": b['text'], "formats": b['formats']} for b in all_blocks],
            "finished": False,
            "block_to_file": {b_idx: f_info['rel_path'] for f_info in files_info for b_idx in range(*f_info['block_range'])}
        }
        self.save_metadata(input_path, cached_data)
        return cached_data

    def process_docx_anchor_init(self, input_path, max_chars, only_load=False, callback=None):
        cached_data = self.load_metadata(input_path)
        if cached_data and cached_data.get("source_type") == "docx_anchor":
            return self.load_cache(input_path, callback=callback)
        if only_load: return None

        # 使用永久镜像目录
        temp_dir = self.ensure_source_mirror(input_path, "docx", callback=callback)
        self.docx_anchor_processor.temp_dir = temp_dir
        
        xml_files = self.docx_anchor_processor.get_xml_files()
        total_files = len(xml_files)
        all_blocks = []
        files_info = []
        
        for idx, xml_file in enumerate(xml_files):
            if callback: callback(f"正在解析文件: {idx+1}/{total_files} ({os.path.basename(xml_file)})")
            rel_path = os.path.relpath(xml_file, temp_dir)
            with open(xml_file, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f, 'xml')
            
            # 核心改进：打标并分配全局索引
            file_blocks = self.docx_anchor_processor.create_blocks_from_soup(soup, start_global_idx=len(all_blocks))
            if not file_blocks: continue
            
            # 保存带标签的源码到镜像
            with open(xml_file, 'wb') as f:
                f.write(soup.encode())
                
            start_idx = len(all_blocks)
            all_blocks.extend(file_blocks)
            files_info.append({
                "rel_path": rel_path,
                "block_range": [start_idx, len(all_blocks)],
                "finished": False
            })

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
        if current_group: groups.append(current_group)

        chunks = []
        for i, g_indices in enumerate(groups):
            group_blocks = [all_blocks[idx] for idx in g_indices]
            chunk = {
                "orig": self.docx_anchor_processor.format_for_ai(group_blocks),
                "trans": "",
                "block_indices": g_indices,
                "is_error": False
            }
            chunks.append(chunk)
            self.save_chunk(input_path, i, chunk)

        cached_data = {
            "source_type": "docx_anchor",
            "working_dir": temp_dir,
            "input_path": input_path,
            "input_ext": ".docx",
            "current_flat_idx": 0,
            "files": [{"rel_path": "all_groups", "chunks": chunks, "finished": False}],
            "all_blocks": [{"text": b['text'], "formats": b['formats'], "parent_idx": b.get('parent_idx'), "segment_idx": b.get('segment_idx')} for b in all_blocks],
            "finished": False,
            "block_to_file": {b_idx: f_info['rel_path'] for f_info in files_info for b_idx in range(*f_info['block_range'])}
        }
        self.save_metadata(input_path, cached_data)
        return cached_data

    def check_chunk_format(self, input_path, text, expected_count, source_type=None):
        """
        根据源文件类型检查格式完整性。
        """
        ext = os.path.splitext(input_path)[1].lower()
        if ext == ".docx":
            return self.docx_anchor_processor.check_anchor_format(text, expected_count)
        else:
            return self.epub_anchor_processor.check_anchor_format(text, expected_count)



    def process_run(self, input_path, translator, max_workers=1, interval=0, callback=None, target_indices=None):
        cached_data = self.load_cache(input_path)
        if not cached_data: return False

        flat_list = [(f_i, c_i) for f_i, f_data in enumerate(cached_data["files"]) for c_i, c_data in enumerate(f_data["chunks"])]
        loop_range = sorted(target_indices) if target_indices is not None else range(cached_data["current_flat_idx"], len(flat_list))

        self.status = "running"
        
        # Thread-safe Task Function
        def process_chunk_task(i):
            if self.status != "running": return
            
            # Rate limiting / Interval
            if interval > 0:
                time.sleep(interval / 1000.0)

            f_idx, c_idx = flat_list[i]
            
            # Read (Should be safe if list structure doesn't change)
            with self.lock:
                chunk = cached_data["files"][f_idx]["chunks"][c_idx]
            
            # Non-streaming call, no history
            # Append Stop Symbol handled in Translator
            full_translation = translator.translate_chunk(chunk["orig"])
            
            # Critical Section: Update and Save
            with self.lock:
                chunk["trans"] = full_translation
                
                # Validation
                expected_count = len(chunk["block_indices"])
                error_type = self.check_chunk_format(input_path, full_translation, expected_count=expected_count)
                chunk["error_type"] = error_type
                
                if error_type == "ok":
                    chunk["is_error"] = False 
                    # Only apply to mirror if valid!
                    self.apply_chunk_to_mirror(input_path, cached_data, i)
                else:
                    chunk["is_error"] = True # Flag as error for UI
                    # Do NOT apply to mirror
                
                # Save Chunk (Atomic file per chunk, safe)
                self.save_chunk(input_path, i, chunk)
                
                # Save Metadata (Locked)
                if target_indices is None: 
                    # Rough estimation of progress for resume capability
                    # In concurrent mode, this is just "latest start", might not be strictly sequential
                    if i >= cached_data["current_flat_idx"]:
                         cached_data["current_flat_idx"] = i + 1
                self.save_metadata(input_path, cached_data)

            if callback: callback(i, len(flat_list), chunk["orig"], full_translation, True, error_type)

        # Execution
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(process_chunk_task, i) for i in loop_range]
            # Wait for all to complete? Or just let them run? 
            # Ideally we wait so we know when 'finished' is true for the batch.
            for future in futures:
                if self.status != "running": break
                try:
                    future.result() # Wait and raise exceptions if any
                except Exception as e:
                    print(f"Task failed: {e}")

        # Finalize
        with self.lock:
            if target_indices is None and self.status == "running": 
                cached_data["finished"] = True
            self.save_metadata(input_path, cached_data)
        
        return True


    def finalize_translation(self, input_path, output_path, target_format=None):
        ext = os.path.splitext(input_path)[1].lower()
        if ext == ".docx":
            return self.finalize_docx_anchor_translation(input_path, output_path)
        else:
            return self.finalize_epub_anchor_translation(input_path, output_path)

    def apply_chunk_to_mirror(self, input_path, cached_data, chunk_idx):
        """
        实时将翻译块回写到 source/ 镜像中。
        """
        f_idx, c_idx = -1, -1
        flat_counter = 0
        for fi, f_data in enumerate(cached_data["files"]):
            for ci in range(len(f_data["chunks"])):
                if flat_counter == chunk_idx:
                    f_idx, c_idx = fi, ci
                    break
                flat_counter += 1
            if f_idx != -1: break
            
        if f_idx == -1: return
        chunk = cached_data["files"][f_idx]["chunks"][c_idx]
        if not chunk["trans"]: return
        
        # Double check validity before applying (even if called manually)
        if chunk.get("is_error", False):
            return # Skip invalid chunks
        
        # 确定受影响的文件
        block_to_file = cached_data.get("block_to_file", {})
        affected_files = set()
        for b_idx in chunk["block_indices"]:
            affected_files.add(block_to_file.get(str(b_idx)))
            
        source_type = cached_data.get("source_type")
        source_dir = os.path.join(self.get_cache_dir_path(input_path), "source")
        
        # 解析响应
        orig_indices = chunk["block_indices"]
        group_blocks = [{"text": cached_data["all_blocks"][idx]["text"], "formats": cached_data["all_blocks"][idx]["formats"]} for idx in orig_indices]
        
        # Passthrough auto_repair=False because we assume it's valid or already checked
        if source_type == "epub_anchor":
            trans_texts, ok = self.epub_anchor_processor.validate_and_parse_response(chunk["trans"], group_blocks, auto_repair=False)
        else:
            trans_texts, ok = self.docx_anchor_processor.validate_and_parse_response(chunk["trans"], group_blocks, auto_repair=False)
            
        if not ok: return
        
        # 逐个文件更新
        for rel_path in affected_files:
            if not rel_path: continue
            abs_path = os.path.join(source_dir, rel_path)
            
            if source_type == "epub_anchor":
                with open(abs_path, 'r', encoding='utf-8') as f:
                    soup = BeautifulSoup(f, 'html.parser')
                soup_blocks = self.epub_anchor_processor.create_blocks_from_soup(soup)
                
                # 建立 data-trans-idx 到 soup block 的映射
                block_map = {b['element'].get('data-trans-idx'): b for b in soup_blocks}
                
                for b_idx, text in zip(orig_indices, trans_texts):
                    if block_to_file.get(str(b_idx)) == rel_path:
                        target_b = block_map.get(str(b_idx))
                        if target_b:
                            self.epub_anchor_processor.restore_html(target_b, text, soup)
                
                with open(abs_path, 'wb') as f:
                    f.write(soup.encode(formatter='html'))
            else:
                with open(abs_path, 'r', encoding='utf-8') as f:
                    soup = BeautifulSoup(f, 'xml')
                # 此时 create_blocks_from_soup 会进行 normalize_paragraph_breaks
                soup_blocks = self.docx_anchor_processor.create_blocks_from_soup(soup, include_nodes=True)
                
                # 建立 parent_idx -> list of segments 映射
                block_map = {}
                for b in soup_blocks:
                    pid = b.get('parent_idx')
                    if pid not in block_map: block_map[pid] = []
                    block_map[pid].append(b)
                
                for b_idx, text in zip(orig_indices, trans_texts):
                    if block_to_file.get(str(b_idx)) == rel_path:
                        # 从 all_blocks 获取元数据
                        meta = cached_data["all_blocks"][b_idx]
                        pid = meta.get('parent_idx')
                        sid = meta.get('segment_idx')
                        
                        target_segments = block_map.get(pid, [])
                        # 查找匹配 segment_idx 的 block
                        target_b = next((tb for tb in target_segments if tb['segment_idx'] == sid), None)
                        
                        if target_b:
                            self.docx_anchor_processor.restore_xml(target_b, text, soup)
                
                with open(abs_path, 'wb') as f:
                    f.write(soup.encode())

    def finalize_epub_anchor_translation(self, input_path, output_path):
        # 极简模式：直接打包镜像，因为 apply_chunk_to_mirror 已经实时更新了它
        self.ensure_source_mirror(input_path, "epub") # 确保目录可用
        self.epub_anchor_processor.temp_dir = os.path.join(self.get_cache_dir_path(input_path), "source")
        self.epub_anchor_processor.repack_epub(output_path)
        return f"Successfully exported to EPUB via Live Synchronization: {output_path}"

    def finalize_docx_anchor_translation(self, input_path, output_path):
        self.ensure_source_mirror(input_path, "docx")
        self.docx_anchor_processor.temp_dir = os.path.join(self.get_cache_dir_path(input_path), "source")
        self.docx_anchor_processor.repack_docx(output_path)
        return f"Successfully exported to DOCX via Live Synchronization: {output_path}"
