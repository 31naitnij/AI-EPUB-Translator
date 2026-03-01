import os
import json
import shutil
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from src.core.epub_anchor_processor import EPubAnchorProcessor

class Processor:
    def __init__(self, cache_dir):
        self.cache_dir = cache_dir
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        self.status = "idle" # idle, running, stopped
        self.epub_anchor_processor = EPubAnchorProcessor()
        self.lock = threading.Lock()

    def save_cache(self, input_path, cached_data):
        """兼容旧接口，内部转发到新逻辑"""
        self.save_metadata(input_path, cached_data)

    def load_cache(self, input_path, callback=None):
        """兼容旧接口，内部转发到新逻辑并聚合数据"""
        data = self.load_metadata(input_path)
        if not data: return None
        
        # 聚合 chunks
        if data.get("files"):
             total_chunks = sum(len(f.get("chunks", [])) for f in data["files"])
             flat_idx = 0
             
             for f_idx, f_info in enumerate(data["files"]):
                 new_chunks = []
                 for c_idx in range(len(f_info.get("chunks", []))):
                     if callback and flat_idx % 5 == 0: 
                         callback(f"正在加载缓存分块: {flat_idx+1}/{total_chunks}")
                     
                     chunk_data = self.load_chunk(input_path, flat_idx)
                     if chunk_data:
                         new_chunks.append(chunk_data)
                     else:
                         new_chunks.append({"orig": "", "trans": "", "block_indices": [], "is_error": False})
                     
                     flat_idx += 1
                 f_info["chunks"] = new_chunks
        
        # 核心改进：加载后同步确保镜像文件被打上 ID 标签
        # 否则 apply_chunk_to_mirror 会因为找不到 ID 而跳过
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
            self.epub_anchor_processor.extract_epub(input_path, callback=callback)
            # 将临时目录移动到 source_dir
            shutil.move(self.epub_anchor_processor.temp_dir, source_dir)
            self.epub_anchor_processor.temp_dir = source_dir
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
        files_data = []
        block_to_file = {}
        
        flat_chunk_counter = 0

        for idx, xhtml_file in enumerate(xhtml_files):
            if callback: callback(f"正在解析文件: {idx+1}/{total_files} ({os.path.basename(xhtml_file)})")
            rel_path = os.path.relpath(xhtml_file, temp_dir)
            
            # 纯字符串读取，不使用任何解析库
            with open(xhtml_file, 'r', encoding='utf-8') as f:
                html_string = f.read()
            
            # 逐行提取含文本的行
            file_blocks = self.epub_anchor_processor.create_blocks_from_html(
                html_string, 
                start_global_idx=len(all_blocks)
            )
            
            if not file_blocks: continue

            # 按字符数分组
            file_chunks_blocks = []
            current_chunk = []
            current_size = 0
            
            for b in file_blocks:
                text_len = len(b['simplified'])
                current_chunk.append(b)
                current_size += text_len
                if current_size >= max_chars:
                    file_chunks_blocks.append(current_chunk)
                    current_chunk = []
                    current_size = 0
            if current_chunk:
                file_chunks_blocks.append(current_chunk)

            # 构建 chunk 元数据
            chunk_metadata_list = []
            for chunk_blocks in file_chunks_blocks:
                block_indices = []
                for b in chunk_blocks:
                    g_idx = b['global_idx']
                    block_indices.append(g_idx)
                    block_to_file[g_idx] = rel_path

                chunk_meta = {
                    "orig": self.epub_anchor_processor.format_for_ai(chunk_blocks),
                    "trans": "",
                    "block_indices": block_indices,
                    "is_error": False
                }
                chunk_metadata_list.append(chunk_meta)
                self.save_chunk(input_path, flat_chunk_counter, chunk_meta)
                flat_chunk_counter += 1

            files_data.append({
                "rel_path": rel_path,
                "chunks": chunk_metadata_list,
                "finished": False
            })
            all_blocks.extend(file_blocks)

        # 构建最终元数据
        cached_data = {
            "source_type": "epub_anchor",
            "working_dir": temp_dir,
            "input_path": input_path,
            "input_ext": ".epub",
            "current_flat_idx": 0,
            "files": files_data,
            "all_blocks": [{"text": b['simplified'], "formats": b['tag_mapping'], "line_idx": b['line_idx'], "indent": b['indent'], "trailing": b['trailing']} for b in all_blocks],
            "finished": False,
            "block_to_file": block_to_file
        }
        self.save_metadata(input_path, cached_data)
        return cached_data

        # [REMOVED process_docx_anchor_init]

    def check_chunk_format(self, input_path, text, expected_count, source_type=None):
        """
        根据源文件类型检查格式完整性。
        """
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
                time.sleep(interval)

            f_idx, c_idx = flat_list[i]
            
            # Read (Should be safe if list structure doesn't change)
            with self.lock:
                chunk = cached_data["files"][f_idx]["chunks"][c_idx]
            
            # Streaming support - REVERTED to non-streaming for stability as requested
            full_translation = translator.translate_chunk(
                chunk["orig"], 
                stream_callback=None # Disabled
            )
            
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
                elif error_type.startswith("unbalanced_internal_"):
                    # 容错：如果是内部锚点不平衡，虽然标记为 error 供 UI 显示，
                    # 但仍然允许 apply_chunk_to_mirror (它会回退到纯文本模式)
                    chunk["is_error"] = True
                    self.apply_chunk_to_mirror(input_path, cached_data, i)
                else:
                    chunk["is_error"] = True # Flag as error for UI
                    # 对于 Line Mismatch 或 Delimiter Mismatch，由于无法定位块，坚决不回写
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
        return self.finalize_epub_anchor_translation(input_path, output_path)

    def apply_chunk_to_mirror(self, input_path, cached_data, chunk_idx):
        """
        实时将翻译块回写到 source/ 镜像中。
        纯行级字符串替换，不使用任何解析库。
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
        
        block_to_file = cached_data.get("block_to_file", {})
        affected_files = set()
        for b_idx in chunk["block_indices"]:
            affected_files.add(block_to_file.get(str(b_idx)))
            
        source_dir = os.path.join(self.get_cache_dir_path(input_path), "source")
        
        orig_indices = chunk["block_indices"]
        group_blocks = [{"text": cached_data["all_blocks"][idx]["text"], "formats": cached_data["all_blocks"][idx]["formats"]} for idx in orig_indices]
        
        trans_texts, ok = self.epub_anchor_processor.validate_and_parse_response(chunk["trans"], group_blocks, auto_repair=False)
        
        for rel_path in affected_files:
            if not rel_path: continue
            abs_path = os.path.join(source_dir, rel_path)
            if not os.path.exists(abs_path): continue
            
            with open(abs_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # 逐块回填：直接按行号替换
            for b_idx, text in zip(orig_indices, trans_texts):
                if block_to_file.get(str(b_idx)) != rel_path:
                    continue
                block_meta = cached_data["all_blocks"][b_idx]
                line_idx = block_meta.get("line_idx")
                tag_mapping = block_meta.get("formats", {})
                indent = block_meta.get("indent", "")
                trailing = block_meta.get("trailing", "\n")
                
                if line_idx is not None and 0 <= line_idx < len(lines):
                    restored = self.epub_anchor_processor.restore_line(
                        text, tag_mapping, indent, trailing
                    )
                    lines[line_idx] = restored
            
            with open(abs_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)

    def finalize_epub_anchor_translation(self, input_path, output_path):
        """
        导出前进行最后一次全量同步，确保所有已翻译块都写入镜像。
        纯行级字符串替换，不使用任何解析库。
        """
        cached_data = self.load_cache(input_path)
        if not cached_data:
            raise ValueError("无法加载翻译缓存，请确保已开始翻译。")
        
        # 按文件聚合回写
        source_dir = os.path.join(self.get_cache_dir_path(input_path), "source")
        block_to_file = cached_data.get("block_to_file", {})
        
        file_to_chunks = {}
        flat_idx = 0
        for f_data in cached_data["files"]:
            for chunk in f_data["chunks"]:
                if chunk.get("trans"):
                    rel_path = block_to_file.get(str(chunk["block_indices"][0]))
                    if rel_path not in file_to_chunks: file_to_chunks[rel_path] = []
                    file_to_chunks[rel_path].append((flat_idx, chunk))
                flat_idx += 1
                
        for rel_path, chunks in file_to_chunks.items():
            abs_path = os.path.join(source_dir, rel_path)
            if not os.path.exists(abs_path): continue
            
            with open(abs_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            for f_idx, chunk in chunks:
                orig_indices = chunk["block_indices"]
                group_blocks = [{"text": cached_data["all_blocks"][idx]["text"], "formats": cached_data["all_blocks"][idx]["formats"]} for idx in orig_indices]
                trans_texts, _ = self.epub_anchor_processor.validate_and_parse_response(chunk["trans"], group_blocks)
                
                for b_idx, text in zip(orig_indices, trans_texts):
                    block_meta = cached_data["all_blocks"][b_idx]
                    line_idx = block_meta.get("line_idx")
                    tag_mapping = block_meta.get("formats", {})
                    indent = block_meta.get("indent", "")
                    trailing = block_meta.get("trailing", "\n")
                    
                    if line_idx is not None and 0 <= line_idx < len(lines):
                        restored = self.epub_anchor_processor.restore_line(
                            text, tag_mapping, indent, trailing
                        )
                        lines[line_idx] = restored
            
            with open(abs_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)

        # 打包
        self.epub_anchor_processor.temp_dir = source_dir
        self.epub_anchor_processor.repack_epub(output_path)
        return f"导出成功：{output_path}\n已同步 {len(file_to_chunks)} 个文件的翻译内容。"
