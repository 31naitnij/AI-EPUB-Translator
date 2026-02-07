import os
import re
import zipfile
import shutil
import tempfile
from bs4 import BeautifulSoup

class DocxAnchorProcessor:
    """
    针对 DOCX 的锚点文本提取与还原处理器。
    采用“提取 - 原地修改 - 重新打包”的策略，确保格式完美保留。
    """
    
    def __init__(self, max_group_chars=2000):
        self.max_group_chars = max_group_chars
        self.temp_dir = None
        
        # 组内块级分隔符池 (Sequence A: U+2A40 - U+2AA3)
        self.BLOCK_DELIMS = "".join(chr(0x2A40 + i) for i in range(100))
        # 块内标签分隔符池 (Sequence B: U+2B40 - U+2BA3)
        self.INNER_DELIMS = "".join(chr(0x2B40 + i) for i in range(100))

    def get_block_delimiters(self, index):
        """获取组内第 index 个块的分隔符 (Sequence A)"""
        char = self.BLOCK_DELIMS[index % len(self.BLOCK_DELIMS)]
        return char, char

    def get_inner_delimiters(self, index):
        """获取块内第 index 个标签的分隔符 (Sequence B)"""
        char = self.INNER_DELIMS[index % len(self.INNER_DELIMS)]
        return char, char

    def extract_docx(self, docx_path, callback=None):
        """将 DOCX 完整解压到临时目录"""
        if callback: callback("正在解压 DOCX 文件...")
        self.temp_dir = tempfile.mkdtemp(prefix="docx_trans_")
        with zipfile.ZipFile(docx_path, 'r') as zip_ref:
            zip_ref.extractall(self.temp_dir)
        return self.temp_dir

    def get_xml_files(self):
        """返回 DOCX 中主要的 XML 内容文件"""
        content_files = []
        # 主文档
        main_doc = os.path.join(self.temp_dir, 'word', 'document.xml')
        if os.path.exists(main_doc):
            content_files.append(main_doc)
        
        # 页眉页脚、脚注、尾注
        word_dir = os.path.join(self.temp_dir, 'word')
        if os.path.exists(word_dir):
            for f in os.listdir(word_dir):
                if f.startswith(('header', 'footer', 'footnotes', 'endnotes', 'comments')) and f.endswith('.xml'):
                    content_files.append(os.path.join(word_dir, f))
        
        # 强制排序，文档主体 document.xml 通常在最前，但其余部分需保持一致
        content_files.sort() 
        return content_files

    def extract_block_with_local_ids(self, element, include_nodes=False):
        """
        核心逻辑：提取 DOCX 段落内容，将每个 <w:r> 转化为唯一的块内序列分隔符 (Sequence B)。
        """
        format_tags = []
        local_counter = [0]

        def recursive_extract(node):
            if node.name == 't' or (hasattr(node, 'name') and node.name.endswith(':t')):
                return node.get_text().replace('<', '&lt;').replace('>', '&gt;')
            
            if node.name == 'r' or (hasattr(node, 'name') and node.name.endswith(':r')):
                delim = self.get_inner_delimiters(local_counter[0])[0]
                local_counter[0] += 1
                
                tag_info = {
                    'id': delim,
                    'tag': 'r',
                    'type': 'run'
                }
                if include_nodes:
                    tag_info['node'] = node
                format_tags.append(tag_info)

                # 提取 run 内部的所有文本节点
                inner_texts = []
                for child in node.find_all(['t', 'w:t'], recursive=False):
                    inner_texts.append(child.get_text().replace('<', '&lt;').replace('>', '&gt;'))
                
                content = "".join(inner_texts)
                if content:
                    return f"{delim}{content}{delim}"
                else:
                    return delim
                
            # 处理其他子节点 (如 w:p 中的特殊标签如 w:br, w:tab)
            child_parts = []
            if hasattr(node, 'children'):
                for child in node.children:
                    if hasattr(child, 'name') and child.name:
                        child_parts.append(recursive_extract(child))
            return "".join(child_parts)

        full_text = recursive_extract(element)
        return full_text, format_tags

    def create_blocks_from_soup(self, soup, include_nodes=False, start_global_idx=0):
        """
        从 DOCX XML 中提取翻译块 (主要是 w:p)。
        添加强制打标逻辑：给每个块添加 data-trans-idx 属性。
        """
        blocks = []
        # 同时查找带命名空间和不带命名空间的 p
        paragraphs = soup.find_all(['p', 'w:p'])
        
        for p in paragraphs:
            text, formats = self.extract_block_with_local_ids(p, include_nodes=include_nodes)
            
            # 净化：去除锚点和空白后如果为空，则跳过
            clean_text = re.sub(r'[\u2A40-\u2AA3\u2B40-\u2BA3\s]', '', text)
            if not clean_text:
                continue
            
            # 核心改进：ID-Aware 发现逻辑
            if p.has_attr('data-trans-idx'):
                idx = int(p['data-trans-idx'])
            else:
                idx = start_global_idx + len(blocks)
                p['data-trans-idx'] = str(idx)
                
            blocks.append({
                'element': p,
                'text': text,
                'formats': formats,
                'size': len(clean_text),
                'global_idx': idx
            })
        return blocks

    def format_for_ai(self, group_blocks):
        """将一组块格式化为 AI 提示格式"""
        lines = []
        for i, block in enumerate(group_blocks):
            ds, de = self.get_block_delimiters(i)
            # 每行一个块，便于 AI 识别
            lines.append(f"{ds}{block['text']}{de}")
        return "\n".join(lines)

    def repair_translated_text(self, text):
        """
        修复翻译文本中的成对分隔符格式问题。
        检测每个分隔符 (Sequence A & B)，确保成对出现。
        """
        all_delims = self.BLOCK_DELIMS + self.INNER_DELIMS
        for delim in all_delims:
            count = text.count(delim)
            if count % 2 == 1:
                # 奇数个，说明缺少一个，在末尾补一个
                text = text + delim
        return text

    def check_anchor_format(self, text):
        """检测成对分隔符格式完整性"""
        all_delims = self.BLOCK_DELIMS + self.INNER_DELIMS
        for delim in all_delims:
            if text.count(delim) % 2 != 0:
                return False
        return True

    def validate_and_parse_response(self, response_text, original_group, auto_repair=False):
        """
        [扁平解析] 解析 AI 返回的多个块。
        """
        if auto_repair:
            response_text = self.repair_translated_text(response_text)
        
        content = response_text.strip()
            
        translated_texts = []
        last_pos = 0
        
        for i in range(len(original_group)):
            ds, de = self.get_block_delimiters(i)
            # 注意：这里的正则围绕 Sequence A 字符包裹的内容
            block_pattern = re.escape(ds) + r'(.*?)' + re.escape(de)
            match = re.search(block_pattern, content[last_pos:], re.DOTALL)
            
            if match:
                block_content = match.group(1).strip()
                translated_texts.append(block_content)
                last_pos += match.end()
            else:
                # 容错：如果找不到该块，保留原文
                translated_texts.append(original_group[i]['text'])
        
        return translated_texts, True

    def restore_xml(self, original_block, translated_text, soup):
        """
        [手术式还原] 直接修改 original_block['element'] 内部已有的 run 节点。
        """
        node_map = {f['id']: f['node'] for f in original_block['formats']}
        
        # 识别所有 INNER_DELIMS 中的字符
        delims_chars = "".join(self.INNER_DELIMS)
        
        # 解析翻译后的文本，寻找配对的 Sequence B 分隔符
        i = 0
        while i < len(translated_text):
            char = translated_text[i]
            if char in delims_chars and char in node_map:
                # 寻找匹配的闭合符号
                start_idx = i + 1
                balance = 1
                j = i + 1
                while j < len(translated_text) and balance > 0:
                    if translated_text[j] == char:
                        balance -= 1
                    j += 1
                
                if balance == 0:
                    # 找到匹配，提取内部文本并更新节点
                    inner_text = translated_text[start_idx : j-1]
                    run_node = node_map[char]
                    t_node = run_node.find(['t', 'w:t'])
                    if t_node:
                        t_node.string = inner_text
                    else:
                        new_t = soup.new_tag('w:t')
                        new_t['xml:space'] = 'preserve'
                        new_t.string = inner_text
                        run_node.append(new_t)
                    i = j
                else:
                    i += 1
            else:
                i += 1

    def repack_docx(self, output_path):
        """重新打包目录为 DOCX"""
        if not self.temp_dir or not os.path.exists(self.temp_dir):
            raise ValueError("没有可打包的临时目录")
            
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, self.temp_dir)
                    # ZIP 规范要求使用正斜杠，在 Windows 上需转换
                    zipf.write(full_path, rel_path.replace("\\", "/"))
                    
    def cleanup(self):
        """清理临时目录"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
