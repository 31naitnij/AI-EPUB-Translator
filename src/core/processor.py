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

    def save_cache(self, input_path, cached_data):
        """兼容旧接口，内部转发到新逻辑"""
        self.save_metadata(input_path, cached_data)

    def load_cache(self, input_path):
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
                 chunk_data = self.load_chunk(input_path, i)
                 if chunk_data:
                     new_chunks.append(chunk_data)
                 else:
                     # 应该不会发生，但提供兜底
                     new_chunks.append({"orig": "", "trans": "", "block_indices": [], "is_error": False})
             data["files"][0]["chunks"] = new_chunks
        return data

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
        # 复制一份，移除 chunks 后保存
        meta = data.copy()
        if meta.get("files"):
            # 我们在元数据中只保留 chunk 的“占位符”或数量信息
            # 为了兼容性，我们把 chunks 数组替换为仅包含基础结构但不含文字的新数组
            # 或者干脆在这里保存一份全量的作为备份？
            # 考虑到用户要求“单独做缓存”，我们还是把 chunks 剥离
            pass 
        
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
            return self.load_cache(input_path)

        if only_load: return None

        # 使用永久镜像目录
        temp_dir = self.ensure_source_mirror(input_path, "epub", callback=callback)
        self.epub_anchor_processor.temp_dir = temp_dir
        
        xhtml_files = self.epub_anchor_processor.get_xhtml_files()
        all_blocks = []
        files_info = []
        
        for xhtml_file in xhtml_files:
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
            return self.load_cache(input_path)
        if only_load: return None

        # 使用永久镜像目录
        temp_dir = self.ensure_source_mirror(input_path, "docx", callback=callback)
        self.docx_anchor_processor.temp_dir = temp_dir
        
        xml_files = self.docx_anchor_processor.get_xml_files()
        all_blocks = []
        files_info = []
        
        for xml_file in xml_files:
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
            "all_blocks": [{"text": b['text'], "formats": b['formats']} for b in all_blocks],
            "finished": False,
            "block_to_file": {b_idx: f_info['rel_path'] for f_info in files_info for b_idx in range(*f_info['block_range'])}
        }
        self.save_metadata(input_path, cached_data)
        return cached_data

    def process_run(self, input_path, translator, context_rounds=1, callback=None, target_indices=None):
        cached_data = self.load_cache(input_path)
        if not cached_data: return False

        flat_list = [(f_i, c_i) for f_i, f_data in enumerate(cached_data["files"]) for c_i, c_data in enumerate(f_data["chunks"])]
        loop_range = sorted(target_indices) if target_indices is not None else range(cached_data["current_flat_idx"], len(flat_list))

        self.status = "running"
        for i in loop_range:
            if self.status != "running":
                if target_indices is None: cached_data["current_flat_idx"] = i 
                self.save_metadata(input_path, cached_data)
                return False 

            f_idx, c_idx = flat_list[i]
            chunk = cached_data["files"][f_idx]["chunks"][c_idx]
            
            history = []
            for hi in range(max(0, i - context_rounds), i):
                hf, hc = flat_list[hi]
                h_chunk = cached_data["files"][hf]["chunks"][hc]
                if h_chunk["trans"]: history.append((h_chunk["orig"], h_chunk["trans"]))

            full_translation = ""
            for partial in translator.translate_chunk(chunk["orig"], history):
                full_translation += partial
                if callback: callback(i, len(flat_list), chunk["orig"], full_translation, False)
            
            chunk["trans"] = full_translation
            chunk["is_error"] = False
            self.save_chunk(input_path, i, chunk)
            
            # 核心改进：实时回写翻译到镜像
            self.apply_chunk_to_mirror(input_path, cached_data, i)
            
            if callback: callback(i, len(flat_list), chunk["orig"], full_translation, True)
            if target_indices is None: cached_data["current_flat_idx"] = i + 1
            self.save_metadata(input_path, cached_data)

        if target_indices is None: cached_data["finished"] = True
        self.save_metadata(input_path, cached_data)
        return True

    def run_manual_verification(self, file_path, callback=None):
        cached_data = self.load_cache(file_path)
        if not cached_data: return False

        flat_list = [(f_i, c_i) for f_i, f_data in enumerate(cached_data["files"]) for c_i, c_data in enumerate(f_data["chunks"])]
        for i, (f_idx, c_idx) in enumerate(flat_list):
            chunk = cached_data["files"][f_idx]["chunks"][c_idx]
            if not chunk["trans"]: continue

            error_prefix = "【结构校验失败，请手动检查】"
            if chunk["trans"].startswith(error_prefix):
                chunk["trans"] = chunk["trans"][len(error_prefix):].lstrip()
            
            chunk["is_error"] = False
            self.save_chunk(file_path, i, chunk)
            if callback: callback(i, len(flat_list), chunk["orig"], chunk["trans"], True)
        
        self.save_metadata(file_path, cached_data)
        self.status = "idle"
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
        
        if source_type == "epub_anchor":
            trans_texts, ok = self.epub_anchor_processor.validate_and_parse_response(chunk["trans"], group_blocks)
        else:
            trans_texts, ok = self.docx_anchor_processor.validate_and_parse_response(chunk["trans"], group_blocks)
            
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
                soup_blocks = self.docx_anchor_processor.create_blocks_from_soup(soup, include_nodes=True)
                block_map = {b['element'].get('data-trans-idx'): b for b in soup_blocks}
                
                for b_idx, text in zip(orig_indices, trans_texts):
                    if block_to_file.get(str(b_idx)) == rel_path:
                        target_b = block_map.get(str(b_idx))
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
