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
        
        # 内容标签符号 (与 DOCX 保持一致)
        self.TS = "⟦" # Tag Start
        self.TE = "⟧" # Tag End
        
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
        
        xhtml_files.sort() # 强制排序，防止非确定性遍历导致块索引错位
        return xhtml_files

    def extract_block_with_local_ids(self, element):
        """
        核心逻辑：提取块内容，将所有 HTML 标签转化为带编号的锚点。
        使用成对稀有字符 ⧖content⧖ 格式，字符本身即为唯一 ID。
        """
        format_tags = []
        local_counter = [0]  # 从 0 开始，用于索引 BLOCK_DELIMS
        
        monolithic_tags = ['math', 'svg', 'canvas', 'video', 'audio']

        def get_delimiter(idx):
            """获取第 idx 个分隔符"""
            return self.BLOCK_DELIMS[idx % len(self.BLOCK_DELIMS)]

        def recursive_extract(node, is_root=False):
            if isinstance(node, str):
                return node.replace('<', '&lt;').replace('>', '&gt;')
            
            if hasattr(node, 'name'):
                if node.name in monolithic_tags:
                    delim = get_delimiter(local_counter[0])
                    local_counter[0] += 1
                    format_tags.append({
                        'id': delim,
                        'tag': node.name,
                        'attrs': dict(node.attrs),
                        'raw_html': str(node),
                        'type': 'monolithic'
                    })
                    # 无内容的整体标签，只用分隔符标记位置
                    return delim
                
                # 递归处理子节点
                child_parts = []
                for child in node.children:
                    child_parts.append(recursive_extract(child))
                inner_content = "".join(child_parts)
                
                if is_root:
                    return inner_content
                
                delim = get_delimiter(local_counter[0])
                local_counter[0] += 1
                
                tag_info = {
                    'id': delim,
                    'tag': node.name,
                    'attrs': dict(node.attrs),
                    'type': 'container'
                }
                format_tags.append(tag_info)
                
                if inner_content:
                    # 成对分隔符包裹内容
                    return f"{delim}{inner_content}{delim}"
                else:
                    return delim

            return ""

        full_text = recursive_extract(element, is_root=True)
        return full_text, format_tags

    def create_blocks_from_soup(self, soup, start_global_idx=0):
        """
        从 BeautifulSoup 对象中识别翻译块。
        添加强制打标逻辑：给每个块添加 data-trans-idx 属性。
        """
        blocks = []
        semantic_tags = {
            'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 
            'li', 'caption', 'figcaption', 'dt', 'dd', 'cite', 'footer', 'aside'
        }
        container_tags = {
            'div', 'section', 'article', 'body', 'table', 'tr', 'td', 'th', 
            'blockquote', 'thead', 'tbody', 'tfoot', 'dl', 'ol', 'ul'
        }
        
        COHESIVE_THRESHOLD = 800

        def get_text_size(node):
            if isinstance(node, str):
                return len(node.strip())
            return len(node.get_text().strip())

        def tag_and_add_block(node):
            size = get_text_size(node)
            if size > 0:
                # 核心改进：ID-Aware 发现逻辑
                # 如果这个节点已经有了全局编号，直接沿用
                if node.has_attr('data-trans-idx'):
                    idx = int(node['data-trans-idx'])
                else:
                    # 只有在没有编号时，才按顺序分配新编号
                    idx = start_global_idx + len(blocks)
                    node['data-trans-idx'] = str(idx)
                
                text, formats = self.extract_block_with_local_ids(node)
                blocks.append({
                    'element': node,
                    'text': text,
                    'formats': formats,
                    'size': size,
                    'global_idx': idx
                })

        def process_node(node):
            if not node or isinstance(node, str):
                return
            
            # 1. 如果是语义标签
            if node.name in semantic_tags:
                tag_and_add_block(node)
                return

            # 2. 如果是容器标签
            if node.name in container_tags:
                total_size = get_text_size(node)
                if total_size == 0:
                    return

                has_child_structures = any(
                    child.name in semantic_tags or child.name in container_tags
                    for child in node.find_all(True, recursive=False)
                )

                if total_size < COHESIVE_THRESHOLD or not has_child_structures:
                    tag_and_add_block(node)
                else:
                    for child in node.children:
                        if isinstance(child, str):
                            if child.strip():
                                # 纯文本或混合内容：在 EPUB 中通常建议包裹在容器中
                                pass
                        else:
                            process_node(child)
            else:
                if get_text_size(node) > 0:
                    tag_and_add_block(node)

        body = soup.find('body')
        if body:
            for child in body.children:
                process_node(child)
        else:
            process_node(soup)
            
        return blocks

    def format_for_ai(self, group_blocks):
        """将一组块格式化为 AI 提示格式，使用序列稀有字符"""
        lines = [self.GS]
        for i, block in enumerate(group_blocks):
            ds, de = self.get_block_delimiters(i)
            lines.append(f"{ds}{block['text']}{de}")
        lines.append(self.GE)
        return "\n".join(lines)

    def repair_translated_text(self, text):
        """
        修复翻译文本中的成对分隔符格式问题。
        检测每个分隔符，确保成对出现。
        """
        # 新格式使用成对分隔符，修复逻辑：检查每个 BLOCK_DELIMS 字符是否成对
        for delim in self.BLOCK_DELIMS:
            count = text.count(delim)
            if count % 2 == 1:
                # 奇数个，说明缺少一个，在末尾补一个
                text = text + delim
        return text

    def check_anchor_format(self, text):
        """
        检测成对分隔符格式完整性。
        检查项：每个分隔符字符必须成对出现（偶数个）。
        """
        for delim in self.BLOCK_DELIMS:
            count = text.count(delim)
            if count % 2 != 0:
                return False
        return True

    def validate_and_parse_response(self, response_text, original_group, auto_repair=False):
        """
        [移除结构校验] 宽容解析。
        auto_repair: 是否自动修复格式错误。
        """
        if auto_repair:
            response_text = self.repair_translated_text(response_text)
        
        pattern = re.escape(self.GS) + r'([\s\S]*)' + re.escape(self.GE)
        group_match = re.search(pattern, response_text)
        if group_match:
            content = group_match.group(1).strip()
        else:
            content = response_text.strip()
            
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
            else:
                translated_texts.append(original_group[i]['text'])
        
        return translated_texts, True

    def restore_html(self, original_block, translated_text, soup):
        """
        将翻译后的带锚点文本还原为 HTML 元素。
        采用原处修改策略，锁定 original_block['element']。
        """
        element = original_block['element']
        format_map = {int(re.search(r'(\d+)', f['id']).group(1)): f for f in original_block['formats']}
        TS, TE = "⟦", "⟧"
        
        def parse_to_nodes(text):
            nodes = []
            i = 0
            while i < len(text):
                if text[i] == TS:
                    start_idx = i
                    level = 1
                    j = i + 1
                    while j < len(text) and level > 0:
                        if text[j] == TS: level += 1
                        elif text[j] == TE: level -= 1
                        j += 1
                    
                    if level == 0:
                        inner_text = text[start_idx+1:j-1]
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
                            new_tag = soup.new_tag(fmt['tag'])
                            for k, v in fmt['attrs'].items():
                                new_tag[k] = v
                            nodes.append(new_tag)
                        i += match_solo.end()
                        continue
                
                nodes.append(soup.new_string(text[i]))
                i += 1
            return nodes

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
        element.clear()
        for node in new_nodes:
            element.append(node)

    def repack_epub(self, output_path):
        """原封不动打包临时目录，并优化兼容性（mimetype不压缩，强制正斜杠）"""
        if not self.temp_dir or not os.path.exists(self.temp_dir):
            raise ValueError("没有可打包的临时目录")
            
        with zipfile.ZipFile(output_path, 'w') as zipf:
            mimetype_path = os.path.join(self.temp_dir, 'mimetype')
            if os.path.exists(mimetype_path):
                zipf.write(mimetype_path, 'mimetype', compress_type=zipfile.ZIP_STORED)
            
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if file == 'mimetype' and root == self.temp_dir:
                        continue
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, self.temp_dir)
                    zip_path = rel_path.replace("\\", "/")
                    zipf.write(full_path, zip_path, compress_type=zipfile.ZIP_DEFLATED)
                    
    def cleanup(self):
        """清理临时目录"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
