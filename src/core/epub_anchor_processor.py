import os
import re
import zipfile
import shutil
import tempfile


class EPubAnchorProcessor:
    """
    纯正则逐行 HTML 提取与还原处理器。
    原则：
    1. 不使用任何 HTML 解析库（无 BeautifulSoup / lxml / html.parser）。
    2. 以"行"为最小翻译单位——只要一行含有可读文本就提取整行。
    3. 简化标签时生成 1-to-1 的标签对应表 (tag_mapping)，用于精确回填。
    4. 回填时通过纯字符串替换将简化标签还原为原始 HTML 标签。
    """

    # 匹配 HTML 注释、处理指令、DOCTYPE、所有标签 (包含属性)
    TAG_PATTERN = re.compile(
        r'<!--.*?-->'             # HTML 注释
        r'|<\?.*?\?>'            # XML 处理指令 <?xml ...?>
        r'|<!DOCTYPE[^>]*>'      # DOCTYPE 声明
        r'|</?[a-zA-Z0-9\-\:]+(?:\s+[^>]*)?>'  # 普通标签
        r'|<[a-zA-Z0-9\-\:]+(?:\s+[^>]*)?/>'   # 自闭合标签
        , re.DOTALL | re.IGNORECASE)
    # 已知的自闭合标签
    SELF_CLOSING_TAGS = {'img', 'br', 'hr', 'col', 'meta', 'link', 'input',
                         'base', 'source', 'area', 'param', 'track', 'wbr', 'keygen'}

    def __init__(self, max_group_chars=2000):
        self.max_group_chars = max_group_chars
        self.temp_dir = None

    # ──────────────────────────────────────────────
    #  EPUB 解压 / 打包
    # ──────────────────────────────────────────────

    def extract_epub(self, epub_path, callback=None):
        """将 EPUB 完整解压到临时目录"""
        if callback:
            callback(f"正在解压 EPUB: {epub_path}")
        self.temp_dir = tempfile.mkdtemp(prefix="epub_")
        with zipfile.ZipFile(epub_path, 'r') as zip_ref:
            zip_ref.extractall(self.temp_dir)
        return self.temp_dir

    def get_xhtml_files(self):
        """返回 EPUB 中所有 XHTML/HTML 内容文件（包括目录文件）"""
        if not self.temp_dir:
            return []
        content_files = []
        for root, dirs, files in os.walk(self.temp_dir):
            for file in files:
                if file.lower().endswith(('.xhtml', '.html', '.htm')):
                    content_files.append(os.path.join(root, file))
        return content_files

    def repack_epub(self, output_path):
        """原封不动打包临时目录"""
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

    # ──────────────────────────────────────────────
    #  核心：逐行提取
    # ──────────────────────────────────────────────

    @staticmethod
    def line_has_text(line):
        """
        判断一行是否含有可翻译的文本。
        去除所有 HTML 标签后，检查是否含有字母、数字或 CJK 字符。
        """
        no_tags = EPubAnchorProcessor.TAG_PATTERN.sub('', line)
        return bool(re.search(
            r'[a-zA-Z0-9'
            r'\u4e00-\u9fff'    # CJK Unified
            r'\u3040-\u309f'    # Hiragana
            r'\u30a0-\u30ff'    # Katakana
            r'\uac00-\ud7af'    # Hangul
            r'\u0400-\u04ff'    # Cyrillic
            r'\u00c0-\u024f'    # Latin Extended
            r']', no_tags))

    def extract_lines(self, html_string):
        """
        从 HTML 字符串中提取所有含有可翻译文本的行。
        返回 list[dict]，每个 dict 包含:
          - line_idx: 原始行号 (0-indexed)
          - orig_line: 原始行内容（含换行符）
          - simplified: 简化后的行内容（标签换为占位符）
          - tag_mapping: dict, 占位符 -> 原始标签字符串
          - indent: 行首空白
          - trailing: 行尾空白（含换行）
        """
        lines = html_string.splitlines(keepends=True)
        blocks = []
        for i, line in enumerate(lines):
            if self.line_has_text(line):
                simplified, tag_mapping, indent, trailing = self.extract_and_simplify(line)
                blocks.append({
                    'line_idx': i,
                    'orig_line': line,
                    'simplified': simplified,
                    'tag_mapping': tag_mapping,
                    'indent': indent,
                    'trailing': trailing,
                })
        return blocks

    # ──────────────────────────────────────────────
    #  核心：标签简化 (1-to-1 映射表)
    # ──────────────────────────────────────────────

    def extract_and_simplify(self, line):
        """
        将一行 HTML 中的所有标签替换为简化占位符，并返回完整的 1-to-1 映射表。
        
        配对标签（如 <span class="x">...</span>）→ <t1>...</t1>
        自闭合/不可配对标签（如 <br/>, <!-- -->, 孤立 </span>）→ <s1/>
        
        Returns:
            (simplified_text, tag_mapping, indent, trailing)
        """
        tags = list(self.TAG_PATTERN.finditer(line))
        if not tags:
            # 无标签，纯文本行
            indent_m = re.match(r'^(\s*)', line)
            indent = indent_m.group(1) if indent_m else ""
            trailing_m = re.search(r'(\s*)$', line)
            trailing = trailing_m.group(1) if trailing_m else ""
            return line.strip(), {}, indent, trailing

        # ── 第一遍：配对标签 ──
        open_stack = []      # [(tag_name, tag_index_in_list), ...]
        pairs = {}           # {open_idx: close_idx}
        unpaired = set()     # 无法配对的标签索引

        for i, match in enumerate(tags):
            tag_str = match.group()

            # HTML 注释
            if tag_str.startswith('<!--'):
                unpaired.add(i)
                continue

            # 闭合标签
            if tag_str.startswith('</'):
                tag_name = re.match(r'</([a-zA-Z0-9\-\:]+)', tag_str)
                if not tag_name:
                    unpaired.add(i)
                    continue
                tag_name = tag_name.group(1).lower()
                # 从栈中反向查找匹配的开标签
                found_idx = -1
                for j in range(len(open_stack) - 1, -1, -1):
                    if open_stack[j][0] == tag_name:
                        found_idx = j
                        break
                if found_idx != -1:
                    start_i = open_stack.pop(found_idx)[1]
                    pairs[start_i] = i
                else:
                    unpaired.add(i)
                continue

            # 开/自闭合标签
            tag_name_m = re.match(r'<([a-zA-Z0-9\-\:]+)', tag_str)
            if not tag_name_m:
                unpaired.add(i)
                continue
            tag_name = tag_name_m.group(1).lower()
            is_self_closing = tag_str.rstrip().endswith('/>') or tag_name in self.SELF_CLOSING_TAGS
            if is_self_closing:
                unpaired.add(i)
            else:
                open_stack.append((tag_name, i))

        # 栈中剩余的开标签，也是无配对的
        for _, i in open_stack:
            unpaired.add(i)

        # ── 第二遍：分配简化 ID ──
        replacements = {}    # tag_index -> simplified placeholder
        tag_mapping = {}     # placeholder -> original tag string
        t_counter = 1
        s_counter = 1

        for i in range(len(tags)):
            if i in pairs:
                # 开标签
                start_token = f"<t{t_counter}>"
                end_token = f"</t{t_counter}>"
                replacements[i] = start_token
                replacements[pairs[i]] = end_token
                tag_mapping[start_token] = tags[i].group()
                tag_mapping[end_token] = tags[pairs[i]].group()
                t_counter += 1
            elif i in unpaired:
                s_token = f"<s{s_counter}/>"
                replacements[i] = s_token
                tag_mapping[s_token] = tags[i].group()
                s_counter += 1
            # 如果 i 既不在 pairs 也不在 unpaired，说明它是某个 pair 的 close 端，
            # 已经在 pairs[open] = close 时处理过了

        # ── 第三遍：组装简化行 ──
        simplified = ""
        last_pos = 0
        for i, match in enumerate(tags):
            start_pos, end_pos = match.start(), match.end()
            simplified += line[last_pos:start_pos]
            if i in replacements:
                simplified += replacements[i]
            last_pos = end_pos
        simplified += line[last_pos:]

        # 提取缩进和尾部空白
        indent_m = re.match(r'^(\s*)', simplified)
        indent = indent_m.group(1) if indent_m else ""
        trailing_m = re.search(r'(\s*)$', simplified)
        trailing = trailing_m.group(1) if trailing_m else ""
        clean_text = simplified.strip()

        return clean_text, tag_mapping, indent, trailing

    # ──────────────────────────────────────────────
    #  核心：还原 (回填)
    # ──────────────────────────────────────────────

    def restore_line(self, translated_text, tag_mapping, indent, trailing):
        """
        将翻译后的简化文本还原为 HTML 行。
        
        容错规则：
        1. 去重：同一个占位符如果出现多次，只保留第一次。
        2. 丢弃伪造：不在 tag_mapping 中的占位符直接丢弃。
        3. 追加丢失：tag_mapping 中存在但翻译中未出现的占位符追加到末尾。
        4. 替换：所有占位符用 tag_mapping 中的原始标签字符串替换。
        """
        # 1. 去重，丢弃伪造
        seen_tokens = set()

        def deduplicate(match):
            token = match.group(0)
            if token not in tag_mapping:
                return ""  # 丢弃伪造的占位符
            if token in seen_tokens:
                return ""  # 去重
            seen_tokens.add(token)
            return token

        dedup_text = re.sub(r'</?t\d+>|<s\d+/>', deduplicate, translated_text)

        # 2. 追加丢失的占位符
        for token in tag_mapping:
            if token not in seen_tokens:
                dedup_text += token

        # 3. 替换为原始 HTML 标签
        def replace_real(match):
            token = match.group(0)
            return tag_mapping.get(token, token)

        restored = re.sub(r'</?t\d+>|<s\d+/>', replace_real, dedup_text)
        return indent + restored + trailing

    # ──────────────────────────────────────────────
    #  分组与 AI 提示格式
    # ──────────────────────────────────────────────

    def get_block_delimiters(self, index):
        """获取组内第 index 个块的分隔符"""
        return f"<{index + 1}>", f"</{index + 1}>"

    def format_for_ai(self, group_blocks):
        """将一组块格式化为 AI 提示格式"""
        lines = []
        for i, block in enumerate(group_blocks):
            ds, de = self.get_block_delimiters(i)
            lines.append(f"{ds}{block['simplified']}{de}")
        return "\n".join(lines)

    def check_anchor_format(self, text, expected_count):
        """
        全面检测格式完整性:
        1. 检查 <n>...</n> 边界。
        2. 检查内部 <tn>...</tn> 是否成对。
        """
        content = text.strip()
        blocks = re.findall(r'<(\d+)>(.*?)</\1>', content, re.DOTALL)
        if len(blocks) != expected_count:
            return "line_count_mismatch"
        for i, (idx_str, block_content) in enumerate(blocks):
            if int(idx_str) != i + 1:
                return f"index_mismatch_at_{idx_str}_expected_{i + 1}"
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
        """
        content = response_text.strip()
        expected_len = len(original_group)
        pattern = r'<(\d+)>(.*?)</\1>'
        matches = list(re.finditer(pattern, content, re.DOTALL))
        found_blocks = {}
        for m in matches:
            b_id = int(m.group(1))
            b_content = m.group(2).strip()
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
                translated_texts.append(original_group[i]['simplified'])
        return translated_texts, any_found

    # ──────────────────────────────────────────────
    #  便捷兼容接口
    # ──────────────────────────────────────────────

    def create_blocks_from_html(self, html_string, start_global_idx=0):
        """
        从 HTML 文件内容提取所有含文本行，返回 block 列表。
        每个 block 包含 line_idx, orig_line, simplified, tag_mapping, indent, trailing, global_idx。
        """
        blocks = self.extract_lines(html_string)
        for i, b in enumerate(blocks):
            b['global_idx'] = start_global_idx + i
            # 为兼容旧接口保留 text 字段
            b['text'] = b['simplified']
            b['formats'] = b['tag_mapping']
        return blocks
