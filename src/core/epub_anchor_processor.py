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

    def extract_epub(self, epub_path, callback=None):
        """将 EPUB 完整解压到临时目录"""
        if callback: callback(f"正在解压 EPUB: {epub_path}")
        self.temp_dir = tempfile.mkdtemp(prefix="epub_")
        with zipfile.ZipFile(epub_path, 'r') as zip_ref:
            zip_ref.extractall(self.temp_dir)
        return self.temp_dir

    def get_xhtml_files(self):
        """返回 EPUB 中主要的 XHTML/HTML 内容文件"""
        if not self.temp_dir:
            return []
        
        content_files = []
        for root, dirs, files in os.walk(self.temp_dir):
            for file in files:
                if file.lower().endswith(('.xhtml', '.html', '.htm')):
                    # 过滤掉一些明显的非内容文件 (如 nav.xhtml, toc.xhtml 等可选)
                    # if 'nav' in file.lower() or 'toc' in file.lower(): continue
                    content_files.append(os.path.join(root, file))
        return content_files

    def extract_block_with_local_ids(self, element):
        """
        核心逻辑：提取块内容，将所有 HTML 标签转化为块内序列锚点 (Sequence B)。
        使用成对稀有字符 ⭀content⭀ 格式，由 INNER_DELIMS 提供序列。
        """
        format_tags = []
        local_counter = [0]
        
        monolithic_tags = ['math', 'svg', 'canvas', 'video', 'audio', 'img', 'br', 'hr']

        def recursive_extract(node, is_root=False):
            if isinstance(node, str):
                return node.replace('<', '&lt;').replace('>', '&gt;')
            
            if hasattr(node, 'name'):
                if node.name in monolithic_tags:
                    delim = self.get_inner_delimiters(local_counter[0])[0]
                    local_counter[0] += 1
                    format_tags.append({
                        'id': delim,
                        'tag': node.name,
                        'attrs': dict(node.attrs),
                        'raw_html': str(node),
                        'type': 'monolithic'
                    })
                    return f"{delim}{delim}"
                
                # 递归处理子节点
                child_parts = []
                for child in node.children:
                    child_parts.append(recursive_extract(child))
                inner_content = "".join(child_parts)
                
                if is_root:
                    return inner_content
                
                delim = self.get_inner_delimiters(local_counter[0])[0]
                local_counter[0] += 1
                
                tag_info = {
                    'id': delim,
                    'tag': node.name,
                    'attrs': dict(node.attrs),
                    'type': 'container'
                }
                format_tags.append(tag_info)
                
                if inner_content:
                    return f"{delim}{inner_content}{delim}"
                else:
                    return delim

            return ""

        full_text = recursive_extract(element, is_root=True).strip()
        
        # --- 优化逻辑：折叠标签 (Tag Folding) ---
        # 识别开头和结尾的锚点字符 (Sequence B) 以及包裹全文本的标签
        folded_formats = []
        delims_chars = "".join(self.INNER_DELIMS)
        
        changed = True
        while changed:
            changed = False
            # 1. 检查开头和结尾的对称包裹标签
            if len(full_text) >= 2:
                if full_text[0] in delims_chars and full_text[0] == full_text[-1]:
                    char = full_text[0]
                    # 确保这个字符在内部没有出现过（即它确实是包裹性的）
                    if full_text.count(char) == 2:
                        # 找到对应的 tag_info
                        tag_idx = -1
                        for idx, fmt in enumerate(format_tags):
                            if fmt['id'] == char and fmt.get('type') == 'container':
                                tag_idx = idx
                                break
                        
                            fmt = format_tags.pop(tag_idx)
                            fmt['fold_type'] = 'wrap'
                            folded_formats.append(fmt)
                            full_text = full_text[1:-1].strip()
                            changed = True
                            continue

            # 2. 检查开头的纯单点/空标签 (如空锚点)
            if full_text and full_text[0] in delims_chars:
                char = full_text[0]
                tag_idx = -1
                for idx, fmt in enumerate(format_tags):
                    if fmt['id'] == char:
                        tag_idx = idx
                        break
                
                    # 单点字符可能是 monolithic 或者空 container
                    # Monolithic 现在是 pair 形式，所以 count 应该是 2 (即使它没有 content)
                    is_monolithic = (format_tags[tag_idx].get('type') == 'monolithic' and full_text.startswith(char + char))
                    is_empty_container = (format_tags[tag_idx].get('type') == 'container' and full_text.count(char) == 1)
                    
                    if is_monolithic:
                        fmt = format_tags.pop(tag_idx)
                        fmt['fold_type'] = 'prefix'
                        folded_formats.append(fmt)
                        full_text = full_text[2:].strip()
                        changed = True
                        continue
                    elif is_empty_container:
                        fmt = format_tags.pop(tag_idx)
                        fmt['fold_type'] = 'prefix'
                        folded_formats.append(fmt)
                        full_text = full_text[1:].strip()
                        changed = True
                        continue

            # 3. 检查结尾的纯单点/空标签
            if full_text and full_text[-1] in delims_chars:
                char = full_text[-1]
                tag_idx = -1
                for idx, fmt in enumerate(format_tags):
                    if fmt['id'] == char:
                        tag_idx = idx
                        break
                
                if tag_idx != -1:
                    is_monolithic = (format_tags[tag_idx].get('type') == 'monolithic' and full_text.endswith(char + char))
                    is_empty_container = (format_tags[tag_idx].get('type') == 'container' and full_text.count(char) == 1)
                    
                    if is_monolithic:
                        fmt = format_tags.pop(tag_idx)
                        fmt['fold_type'] = 'suffix'
                        folded_formats.append(fmt)
                        full_text = full_text[:-2].strip()
                        changed = True
                        continue
                    elif is_empty_container:
                        fmt = format_tags.pop(tag_idx)
                        fmt['fold_type'] = 'suffix'
                        folded_formats.append(fmt)
                        full_text = full_text[:-1].strip()
                        changed = True
                        continue
        
        # 将折叠的标签合并到 formats 中，但标记为已合并
        for fmt in folded_formats:
            fmt['is_folded'] = True
            format_tags.append(fmt)

        # 终极净化：将内部所有空白字符集（换行、制表符、连续空格）合并为一个空格，模拟浏览器渲染效果
        full_text = re.sub(r'\s+', ' ', full_text).strip()

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
        
        # 降阈值，强制拆分容器标签为更小的语义块
        COHESIVE_THRESHOLD = 1 

        def get_text_size(node):
            if not node: return 0
            if isinstance(node, str):
                return len(node.strip())
            # 改进：更加严格的文本提取，排除掉仅包含空白字符的情况
            text = node.get_text(strip=True)
            return len(text)

        def tag_and_add_block(node):
            size = get_text_size(node)
            if size > 0:
                # 核心改进：ID-Aware 发现逻辑
                if node.has_attr('data-trans-idx'):
                    idx = int(node['data-trans-idx'])
                else:
                    idx = start_global_idx + len(blocks)
                    node['data-trans-idx'] = str(idx)
                
                text, formats = self.extract_block_with_local_ids(node)
                
                # 终极净化：如果提取出的文本在去除所有锚点符号和空白后为空，则不提取
                # Sequence A: 2A40-2AA3, Sequence B: 2B40-2BA3, 加上 Unicode 空白 \u00A0
                clean_text = re.sub(r'[\u2A40-\u2AA3\u2B40-\u2BA3\s\u00A0]', '', text)
                if not clean_text:
                    return

                blocks.append({
                    'element': node,
                    'text': text,
                    'formats': formats,
                    'size': len(clean_text), # 使用实际文本长度
                    'global_idx': idx
                })

        def process_node(node):
            if not node or isinstance(node, str):
                return
            
            # 1. 优先检查容器标签，决定是否拆解
            if node.name in container_tags:
                total_size = get_text_size(node)
                if total_size == 0:
                    return

                # 是否包含可以继续拆分的子结构
                has_child_structures = any(
                    child.name in semantic_tags or child.name in container_tags
                    for child in node.find_all(True, recursive=False)
                )

                # 如果内容很少或是叶子容器，则整体作为一个块
                if total_size < COHESIVE_THRESHOLD or not has_child_structures:
                    tag_and_add_block(node)
                else:
                    # 递归拆解容器内容
                    for child in node.children:
                        process_node(child)
                return

            # 2. 检查语义标签
            if node.name in semantic_tags:
                tag_and_add_block(node)
                return

            # 3. 处理既非容器也非语义的标签（可能是 span, b 等，如果它们出现在顶层）
            if get_text_size(node) > 0:
                tag_and_add_block(node)

        if hasattr(soup, 'body') and soup.body:
            root = soup.body
        elif soup.name == '[document]':
            root = soup
        else:
            root = soup

        for child in root.children:
            process_node(child)
            
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
        1. 确保每一行（由 Sequence A 定义）都有正确的起始和结束。
        2. 确保行内锚点 (Sequence B) 成对出现。
        """
        lines = text.split('\n')
        repaired_lines = []
        
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            
            # 找到该行对应的 Sequence A 标识符
            ds, de = self.get_block_delimiters(i)
            
            # 1. 修复行级锚点 (Sequence A)
            if not line.startswith(ds):
                line = ds + line
            if not line.endswith(de):
                line = line + de
            
            # 2. 修复行内锚点 (Sequence B) 对称性
            for delim in self.INNER_DELIMS:
                count = line.count(delim)
                if count % 2 == 1:
                    # 在末尾（行级锚点之前）补一个
                    line = line[:-1] + delim + de
            
            repaired_lines.append(line)
            
        return "\n".join(repaired_lines)

    def check_anchor_format(self, text):
        """全面检测格式完整性"""
        lines = text.split('\n')
        for i, line in enumerate(lines):
            line = line.strip()
            if not line: continue
            
            ds, de = self.get_block_delimiters(i)
            # 检查行首尾配对
            if not (line.startswith(ds) and line.endswith(de)):
                return False
            
            # 检查内部对称
            for delim in self.INNER_DELIMS:
                if line.count(delim) % 2 != 0:
                    return False
        return True

    def validate_and_parse_response(self, response_text, original_group, auto_repair=False):
        """
        [扁平解析] 解析 AI 返回的多个块。
        增加行数一致性校验。
        """
        if auto_repair:
            response_text = self.repair_translated_text(response_text)
        
        content = response_text.strip()
            
        translated_texts = []
        last_pos = 0
        success = True
        
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
                # 容错：如果找不到该块，标识失败并保留原文
                translated_texts.append(original_group[i]['text'])
                success = False
        
        # 严格检查：解析出的有效块数量必须等于请求的块数量
        if len(translated_texts) != len(original_group):
            success = False
            
        return translated_texts, success

    def restore_html(self, original_block, translated_text, soup):
        """
        将翻译后的带锚点文本还原为 HTML 元素。
        采用递归策略处理嵌套的 Sequence B 分隔符。
        """
        element = original_block['element']
        format_map = {f['id']: f for f in original_block['formats'] if not f.get('is_folded')}
        folded_tags = [f for f in original_block['formats'] if f.get('is_folded')]
        
        # 识别所有 INNER_DELIMS 中的字符
        delims_chars = "".join(self.INNER_DELIMS)
        
        def parse_recursive(text):
            nodes = []
            i = 0
            while i < len(text):
                char = text[i]
                if char in delims_chars and char in format_map:
                    fmt = format_map[char]
                    if fmt['type'] == 'monolithic':
                        # 单体标签 (img, br 等)
                        mono_soup = BeautifulSoup(fmt['raw_html'], 'html.parser')
                        if mono_soup.contents:
                            import copy
                            nodes.append(copy.copy(mono_soup.contents[0]))
                        
                        # 消耗掉成对的第二个字符 (如果是成对的话)
                        if i + 1 < len(text) and text[i+1] == char:
                            i += 2
                        else:
                            i += 1
                    else:
                        # 容器标签 (span, b, a 等)
                        # 寻找匹配的闭合符号
                        start_idx = i + 1
                        balance = 1
                        j = i + 1
                        while j < len(text) and balance > 0:
                            if text[j] == char:
                                balance -= 1
                            j += 1
                        
                        if balance == 0:
                            # 找到匹配，递归处理内部内容
                            inner_text = text[start_idx : j-1]
                            new_tag = soup.new_tag(fmt['tag'])
                            for k, v in fmt['attrs'].items():
                                new_tag[k] = v
                            
                            for child_node in parse_recursive(inner_text):
                                new_tag.append(child_node)
                            
                            nodes.append(new_tag)
                            i = j
                        else:
                            # 未找到闭合，当做普通文本处理 (防止崩溃)
                            nodes.append(soup.new_string(char))
                            i += 1
                else:
                    # 普通文本
                    nodes.append(soup.new_string(char))
                    i += 1
            return nodes

        def finalize_nodes(nodes):
            """合并连续的文本节点"""
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

        # 核心逻辑：应用折叠标签
        # 1. 解析核心内容
        core_nodes = finalize_nodes(parse_recursive(translated_text))
        
        # 2. 按顺序还原折叠标签 (实际上剥皮时是 LIFO，还原时倒序即为按照正确嵌套层级外包)
        current_content = core_nodes
        # folded_tags 列表中的顺序是发现顺序。由于我们是在 while True 中剥洋葱，
        # 列表最后的标签是最先被剥离的（即最外层）。
        # 但如果是 prefix/suffix, 剥离顺序决定了它们在 inner 之外的拓扑顺序。
        # 倒序遍历可以确保最外层的 wrap 最后包，从而维持洋葱结构。
        for fmt in reversed(folded_tags):
            ftype = fmt.get('fold_type')
            if ftype == 'wrap':
                new_tag = soup.new_tag(fmt['tag'])
                for k, v in fmt['attrs'].items(): new_tag[k] = v
                for node in current_content:
                    new_tag.append(node)
                current_content = [new_tag]
            elif ftype == 'prefix':
                if fmt['type'] == 'monolithic':
                    mono_soup = BeautifulSoup(fmt['raw_html'], 'html.parser')
                    node = None
                    if mono_soup.contents:
                        import copy
                        node = copy.copy(mono_soup.contents[0])
                    if node: current_content = [node] + current_content
                else:
                    new_tag = soup.new_tag(fmt['tag'])
                    for k, v in fmt['attrs'].items(): new_tag[k] = v
                    current_content = [new_tag] + current_content
            elif ftype == 'suffix':
                if fmt['type'] == 'monolithic':
                    mono_soup = BeautifulSoup(fmt['raw_html'], 'html.parser')
                    node = None
                    if mono_soup.contents:
                        import copy
                        node = copy.copy(mono_soup.contents[0])
                    if node: current_content = current_content + [node]
                else:
                    new_tag = soup.new_tag(fmt['tag'])
                    for k, v in fmt['attrs'].items(): new_tag[k] = v
                    current_content = current_content + [new_tag]

        element.clear()
        for node in current_content:
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
