import os
import re
import zipfile
import shutil
import tempfile


class EPubDirectProcessor:
    """
    直接处理 HTML 文本，不进行标签简化和格式检查。
    原则：
    1. 不使用任何 HTML 解析库（无 BeautifulSoup / lxml / html.parser）。
    2. 以"段落块"（完整的 <p></p> 等块级元素）为最小提取单位，<p></p> 不可中断。
    3. 不生成 `<t1>` 等简化标签，保持原样。
    4. 不使用 `<1>...</1>` 包装发送给 AI，而是直接拼接多行。
    5. 返回的结果将直接整块替代原文对应区域，不再逐行 1:1 对齐。
    """

    # 匹配 HTML 注释、处理指令、DOCTYPE、所有标签 (包含属性)
    TAG_PATTERN = re.compile(
        r'<!--.*?-->'             # HTML 注释
        r'|<\?.*?\?>'            # XML 处理指令 <?xml ...?>
        r'|<!DOCTYPE[^>]*>'      # DOCTYPE 声明
        r'|</?[a-zA-Z0-9\-\:]+(?:\s+[^>]*)?>'  # 普通标签
        r'|<[a-zA-Z0-9\-\:]+(?:\s+[^>]*)?/>'   # 自闭合标签
        , re.DOTALL | re.IGNORECASE)

    def __init__(self, max_group_chars=2000):
        self.max_group_chars = max_group_chars
        self.temp_dir = None

    # ──────────────────────────────────────────────
    #  EPUB 解压 / 打包
    # ──────────────────────────────────────────────

    def extract_epub(self, epub_path, callback=None):
        """将 EPUB 完整解压到临时目录并进行预格式化"""
        if callback:
            callback(f"正在解压 EPUB: {epub_path}")
        self.temp_dir = tempfile.mkdtemp(prefix="epub_")
        with zipfile.ZipFile(epub_path, 'r') as zip_ref:
            zip_ref.extractall(self.temp_dir)
            
        self._format_html_files(callback)
        return self.temp_dir

    def normalize_html_files(self, target_dir=None, callback=None):
        """
        公开接口：对指定目录（或 self.temp_dir）中的所有 HTML 文件进行规范化排版。
        使阅读排版与代码排版一致：每个块级元素独占一行，元素之间有空行分隔。
        可在任意时机调用（不仅限于初始解压）。
        """
        old_temp_dir = self.temp_dir
        if target_dir:
            self.temp_dir = target_dir
        
        try:
            self._format_html_files(callback)
        finally:
            self.temp_dir = old_temp_dir

    def _format_html_files(self, callback=None):
        """
        对所有 HTML 文件进行块级安全重排（美化）。
        核心规则：
        1. 每个块级开标签前换行，闭标签后换行
        2. 同行多个块级元素（如 <p>aaa.</p><p>bbb.</p>）拆分为独立行
        3. 块级元素之间保留一个空行，提升可读性
        4. 不影响行内标签（<span>, <em>, <strong> 等）
        """
        xhtml_files = self.get_xhtml_files()
        if not xhtml_files:
            return

        # 格式优化仅针对 HTML/XHTML 块级元素; .ncx 目录文件结构不同,
        # 跳过格式化, 但仍由 get_xhtml_files() 返回供提取和翻译使用
        xhtml_files = [f for f in xhtml_files if not f.lower().endswith('.ncx')]
        if not xhtml_files:
            return

        import re
        # 块级标签列表
        BLOCK_TAGS = ['p', 'div', 'h[1-6]', 'ul', 'ol', 'li', 'blockquote',
                      'table', 'tr', 'td', 'th', 'thead', 'tbody', 'tfoot',
                      'figure', 'figcaption', 'header', 'footer',
                      'article', 'section', 'aside', 'nav', 'main',
                      'pre', 'details', 'summary', 'dl', 'dt', 'dd']
        SELF_CLOSING = ['br', 'hr']
        
        block_tags_pattern = '|'.join(BLOCK_TAGS)

        # 匹配块级开标签（含属性）
        pattern_open = re.compile(
            r'(<(?:' + block_tags_pattern + r')\b[^>]*>)', re.IGNORECASE)
        # 匹配块级闭标签
        pattern_close = re.compile(
            r'(</(?:' + block_tags_pattern + r')\b[^>]*>)', re.IGNORECASE)
        # 匹配自闭合标签
        pattern_self = re.compile(
            r'(</?(?:' + '|'.join(SELF_CLOSING) + r')\b[^>]*>)', re.IGNORECASE)

        total = len(xhtml_files)
        for file_idx, filepath in enumerate(xhtml_files):
            try:
                if callback:
                    callback(f"正在规范化 HTML: {file_idx+1}/{total} ({os.path.basename(filepath)})")
                    
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                res = content

                # 步骤 1: 在块级开标签前插入换行（幂等：前一位已是换行则不再插入）
                def newline_before(m):
                    return m.group(1) if m.start() > 0 and m.string[m.start()-1] == '\n' else '\n' + m.group(1)
                res = pattern_open.sub(newline_before, res)

                # 步骤 2: 在块级闭标签后插入换行（幂等：后一位已是换行则不再插入）
                def newline_after(m):
                    return m.group(1) if m.end() < len(m.string) and m.string[m.end()] == '\n' else m.group(1) + '\n'
                res = pattern_close.sub(newline_after, res)

                # 步骤 3: 在自闭合标签后插入换行（幂等）
                res = pattern_self.sub(newline_after, res)
                
                # 步骤 4: 规范化连续空行 — 最多保留一个空行（两个换行符）
                # 先将 3 个及以上连续换行（含中间空白）压缩为两个换行
                res = re.sub(r'\n\s*\n\s*\n', '\n\n', res)
                
                # 步骤 5: 清理文件开头的多余空行
                res = res.lstrip('\n')
                
                # Only save if changed to save I/O
                if res != content:
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(res)
            except Exception as e:
                if callback:
                    callback(f"规范化文件失败 {os.path.basename(filepath)}: {e}")

    def get_xhtml_files(self):
        """
        返回 EPUB 中所有 XHTML/HTML 内容文件，按 OPF spine 定义的阅读顺序排列。
        同时包含 toc.ncx (EPUB2 目录文件), 其中 <text> 标签含可翻译的章节标题。
        若 OPF 解析失败，回退到文件系统遍历 (旧行为)。
        """
        if not self.temp_dir:
            return []

        # 尝试按 OPF spine 顺序解析
        try:
            ordered_files = self._get_spine_ordered_files()
            if ordered_files:
                # 追加 toc.ncx 文件 (EPUB2 目录, 含可翻译的 <text> 条目)
                for root, dirs, files in os.walk(self.temp_dir):
                    for file in files:
                        if file.lower().endswith('.ncx'):
                            ordered_files.append(os.path.join(root, file))
                return ordered_files
        except Exception:
            pass

        # 回退: 文件系统遍历 (旧行为)
        content_files = []
        for root, dirs, files in os.walk(self.temp_dir):
            for file in files:
                if file.lower().endswith(('.xhtml', '.html', '.htm', '.ncx')):
                    content_files.append(os.path.join(root, file))
        return content_files

    def _get_ncx_files(self):
        """返回 EPUB 中所有 .ncx 文件 (EPUB2 目录)"""
        ncx_files = []
        if not self.temp_dir:
            return ncx_files
        for root, dirs, files in os.walk(self.temp_dir):
            for file in files:
                if file.lower().endswith('.ncx'):
                    ncx_files.append(os.path.join(root, file))
        return ncx_files

    def _get_spine_ordered_files(self):
        """
        解析 EPUB 的 OPF 文件，按 <spine> 中 <itemref> 的顺序返回 xhtml 文件。
        spine 之外的 xhtml 文件 (如 nav.xhtml) 追加到末尾，避免遗漏。
        """
        # 1. 读取 META-INF/container.xml 定位 OPF 文件
        container_path = os.path.join(self.temp_dir, "META-INF", "container.xml")
        if not os.path.exists(container_path):
            return []
        with open(container_path, 'r', encoding='utf-8') as f:
            container_content = f.read()
        opf_match = re.search(r'<rootfile\s+[^>]*full-path="([^"]+)"', container_content, re.IGNORECASE)
        if not opf_match:
            return []
        opf_rel_path = opf_match.group(1)
        opf_abs_path = os.path.join(self.temp_dir, opf_rel_path)
        if not os.path.exists(opf_abs_path):
            return []
        opf_dir = os.path.dirname(opf_abs_path)

        # 2. 读取 OPF 内容
        with open(opf_abs_path, 'r', encoding='utf-8') as f:
            opf_content = f.read()

        # 3. 解析 <manifest>: id -> {href, media_type}
        # 注意: 不能用 [^/>] 排除 /, 因为 media-type="application/xhtml+xml" 含 /
        manifest = {}
        for m in re.finditer(r'<item\b([^>]+)>', opf_content, re.IGNORECASE):
            attrs = m.group(1).rstrip('/').strip()
            id_m = re.search(r'\bid="([^"]+)"', attrs)
            href_m = re.search(r'\bhref="([^"]+)"', attrs)
            type_m = re.search(r'\bmedia-type="([^"]+)"', attrs)
            if id_m and href_m:
                manifest[id_m.group(1)] = {
                    'href': href_m.group(1),
                    'media_type': (type_m.group(1) if type_m else "").lower(),
                }

        # 4. 解析 <spine>: 按 <itemref idref="..."> 顺序收集 id
        spine_ids = []
        spine_match = re.search(r'<spine\b[^>]*>(.*?)</spine>', opf_content, re.IGNORECASE | re.DOTALL)
        if spine_match:
            spine_content = spine_match.group(1)
            for m in re.finditer(r'<itemref\s+[^>]*?\bidref="([^"]+)"', spine_content, re.IGNORECASE):
                spine_ids.append(m.group(1))

        if not spine_ids:
            return []

        # 5. 按 spine 顺序收集 xhtml 文件
        from urllib.parse import unquote
        ordered_files = []
        seen_paths = set()
        for item_id in spine_ids:
            item = manifest.get(item_id)
            if not item:
                continue
            # 只处理 xhtml/html 类型，跳过 css/图片/ncx 等
            if 'xhtml' not in item['media_type'] and 'html' not in item['media_type']:
                continue
            href = unquote(item['href'])
            abs_path = os.path.normpath(os.path.join(opf_dir, href))
            if os.path.exists(abs_path) and abs_path not in seen_paths:
                ordered_files.append(abs_path)
                seen_paths.add(abs_path)

        # 6. 追加 spine 之外的 xhtml 文件 (如 nav.xhtml, 不在 spine 中的辅助页面)
        for root, dirs, files in os.walk(self.temp_dir):
            for file in files:
                if file.lower().endswith(('.xhtml', '.html', '.htm')):
                    abs_path = os.path.join(root, file)
                    norm_path = os.path.normpath(abs_path)
                    if norm_path not in seen_paths:
                        ordered_files.append(abs_path)
                        seen_paths.add(norm_path)

        return ordered_files

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
    #  核心：段落块提取（<p></p> 等完整块级元素）
    # ──────────────────────────────────────────────

    @staticmethod
    def line_has_text(line):
        """
        判断一行是否含有可翻译的文本。
        去除所有 HTML 标签后，检查是否含有字母、数字或 CJK 字符。
        """
        no_tags = EPubDirectProcessor.TAG_PATTERN.sub('', line)
        return bool(re.search(
            r'[a-zA-Z0-9'
            r'\u4e00-\u9fff'    # CJK Unified
            r'\u3040-\u309f'    # Hiragana
            r'\u30a0-\u30ff'    # Katakana
            r'\uac00-\ud7af'    # Hangul
            r'\u0400-\u04ff'    # Cyrillic
            r'\u00c0-\u024f'    # Latin Extended
            r']', no_tags))

    def extract_paragraph_blocks(self, html_string):
        """
        从 HTML 字符串中提取完整的段落块（如 <p>...</p> 等块级元素）。
        每个段落块在原文中占据一个连续的行范围，翻译时将整体替换。
        返回 list[dict]，每个 dict 包含:
          - start_line_idx: 起始行号 (0-indexed，包含)
          - end_line_idx: 结束行号 (0-indexed，包含)
          - text: 完整原文（含换行符）
          - tag_mapping: 空字典（保留兼容）
        """
        lines = html_string.splitlines(keepends=True)
        blocks = []

        # 块级标签（通常不会嵌套自身，或嵌套场景简单）
        # text: EPUB2 toc.ncx 中的 <text> 条目, 含可翻译的章节标题
        BLOCK_TAG_PATTERNS = [
            r'p', r'h[1-6]', r'li', r'blockquote', r'figcaption',
            r'dt', r'dd', r'summary', r'pre', r'text'
        ]

        i = 0
        while i < len(lines):
            line = lines[i]
            matched = False

            for tag_pattern in BLOCK_TAG_PATTERNS:
                open_re = re.compile(rf'<({tag_pattern})(?:\s+[^>]*)?>', re.IGNORECASE)
                open_match = open_re.search(line)
                if not open_match:
                    continue

                tag_name = open_match.group(1).lower()
                close_re = re.compile(rf'</{re.escape(tag_name)}\s*>', re.IGNORECASE)

                # 同一行内已闭合
                if close_re.search(line):
                    if self.line_has_text(line):
                        blocks.append({
                            'start_line_idx': i,
                            'end_line_idx': i,
                            'text': line,
                            'tag_mapping': {},
                        })
                    matched = True
                    break

                # 跨多行查找闭标签
                block_lines = [line]
                j = i + 1
                found_close = False
                while j < len(lines):
                    block_lines.append(lines[j])
                    if close_re.search(lines[j]):
                        found_close = True
                        break
                    j += 1

                if found_close:
                    text = ''.join(block_lines)
                    if self.line_has_text(text):
                        blocks.append({
                            'start_line_idx': i,
                            'end_line_idx': j,
                            'text': text,
                            'tag_mapping': {},
                        })
                    i = j  # 跳到结束行
                    matched = True
                    break

            if matched:
                i += 1
                continue

            # 未被块级标签捕获，但含有文本的行（裸文本）
            if self.line_has_text(line):
                blocks.append({
                    'start_line_idx': i,
                    'end_line_idx': i,
                    'text': line,
                    'tag_mapping': {},
                })

            i += 1

        # 去重/防嵌套：保留范围更小的内层块，丢弃外层重叠块
        blocks.sort(key=lambda b: (b['start_line_idx'], b['end_line_idx']))
        filtered = []
        for b in blocks:
            overlap = False
            for existing in filtered:
                if not (b['end_line_idx'] < existing['start_line_idx'] or
                        b['start_line_idx'] > existing['end_line_idx']):
                    # 有重叠，若 b 范围更大或相等，则丢弃 b
                    if (b['end_line_idx'] - b['start_line_idx']) >= (existing['end_line_idx'] - existing['start_line_idx']):
                        overlap = True
                        break
            if not overlap:
                filtered.append(b)

        return filtered

    # ──────────────────────────────────────────────
    #  核心：不再简化标签
    # ──────────────────────────────────────────────

    def extract_and_simplify(self, line):
        """
        在直接模式中，我们不进行标签简化。
        只提取缩进和尾部空白。（已弃用，保留兼容）
        """
        indent_m = re.match(r'^(\s*)', line)
        indent = indent_m.group(1) if indent_m else ""
        trailing_m = re.search(r'(\s*)$', line)
        trailing = trailing_m.group(1) if trailing_m else ""
        clean_text = line.strip()
        return clean_text, {}, indent, trailing

    # ──────────────────────────────────────────────
    #  核心：还原 (回填) —— 整块替换模式下不再使用
    # ──────────────────────────────────────────────

    def restore_line(self, translated_text, tag_mapping, indent, trailing):
        """
        在直接模式中，不进行任何标签替换。直接拼接缩进、翻译后的文本和尾部空白。
        （整块替换模式下已弃用，保留兼容）
        """
        if not translated_text:
            return ""
        return indent + translated_text + trailing

    # ──────────────────────────────────────────────
    #  分组与 AI 提示格式
    # ──────────────────────────────────────────────

    def format_for_ai(self, group_blocks):
        """将一组块格式化为 AI 提示格式（直接拼接，不加任何 <n> 标签）"""
        lines = []
        for block in group_blocks:
            lines.append(block.get('text', block.get('simplified', '')))
        return "\n".join(lines)

    def check_anchor_format(self, text, expected_count):
        """
        在直接模式下，不需要进行严格的格式检验。
        """
        return "ok"

    @staticmethod
    def clean_markdown_code_blocks(response_text):
        """过滤掉 markdown 代码块标记，返回纯文本。"""
        lines = response_text.split('\n')
        cleaned = []
        in_code_block = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('```'):
                in_code_block = not in_code_block
                continue
            cleaned.append(line)
        return '\n'.join(cleaned).strip()

    def validate_and_parse_response(self, response_text, original_group, auto_repair=False):
        """
        整块替换模式：不再按行拆分对齐。
        直接返回清洗后的整块翻译文本。
        """
        cleaned = self.clean_markdown_code_blocks(response_text)
        return [cleaned], True

    # ──────────────────────────────────────────────
    #  便捷兼容接口
    # ──────────────────────────────────────────────

    def create_blocks_from_html(self, html_string, start_global_idx=0, file_rel_path=None):
        """
        从 HTML 文件内容提取所有段落块，返回 block 列表。
        每个 block 包含 start_line_idx, end_line_idx, text, tag_mapping, global_idx, file_rel_path。
        """
        blocks = self.extract_paragraph_blocks(html_string)
        for i, b in enumerate(blocks):
            b['global_idx'] = start_global_idx + i
            # 为兼容旧接口保留字段
            b['text'] = b['text']
            b['formats'] = b['tag_mapping']
            b['file_rel_path'] = file_rel_path
        return blocks
