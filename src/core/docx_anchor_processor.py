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
        
        # 稀有 Unicode 符号标记 (与 EPUB 保持一致)
        self.GS = "⟬" # Group Start
        self.GE = "⟭" # Group End
        self.AS = "⦗" # Anchor Start
        self.AE = "⦘" # Anchor End
        
        # 内部标签使用的括号
        self.TS = "⟦" 
        self.TE = "⟧"
        
        # 块级分隔符池
        self.BLOCK_DELIMS = "⧖⧗⧘⧙⧚⧛⧜⧝⧞⧟⨀⨁⨂⨃⨄⨅⨆⨇⨈⨉⨊⨋⨌⨍⨎⨏⨐⨑⨒⨓⨔⨕⨖⨗⨘⨙⨚⨛⨜⨝⨞⨟"

    def get_block_delimiters(self, index):
        char = self.BLOCK_DELIMS[index % len(self.BLOCK_DELIMS)]
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
        
        return content_files

    def extract_block_with_local_ids(self, element):
        """
        核心逻辑：提取 DOCX 段落内容，将格式运行 <w:r> 转化为带编号的锚点。
        """
        format_tags = []
        local_counter = [1]

        def recursive_extract(node):
            if node.name == 't': # w:t 标签
                return node.get_text().replace('<', '&lt;').replace('>', '&gt;')
            
            if node.name == 'r': # w:r 标签 (Run)
                # 检查是否有 w:t
                t_node = node.find('t', recursive=False)
                # 检查是否有其他特殊标签 (如 w:br, w:tab, w:drawing)
                special_nodes = node.find_all(lambda tag: tag.name in ('br', 'tab', 'drawing', 'pict'), recursive=False)
                
                # 获取格式属性 (w:rPr)
                rPr = node.find('rPr', recursive=False)
                attrs = str(rPr) if rPr else ""
                
                # 如果这个 run 包含文本
                if t_node:
                    inner_text = t_node.get_text().replace('<', '&lt;').replace('>', '&gt;')
                    if not attrs and not special_nodes:
                        # 无格式，直接返回文本
                        return inner_text
                    
                    tag_id = f"{self.AS}{local_counter[0]}{self.AE}"
                    local_counter[0] += 1
                    format_tags.append({
                        'id': tag_id,
                        'tag': 'r',
                        'raw_xml': str(node),
                        'type': 'container'
                    })
                    return f"{self.TS}{inner_text}{self.TE}{tag_id}"
                
                # 如果这个 run 只包含特殊节点
                elif special_nodes:
                    tag_id = f"{self.AS}{local_counter[0]}{self.AE}"
                    local_counter[0] += 1
                    format_tags.append({
                        'id': tag_id,
                        'tag': 'r',
                        'raw_xml': str(node),
                        'type': 'monolithic'
                    })
                    return tag_id
                
            # 处理其他子节点 (如 w:p 中的特殊标签)
            child_parts = []
            if hasattr(node, 'children'):
                for child in node.children:
                    if hasattr(child, 'name') and child.name:
                        child_parts.append(recursive_extract(child))
            return "".join(child_parts)

        full_text = recursive_extract(element)
        return full_text, format_tags

    def create_blocks_from_soup(self, soup):
        """从 DOCX XML 中提取翻译块 (主要是 w:p)"""
        blocks = []
        # DOCX 中的段落标签是 w:p
        # 注意：BeautifulSoup 在解析带命名的 XML 时可能需要处理命名空间
        # 但我们这里简单通过标签名查找
        paragraphs = soup.find_all(['p', 'w:p'])
        
        for p in paragraphs:
            # 简单过滤掉没有文本的段落
            text_content = p.get_text().strip()
            if not text_content:
                # 即使是空段落，我们也保留其结构，但不作为翻译块？
                # 按照 EPUB 的逻辑，我们保留它以保持对齐
                pass
            
            text, formats = self.extract_block_with_local_ids(p)
            if not text.strip():
                # 如果没有任何可翻译文字，跳过
                continue
                
            blocks.append({
                'element': p,
                'text': text,
                'formats': formats,
                'size': len(text)
            })
        return blocks

    def format_for_ai(self, group_blocks):
        """同 EPUB"""
        lines = [self.GS]
        for i, block in enumerate(group_blocks):
            ds, de = self.get_block_delimiters(i)
            lines.append(f"{ds}{block['text']}{de}")
        lines.append(self.GE)
        return "\n".join(lines)

    def validate_and_parse_response(self, response_text, original_group):
        """
        校验 AI 响应的结构并解析。根据序列分隔符提取。
        同时校验内部锚点 (⦗n⦘) 和 ⟦⟧ 符号。
        """
        pattern = re.escape(self.GS) + r'([\s\S]*)' + re.escape(self.GE)
        group_match = re.search(pattern, response_text)
        if not group_match:
            return None, False
        
        content = group_match.group(1).strip()
        translated_texts = []
        
        last_pos = 0
        for i in range(len(original_group)):
            ds, de = self.get_block_delimiters(i)
            block_pattern = re.escape(ds) + r'(.*?)' + re.escape(de)
            match = re.search(block_pattern, content[last_pos:], re.DOTALL)
            if match:
                block_text = match.group(1).strip()
                translated_texts.append(block_text)
                last_pos += match.end()
                
                # --- 增加：内部锚点一致性校验 ---
                orig_block = original_group[i]
                orig_anchors = set(re.findall(re.escape(self.AS) + r'(\d+)' + re.escape(self.AE), orig_block['text']))
                trans_anchors = set(re.findall(re.escape(self.AS) + r'(\d+)' + re.escape(self.AE), block_text))
                
                if orig_anchors != trans_anchors:
                    return None, False
                
                if block_text.count(self.TS) != block_text.count(self.TE):
                    return None, False
            else:
                return None, False
        
        if len(translated_texts) != len(original_group):
            return None, False
                
        return translated_texts, True

    def restore_xml(self, original_block, translated_text, soup):
        """将翻译后的锚点文本还原为 DOCX XML"""
        format_map = {int(re.search(r'(\d+)', f['id']).group(1)): f for f in original_block['formats']}
        
        def parse_to_nodes(text):
            nodes = []
            i = 0
            while i < len(text):
                if text[i] == self.TS:
                    start_idx = i
                    level = 1
                    j = i + 1
                    while j < len(text) and level > 0:
                        if text[j] == self.TS: level += 1
                        elif text[j] == self.TE: level -= 1
                        j += 1
                    
                    if level == 0:
                        inner_text = text[start_idx+1:j-1]
                        anchor_tail = text[j:]
                        match = re.match(re.escape(self.AS) + r'(\d+)' + re.escape(self.AE), anchor_tail)
                        if match:
                            anchor_num = int(match.group(1))
                            if anchor_num in format_map:
                                fmt = format_map[anchor_num]
                                # 还原 w:r
                                # 我们采取“克隆并更新文本”的策略
                                r_node = BeautifulSoup(fmt['raw_xml'], 'xml').find('r')
                                if r_node:
                                    t_node = r_node.find('t')
                                    if t_node:
                                        t_node.string = inner_text
                                    nodes.append(r_node)
                                    i = j + match.end()
                                    continue
                
                match_solo = re.match(re.escape(self.AS) + r'(\d+)' + re.escape(self.AE), text[i:])
                if match_solo:
                    anchor_num = int(match_solo.group(1))
                    if anchor_num in format_map:
                        fmt = format_map[anchor_num]
                        # 还原单体节点 (如 w:br 或带 drawing 的 w:r)
                        node = BeautifulSoup(fmt['raw_xml'], 'xml').contents[0]
                        import copy
                        nodes.append(copy.copy(node))
                        i += match_solo.end()
                        continue
                
                # 普通文本，需要包裹在 w:r/w:t 中
                # 为了保持简单，我们遇到连续文本时会创建一个新的 w:r
                curr_text = ""
                while i < len(text) and text[i] not in (self.TS, self.AS):
                    curr_text += text[i]
                    i += 1
                if curr_text:
                    new_r = soup.new_tag('w:r')
                    new_t = soup.new_tag('w:t')
                    new_t['xml:space'] = 'preserve'
                    new_t.string = curr_text
                    new_r.append(new_t)
                    nodes.append(new_r)
                continue
                
            return nodes

        new_nodes = parse_to_nodes(translated_text)
        
        # 保留 w:pPr (段落属性)
        pPr = original_block['element'].find(['pPr', 'w:pPr'], recursive=False)
        original_block['element'].clear()
        if pPr:
            original_block['element'].append(pPr)
            
        for node in new_nodes:
            original_block['element'].append(node)

    def repack_docx(self, output_path):
        """重新打包目录为 DOCX"""
        if not self.temp_dir or not os.path.exists(self.temp_dir):
            raise ValueError("没有可打包的临时目录")
            
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, self.temp_dir)
                    zipf.write(full_path, rel_path)
                    
    def cleanup(self):
        """清理临时目录"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
