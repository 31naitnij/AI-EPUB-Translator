import os
import re
import zipfile
import shutil
import tempfile
from bs4 import BeautifulSoup, NavigableString, Comment

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
        """获取组内第 index 个块的分隔符 (使用 <n></n> 格式)"""
        return f"<{index+1}>", f"</{index+1}>"

    def get_inner_delimiters(self, index, is_self_closing=False):
        """获取块内第 index 个标签的分隔符 (使用 <tn></tn> 或 <sn/> 格式)"""
        if is_self_closing:
            return f"<s{index+1}/>", f"<s{index+1}/>"
        return f"<t{index+1}>", f"</t{index+1}>"

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

    def extract_block_with_local_ids(self, element, current_tag_idx=0):
        """
        核心逻辑：提取块内容并分配标签 ID。
        使用简化标签策略：标签 ID 在当前请求中累加。
        """
        format_tags = [] 
        tag_counter = [current_tag_idx]
        monolithic_tags = ['math', 'svg', 'canvas', 'video', 'audio', 'img', 'br', 'hr']

        def recursive_extract(node):
            if isinstance(node, str):
                # 预清理文本中的 HTML 特殊字符，但保留空白，统一在最后处理
                return node.replace('<', '&lt;').replace('>', '&gt;')
            
            if hasattr(node, 'name') and node.name:
                if node.name in monolithic_tags:
                    delim, _ = self.get_inner_delimiters(tag_counter[0], is_self_closing=True)
                    tag_counter[0] += 1
                    format_tags.append({
                        'id': delim,
                        'tag': node.name,
                        'attrs': dict(node.attrs),
                        'raw_html': str(node),
                        'type': 'monolithic',
                        'is_internal': True
                    })
                    return delim
                
                # 容器标签
                child_parts = []
                for child in node.children:
                    child_parts.append(recursive_extract(child))
                
                inner_text = "".join(child_parts)
                start_delim, end_delim = self.get_inner_delimiters(tag_counter[0])
                tag_counter[0] += 1
                
                format_tags.append({
                    'id': start_delim,
                    'tag': node.name,
                    'attrs': dict(node.attrs),
                    'type': 'container',
                    'is_internal': True
                })
                return f"{start_delim}{inner_text}{end_delim}"
            return ""

        final_parts = []
        for child in element.children:
            final_parts.append(recursive_extract(child))
            
        full_text = "".join(final_parts)
        
        # 终极净化：强制将所有连续的空白字符（包括换行）压缩为单个空格
        # 这确保了标签和文本之间紧密相连，不会出现“标签单独占一行”
        full_text = re.sub(r'\s+', ' ', full_text).strip()
        
        return full_text, format_tags, tag_counter[0]

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
        """
        current_tag_idx = [0]
        blocks = []
        semantic_tags = {
            'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 
            'caption', 'figcaption', 'dt', 'dd', 'cite', 'footer', 'aside'
        }
        container_tags = {
            'div', 'section', 'article', 'body', 'table', 'tr', 'td', 'th', 
            'blockquote', 'thead', 'tbody', 'tfoot', 'dl', 'ol', 'ul', 'nav', 'li'
        }
        
        # 低阈值，强制拆分容器标签为更细粒度的语义块，以匹配渲染行数
        COHESIVE_THRESHOLD = 10 

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
                
                text, formats, next_tag_idx = self.extract_block_with_local_ids(node, current_tag_idx[0])
                current_tag_idx[0] = next_tag_idx
                
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
            
            if isinstance(node, NavigableString):
                if not isinstance(node, Comment) and node.strip():
                    new_span = soup.new_tag("span")
                    node.wrap(new_span)
                    tag_and_add_block(new_span)
                return
            
            # 核心改进：深度优先判断是否应该打散块
            # 规则：如果一个节点（无论是容器还是语义标签）包含了其他块级元素，则继续拆解
            has_block_children = any(
                child.name in semantic_tags or child.name in container_tags
                for child in node.find_all(True, recursive=False)
            )

            if node.name in semantic_tags or node.name in container_tags:
                total_size = get_text_size(node)
                if total_size == 0:
                    return

                # 如果它包含更深层的块结构，且内容超过最小内聚阈值，则拆解
                if has_block_children and total_size > COHESIVE_THRESHOLD:
                    for child in list(node.children):
                        process_node(child)
                else:
                    # 叶子语义块或微小结构，整体作为一个翻译单元
                    tag_and_add_block(node)
                return

            # 处理既非容器也非语义的标签（可能是顶层的 span, b 等，虽然少见）
            if get_text_size(node) > 0:
                tag_and_add_block(node)

        if hasattr(soup, 'body') and soup.body:
            root = soup.body
        elif soup.name == '[document]':
            root = soup
        else:
            root = soup

        for child in list(root.children):
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
        1. 检查 <n>...</n> 边界。
        2. 检查内部 <tn>...</tn> 是否成对。
        """
        content = text.strip()
        
        # 查找所有 <n>...</n> 块
        # 使用 DOTALL 允许跨行
        blocks = re.findall(r'<(\d+)>(.*?)</\1>', content, re.DOTALL)
        
        if len(blocks) != expected_count:
            return "line_count_mismatch"

        for i, (idx_str, block_content) in enumerate(blocks):
            # 块索引校验
            if int(idx_str) != i + 1:
                return f"index_mismatch_at_{idx_str}_expected_{i+1}"
            
            # 内部容器标签平衡性检查 <t1>...</t1>
            container_anchors = re.findall(r'<t(\d+)>', block_content)
            for anchor_idx in set(container_anchors):
                start_tag = f"<t{anchor_idx}>"
                end_tag = f"</t{anchor_idx}>"
                if block_content.count(start_tag) != block_content.count(end_tag):
                    return f"unbalanced_internal_t{anchor_idx}"
            
        return "ok"

    def validate_and_parse_response(self, response_text, original_group, auto_repair=False):
        """
        容错解析 AI 响应：
        1. 使用 ID 驱动映射 (<n>...</n>)。
        2. 如果某个 ID 缺失，使用原文回填。
        3. 只要提取到一个有效的块，就认为 success=True。
        """
        content = response_text.strip()
        expected_len = len(original_group)
        
        # 提取所有有效的 <n>...</n> 块
        pattern = r'<(\d+)>(.*?)</\1>'
        matches = list(re.finditer(pattern, content, re.DOTALL))
        
        found_blocks = {}
        for m in matches:
            b_id = int(m.group(1))
            b_content = m.group(2).strip()
            # 记录第一个出现的 ID（防止 AI 重复输出同名块）
            if b_id not in found_blocks:
                found_blocks[b_id] = b_content
                
        translated_texts = []
        any_found = False
        
        for i in range(expected_len):
            expected_id = i + 1
            if expected_id in found_blocks:
                translated_texts.append(found_blocks[expected_id])
                any_found = True
            else:
                # 缺失块：回退到原文
                translated_texts.append(original_group[i]['text'])
                
        return translated_texts, any_found

    def restore_html(self, original_block, translated_text, soup):
        """
        将翻译后的文本还原为 HTML。
        容错规则：
        1. 仅还原存在于 original_block['formats'] 中的 ID。
        2. 若有错误/未知标签则忽略。
        3. 自动闭合翻译中未闭合的标签，确保 HTML 结构安全。
        """
        current_html = translated_text
        formats = original_block.get('formats', [])
        format_map = {f['id']: f for f in formats}
        
        # 记录已打开的标签，用于尾部自动闭合
        open_tags_stack = []

        # 匹配所有简化标签占位符: <t1>, </t1>, <s1/>
        tag_pattern = re.compile(r'<(/?t\d+>|s\d+/>)')

        def replacement_func(match):
            placeholder = match.group(1) # e.g. "t1>", "/t1>", "s1/>"
            full_tag = "<" + placeholder
            
            # 归一化 ID 用于查找 (e.g. </t1> -> <t1>)
            search_id = full_tag
            if full_tag.startswith('</t'):
                search_id = full_tag.replace('</t', '<t')
            
            if search_id not in format_map:
                # 忽略 ID 不存在的标签 (用户要求：若有错误标签，则忽略)
                return ""
            
            f = format_map[search_id]
            tag_name = f['tag']
            
            # 生成真实的开始或结束标签
            if full_tag.startswith('<s'): # 自闭合
                t = soup.new_tag(tag_name)
                for k, v in f['attrs'].items():
                    if isinstance(v, list): v = " ".join(v)
                    t[k] = v
                return str(t)
            
            elif full_tag.startswith('<t'): # 开始标签
                t = soup.new_tag(tag_name)
                for k, v in f['attrs'].items():
                    if isinstance(v, list): v = " ".join(v)
                    t[k] = v
                open_tags_stack.append(tag_name)
                # str(t) 会输出 <tag>内容</tag>，我们只需要前半截
                return str(t).replace(f"</{tag_name}>", "")
            
            elif full_tag.startswith('</t'): # 结束标签
                if open_tags_stack and open_tags_stack[-1] == tag_name:
                    open_tags_stack.pop()
                    return f"</{tag_name}>"
                else:
                    # 不匹配或顺序错误的结束标签 -> 忽略以维持结构
                    return ""
            
            return ""

        # 执行单次替换，确保不会因为索引变动导致错误
        current_html = tag_pattern.sub(replacement_func, current_html)
        
        # 自动闭合所有剩余的标签（洋葱模型）
        while open_tags_stack:
            tag_name = open_tags_stack.pop()
            current_html += f"</{tag_name}>"

        element = original_block['element']
        import copy
        final_soup = BeautifulSoup(current_html, 'html.parser')
        target_root = final_soup.body if final_soup.body else final_soup
        
        element.clear()
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
