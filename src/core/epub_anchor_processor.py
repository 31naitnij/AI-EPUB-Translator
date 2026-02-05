import os
import re
import zipfile
import shutil
import tempfile
from bs4 import BeautifulSoup

class EPubAnchorProcessor:
    """
    针对 EPUB 的锚点文本提取提取与还原处理器。
    采用“提取 - 原地修改 - 重新打包”的极简策略，确保极致的结构保留。
    """
    
    def __init__(self, max_group_chars=2000):
        self.max_group_chars = max_group_chars
        self.temp_dir = None
        self.format_counter = 0
        
        # 稀有 Unicode 符号标记
        self.GS = "⟬" # Group Start
        self.GE = "⟭" # Group End
        self.AS = "⦗" # Anchor Start
        self.AE = "⦘" # Anchor End
        
        # 块级分隔符池 (绝对稀有字符)
        self.BLOCK_DELIMS = "⧖⧗⧘⧙⧚⧛⧜⧝⧞⧟⨀⨁⨂⨃⨄⨅⨆⨇⨈⨉⨊⨋⨌⨍⨎⨏⨐⨑⨒⨓⨔⨕⨖⨗⨘⨙⨚⨛⨜⨝⨞⨟"

    def get_block_delimiters(self, index):
        char = self.BLOCK_DELIMS[index % len(self.BLOCK_DELIMS)]
        return char, char

    def extract_epub(self, epub_path, callback=None):
        """将 EPUB 完整解压到临时目录"""
        if callback: callback("正在解压 EPUB 文件...")
        self.temp_dir = tempfile.mkdtemp(prefix="epub_trans_")
        with zipfile.ZipFile(epub_path, 'r') as zip_ref:
            zip_ref.extractall(self.temp_dir)
        return self.temp_dir

    def get_xhtml_files(self):
        """遍历并返回需要翻译的 XHTML/HTML 文件路径，简单跳过结构性技术文件"""
        xhtml_files = []
        # 简单过滤：仅通过文件名跳过明确的结构性文件
        skip_patterns = ['titlepage', 'title_page', 'cover', 'nav', 'toc', 'container.xml']
        
        for root, dirs, files in os.walk(self.temp_dir):
            for file in files:
                lower_name = file.lower()
                if lower_name.endswith(('.xhtml', '.html', '.htm')):
                    if any(p in lower_name for p in skip_patterns):
                        continue
                    xhtml_files.append(os.path.join(root, file))
        return xhtml_files

    def extract_block_with_local_ids(self, element):
        """
        核心逻辑：提取块内容，将所有 HTML 标签转化为带编号的锚点。
        使用 ⟦内容⟧⦗ID⦘ 表示容器镜像，使用 ⦗ID⦘ 表示独立锚点。
        """
        format_tags = []
        local_counter = [1]
        
        monolithic_tags = ['math', 'svg', 'canvas', 'video', 'audio']
        
        # 内部标签使用的括号（如果不想用 ⟦⟧ 可以换成其他稀有字符，但目前 ⟦⟧ 已是稀有字符）
        # 如果用户坚持连 ⟦⟧ 也不要，我们可以换成 ⦑ ⦒ (Mathematical Left/Right White Angle Brackets)
        TS = "⟦" 
        TE = "⟧"

        def recursive_extract(node, is_root=False):
            if isinstance(node, str):
                return node.replace('<', '&lt;').replace('>', '&gt;')
            
            if hasattr(node, 'name'):
                if node.name in monolithic_tags:
                    tag_id = f"{self.AS}{local_counter[0]}{self.AE}"
                    local_counter[0] += 1
                    format_tags.append({
                        'id': tag_id,
                        'tag': node.name,
                        'attrs': dict(node.attrs),
                        'raw_html': str(node),
                        'type': 'monolithic'
                    })
                    return tag_id
                
                # 递归处理子节点
                child_parts = []
                for child in node.children:
                    child_parts.append(recursive_extract(child))
                inner_content = "".join(child_parts)
                
                if is_root:
                    return inner_content
                
                tag_id = f"{self.AS}{local_counter[0]}{self.AE}"
                local_counter[0] += 1
                
                tag_info = {
                    'id': tag_id,
                    'tag': node.name,
                    'attrs': dict(node.attrs),
                    'type': 'container'
                }
                format_tags.append(tag_info)
                
                if inner_content:
                    return f"{TS}{inner_content}{TE}{tag_id}"
                else:
                    return tag_id

            return ""

        full_text = recursive_extract(element, is_root=True)
        return full_text, format_tags

    def create_blocks_from_soup(self, soup):
        """从 BeautifulSoup 对象中识别翻译块"""
        blocks = []
        # 极大扩展可翻译标签
        translatable_tags = [
            'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 
            'li', 'td', 'th', 'caption', 'figcaption', 
            'blockquote', 'dt', 'dd', 'cite', 'footer', 'aside',
            'div', 'section', 'article' # 只有其直接包含文本时才处理
        ]
        
        # 寻找所有可能的元素
        all_elements = soup.find_all(translatable_tags)
        
        for element in all_elements:
            # 策略：如果一个元素包含其他也在 translatable_tags 里的子元素，
            # 只有当它本身有“直接”的非空白文本时，才处理它。
            has_translatable_child = any(child.name in translatable_tags for child in element.find_all(translatable_tags, recursive=False))
            
            if has_translatable_child:
                # 检查是否有直接文本
                direct_text = "".join([t for t in element.find_all(string=True, recursive=False) if t.strip()])
                if not direct_text:
                    continue
            
            # 不再跳过 text_content 为空的块 (如 <p>&nbsp;</p>)，以保持对齐
            text, formats = self.extract_block_with_local_ids(element)
            blocks.append({
                'element': element,
                'text': text,
                'formats': formats,
                'size': len(text)
            })
        return blocks

    def format_for_ai(self, group_blocks):
        """将一组块格式化为 AI 提示格式，使用序列稀有字符"""
        lines = [self.GS]
        for i, block in enumerate(group_blocks):
            ds, de = self.get_block_delimiters(i)
            lines.append(f"{ds}{block['text']}{de}")
        lines.append(self.GE)
        return "\n".join(lines)
    def validate_and_parse_response(self, response_text, original_group):
        """
        校验 AI 响应的结构并解析。根据序列分隔符提取。
        同时校验内部锚点 (⦗n⦘) 的对齐和 ⟦⟧ 符号的闭合。
        """
        pattern = re.escape(self.GS) + r'([\s\S]*)' + re.escape(self.GE)
        group_match = re.search(pattern, response_text)
        if not group_match:
            return None, False
        
        content = group_match.group(1).strip()
        translated_texts = []
        
        # 内部标签括号
        TS, TE = "⟦", "⟧"
        
        # 按顺序寻找分隔符
        for i in range(len(original_group)):
            ds, de = self.get_block_delimiters(i)
            # 构造正则匹配此块
            block_pattern = re.escape(ds) + r'(.*?)' + re.escape(de)
            match = re.search(block_pattern, content, re.DOTALL)
            if match:
                block_text = match.group(1).strip()
                translated_texts.append(block_text)
                
                # --- 增加：内部锚点一致性校验 ---
                orig_block = original_group[i]
                # 提取原始块中的所有锚点 ID
                orig_anchors = set(re.findall(re.escape(self.AS) + r'(\d+)' + re.escape(self.AE), orig_block['text']))
                # 提取翻译块中的所有锚点 ID
                trans_anchors = set(re.findall(re.escape(self.AS) + r'(\d+)' + re.escape(self.AE), block_text))
                
                # 如果锚点 ID 不完全一致（多了或少了），则判定失败
                if orig_anchors != trans_anchors:
                    return None, False
                
                # 校验 ⟦ ⟧ 符号的数量是否一致（基本闭合检查）
                if block_text.count(TS) != block_text.count(TE):
                    return None, False
            else:
                return None, False
        
        if len(translated_texts) != len(original_group):
            return None, False
                
        return translated_texts, True


    def restore_html(self, original_block, translated_text, soup):
        """将翻译后的带锚点文本还原为 HTML 元素"""
        format_map = {int(re.search(r'(\d+)', f['id']).group(1)): f for f in original_block['formats']}
        TS, TE = "⟦", "⟧"
        
        def parse_to_nodes(text):
            nodes = []
            i = 0
            while i < len(text):
                if text[i] == TS:
                    # 找到对应的 TE 和后的锚点
                    start_idx = i
                    level = 1
                    j = i + 1
                    while j < len(text) and level > 0:
                        if text[j] == TS: level += 1
                        elif text[j] == TE: level -= 1
                        j += 1
                    
                    if level == 0:
                        inner_text = text[start_idx+1:j-1]
                        # 检查后面是否有 ⦗n⦘
                        anchor_tail = text[j:]
                        match = re.match(re.escape(self.AS) + r'(\d+)' + re.escape(self.AE), anchor_tail)
                        if match:
                            anchor_num = int(match.group(1))
                            if anchor_num in format_map:
                                fmt = format_map[anchor_num]
                                new_tag = soup.new_tag(fmt['tag'])
                                for k, v in fmt['attrs'].items():
                                    new_tag[k] = v
                                for child in parse_to_nodes(inner_text):
                                    new_tag.append(child)
                                nodes.append(new_tag)
                                i = j + match.end()
                                continue
                
                match_solo = re.match(re.escape(self.AS) + r'(\d+)' + re.escape(self.AE), text[i:])
                if match_solo:
                    anchor_num = int(match_solo.group(1))
                    if anchor_num in format_map:
                        fmt = format_map[anchor_num]
                        if fmt.get('type') == 'monolithic':
                            new_node = BeautifulSoup(fmt['raw_html'], 'html.parser').contents[0]
                            import copy
                            nodes.append(copy.copy(new_node))
                        else:
                            # 独立容器（如空标签或 br）
                            new_tag = soup.new_tag(fmt['tag'])
                            for k, v in fmt['attrs'].items():
                                new_tag[k] = v
                            nodes.append(new_tag)
                        i += match_solo.end()
                        continue
                
                nodes.append(soup.new_string(text[i]))
                i += 1
            return nodes

        # 优化：合并连续的字符串节点
        def finalize_nodes(nodes):
            if not nodes: return []
            result = []
            curr_str = ""
            for n in nodes:
                if isinstance(n, str) or (hasattr(n, 'name') and n.name is None):
                    curr_str += str(n)
                else:
                    if curr_str:
                        result.append(soup.new_string(curr_str))
                        curr_str = ""
                    result.append(n)
            if curr_str:
                result.append(soup.new_string(curr_str))
            return result

        new_nodes = finalize_nodes(parse_to_nodes(translated_text))
        original_block['element'].clear()
        for node in new_nodes:
            original_block['element'].append(node)

    def repack_epub(self, output_path):
        """原封不动打包临时目录，并优化兼容性（mimetype不压缩，强制正斜杠）"""
        if not self.temp_dir or not os.path.exists(self.temp_dir):
            raise ValueError("没有可打包的临时目录")
            
        with zipfile.ZipFile(output_path, 'w') as zipf:
            # 1. 必须先写入 mimetype 且不压缩 (EPUB 标准)
            mimetype_path = os.path.join(self.temp_dir, 'mimetype')
            if os.path.exists(mimetype_path):
                # 显式指定 arcname 为 "mimetype"，确保没有路径前缀
                zipf.write(mimetype_path, 'mimetype', compress_type=zipfile.ZIP_STORED)
            
            # 2. 写入其余文件
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if file == 'mimetype' and root == self.temp_dir:
                        continue
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, self.temp_dir)
                    
                    # 关键修复：强制使用正斜杠 (/)，即使在 Windows 上
                    # 这是 EPUB/ZIP 标准所要求的，否则在某些阅读器上会找不到文件（如封面）
                    zip_path = rel_path.replace(os.sep, '/')
                    
                    zipf.write(full_path, zip_path, compress_type=zipfile.ZIP_DEFLATED)
                    
    def cleanup(self):
        """清理临时目录"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
