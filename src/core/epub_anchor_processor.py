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
        """获取组内第 index 个块的分隔符 (使用 [[n]] 格式)"""
        tag = f"[[{index+1}]]"
        return tag, tag

    def get_inner_delimiters(self, index):
        """获取块内第 index 个标签的分隔符 (使用 ((A)) 格式)"""
        res = ""
        temp = index
        while temp >= 0:
            res = chr(65 + (temp % 26)) + res
            temp = (temp // 26) - 1
        tag = f"(({res}))"
        return tag, tag

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
        核心逻辑：提取块内容。
        1. Tag Folding：折叠完整包裹或边缘的空标签。
        2. Internal Anchors：将其余内部标签转化为 ⟬n⟭ 锚点。
        """
        content = element.decode_contents().strip()
        format_tags = [] # 存储所有格式信息（折叠标签 + 内部锚点）
        
        while True:
            temp_soup = BeautifulSoup(content, 'html.parser')
            all_nodes = [c for c in temp_soup.contents if not (isinstance(c, str) and not c.strip())]
            
            if not all_nodes:
                break
                
            changed = False
            # Prefix Folding
            first = all_nodes[0]
            if hasattr(first, 'name') and not first.get_text(strip=True) and not first.find_all(True):
                format_tags.append({
                    'tag': first.name,
                    'attrs': dict(first.attrs),
                    'is_folded': True,
                    'fold_type': 'prefix'
                })
                del all_nodes[0]
                content = "".join(str(n) for n in all_nodes)
                changed = True
            # Suffix Folding
            elif hasattr(all_nodes[-1], 'name') and not all_nodes[-1].get_text(strip=True) and not all_nodes[-1].find_all(True):
                last = all_nodes[-1]
                format_tags.append({
                    'tag': last.name,
                    'attrs': dict(last.attrs),
                    'is_folded': True,
                    'fold_type': 'suffix'
                })
                del all_nodes[-1]
                content = "".join(str(n) for n in all_nodes)
                changed = True
            # Wrapping Folding
            elif len(all_nodes) == 1 and all_nodes[0].name:
                tag = all_nodes[0]
                format_tags.append({
                    'tag': tag.name,
                    'attrs': dict(tag.attrs),
                    'is_folded': True,
                    'fold_type': 'wrap'
                })
                content = tag.decode_contents().strip()
                changed = True
                
            if not changed:
                break

        # 接下来处理内部锚点 (⟬n⟭)
        temp_soup = BeautifulSoup(content, 'html.parser')
        local_counter = [0]
        monolithic_tags = ['math', 'svg', 'canvas', 'video', 'audio', 'img', 'br', 'hr']

        def recursive_extract(node):
            if isinstance(node, str):
                return node.replace('<', '&lt;').replace('>', '&gt;')
            
            if hasattr(node, 'name') and node.name:
                if node.name in monolithic_tags:
                    delim = self.get_inner_delimiters(local_counter[0])[0]
                    local_counter[0] += 1
                    format_tags.append({
                        'id': delim,
                        'tag': node.name,
                        'attrs': dict(node.attrs),
                        'raw_html': str(node),
                        'type': 'monolithic',
                        'is_internal': True
                    })
                    return f"{delim}{delim}"
                
                # 容器标签
                child_parts = []
                for child in node.children:
                    child_parts.append(recursive_extract(child))
                
                inner_text = "".join(child_parts)
                delim = self.get_inner_delimiters(local_counter[0])[0]
                local_counter[0] += 1
                
                format_tags.append({
                    'id': delim,
                    'tag': node.name,
                    'attrs': dict(node.attrs),
                    'type': 'container',
                    'is_internal': True
                })
                return f"{delim}{inner_text}{delim}"
            return ""

        final_parts = []
        for child in temp_soup.contents:
            final_parts.append(recursive_extract(child))
            
        full_text = "".join(final_parts)
        full_text = re.sub(r'\s+', ' ', full_text).strip()
        
        return full_text, format_tags

    def extract_block_with_local_ids_legacy(self, element):
        """
        [旧版保留供参考] 以前将 HTML 标签转化为锚点的逻辑。
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
                    part = recursive_extract(child)
                    if not part:
                        continue
                        
                    # 检查 child 是否是块级元素 (如果是，前后加换行)
                    is_block = False
                    if hasattr(child, 'name') and child.name in [
                        'p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 
                        'li', 'ol', 'ul', 'nav', 'blockquote', 'pre', 'hr', 'tr', 'table'
                    ]:
                        is_block = True
                        
                    if is_block:
                       child_parts.append(f"\n{part}\n")
                    else:
                       child_parts.append(part)

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
                    # 空容器也使用成对格式，确保 restore_html 对称
                    return f"{delim}{delim}"

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
                        
                        if tag_idx != -1:
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
                
                if tag_idx != -1:
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

        # 终极净化：折叠所有空白字符（空格、换行、制表符等）为单个空格
        # 这能彻底解决“译文换行导致行数统计错误”的问题，同时也符合 HTML 渲染逻辑
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
            'caption', 'figcaption', 'dt', 'dd', 'cite', 'footer', 'aside'
        }
        container_tags = {
            'div', 'section', 'article', 'body', 'table', 'tr', 'td', 'th', 
            'blockquote', 'thead', 'tbody', 'tfoot', 'dl', 'ol', 'ul', 'nav', 'li'
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
                # [[ ]] and (( )) are ASCII, no need for special range here unless we want to be specific
                clean_text = re.sub(r'\[\[\d+\]\]|\(\([A-Z]+\)\)|\s|\u00A0', '', text)
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
            if not node:
                return
            
            # 0. Handle Text Nodes (often dropped in previous version)
            if isinstance(node, str):
                if node.strip():
                   # Wrap in a temporary span-like structure or just process it?
                   # Since tag_and_add_block expects an element with attributes, 
                   # we might need to wrap it if it's raw text.
                   # However, BS4 NavigableString doesn't have attrs.
                   # Let's wrap it in a dummy tag to consistent processing.
                   new_span = soup.new_tag("span")
                   new_span.string = node
                   # Check size
                   if get_text_size(new_span) > 0:
                       tag_and_add_block(new_span)
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



    def check_anchor_format(self, text, expected_count):
        """
        全面检测格式完整性:
        1. 检查每行 [[n]] 边界。
        2. 检查内部 ((A)) 是否成对。
        """
        lines = text.strip().split('\n')
        valid_lines = [l for l in lines if l.strip()]
        
        if len(valid_lines) != expected_count:
            return "line_count_mismatch"

        for i, line in enumerate(valid_lines):
            line = line.strip()
            ds, de = self.get_block_delimiters(i)
            if not (line.startswith(ds) and line.endswith(de)):
                return "delimiter_mismatch"
            
            # 内部锚点平衡性检查
            internal_anchors = re.findall(r'\(\([A-Z0-9]+\)\)', line)
            for anchor in set(internal_anchors):
                if line.count(anchor) % 2 != 0:
                    return f"unbalanced_internal_{anchor}"
            
        return "ok"

    def validate_and_parse_response(self, response_text, original_group, auto_repair=False):
        """
        [扁平解析] 解析 AI 返回的多个块。
        增加行数一致性校验。
        """
        content = response_text.strip()
            
        translated_texts = []
        last_pos = 0
        success = True
        
        for i in range(len(original_group)):
            ds, de = self.get_block_delimiters(i)
            # 匹配 [[n]]...[[n]] 格式，n 可能为多位数
            # 需要转义方括号
            ds_esc = re.escape(ds)
            de_esc = re.escape(de)
            block_pattern = ds_esc + r'(.*?)' + de_esc
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
        将翻译后的带 ⟬n⟭ 锚点的文本还原为 HTML 元素。
        1. 还原块内 ⟬n⟭ 锚点。
        2. 应用折叠的标签 (Folding Tags)。
        """
        element = original_block['element']
        format_tags = original_block.get('formats', [])
        
        # 分离折叠标签和内部锚点
        internal_anchors = [f for f in format_tags if f.get('is_internal')]
        folded_tags = [f for f in format_tags if f.get('is_folded')]
        
        # 1. 还原内部锚点 (⟬n⟭)
        current_html = translated_text
        # 按 ID 长度降序替换，防止 ⟬10⟭ 匹配到 ⟬1⟭
        internal_anchors.sort(key=lambda x: len(x['id']), reverse=True)
        
        for fmt in internal_anchors:
            delim = fmt['id']
            if fmt['type'] == 'monolithic':
                # 单体标签还原
                current_html = current_html.replace(f"{delim}{delim}", fmt['raw_html'])
            else:
                # 容器标签还原
                start_tag = f"<{fmt['tag']}"
                for k, v in fmt['attrs'].items():
                    if isinstance(v, list): v = " ".join(v)
                    start_tag += f' {k}="{v}"'
                start_tag += ">"
                end_tag = f"</{fmt['tag']}>"
                
                # 双向替换锚点
                parts = current_html.split(delim)
                if len(parts) >= 3:
                    # 假设 AI 保留了成对的锚点
                    new_parts = [parts[0]]
                    for i in range(1, len(parts) - 1, 2):
                        new_parts.append(start_tag)
                        new_parts.append(parts[i])
                        new_parts.append(end_tag)
                        new_parts.append(parts[i+1])
                    current_html = "".join(new_parts)

        # 2. 应用折叠标签 (按洋葱模型在外周还原, 即逆序还原)
        import copy
        for fmt in reversed(folded_tags):
            ftype = fmt.get('fold_type', 'wrap')
            new_tag = soup.new_tag(fmt['tag'])
            for k, v in fmt['attrs'].items():
                new_tag[k] = v
            
            if ftype == 'wrap':
                inner_soup = BeautifulSoup(current_html, 'html.parser')
                target_inner = inner_soup.body if inner_soup.body else inner_soup
                for node in list(target_inner.contents):
                    new_tag.append(copy.copy(node))
                current_html = str(new_tag)
            elif ftype == 'prefix':
                current_html = str(new_tag) + current_html
            elif ftype == 'suffix':
                current_html = current_html + str(new_tag)

        element.clear()
        final_soup = BeautifulSoup(current_html, 'html.parser')
        target_root = final_soup.body if final_soup.body else final_soup
        
        for node in list(target_root.contents):
            element.append(copy.copy(node))

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
