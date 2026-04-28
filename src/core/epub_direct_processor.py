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
    2. 以"行"为最小提取单位。
    3. 不生成 `<t1>` 等简化标签，保持原样。
    4. 不使用 `<1>...</1>` 包装发送给 AI，而是直接拼接多行。
    5. 返回的结果将直接覆盖当前块的第一行，其余行置空。
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

    def extract_lines(self, html_string):
        """
        从 HTML 字符串中提取所有含有可翻译文本的行。
        返回 list[dict]，每个 dict 包含:
          - line_idx: 原始行号 (0-indexed)
          - orig_line: 原始行内容（含换行符）
          - simplified: 简化后的行内容（在直接模式下就是去掉首尾空格的原始HTML）
          - tag_mapping: 空字典（不再需要）
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
    #  核心：不再简化标签
    # ──────────────────────────────────────────────

    def extract_and_simplify(self, line):
        """
        在直接模式中，我们不进行标签简化。
        只提取缩进和尾部空白。
        """
        indent_m = re.match(r'^(\s*)', line)
        indent = indent_m.group(1) if indent_m else ""
        trailing_m = re.search(r'(\s*)$', line)
        trailing = trailing_m.group(1) if trailing_m else ""
        clean_text = line.strip()

        return clean_text, {}, indent, trailing

    # ──────────────────────────────────────────────
    #  核心：还原 (回填)
    # ──────────────────────────────────────────────

    def restore_line(self, translated_text, tag_mapping, indent, trailing):
        """
        在直接模式中，不进行任何标签替换。直接拼接缩进、翻译后的文本和尾部空白。
        """
        # 如果 translated_text 是空的，就不要加 indent 和 trailing 了，避免多出空行
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
            lines.append(block['simplified'])
        return "\n".join(lines)

    def check_anchor_format(self, text, expected_count):
        """
        在直接模式下，我们不需要进行任何格式检验。
        """
        return "ok"

    def validate_and_parse_response(self, response_text, original_group, auto_repair=False):
        """
        在直接模式中，我们逐行提取文本，发送给 AI 的也是多行文本。
        预期 AI 返回的行数与发送的行数一致。我们通过按行拆分来一对一回填。
        如果行数不一致，我们会尽可能对齐。
        """
        expected_len = len(original_group)
        if expected_len == 0:
            return [], False
            
        # 拆分并去除纯空行（因为原文件中含有文本的行绝不会是空行）
        # 如果模型输出了 markdown 代码块 ```html，我们也要过滤掉
        lines = []
        for line in response_text.split('\n'):
            line = line.strip()
            if not line:
                continue
            if line.startswith('```'):
                continue
            lines.append(line)
            
        translated_texts = lines[:expected_len]
        
        # 如果模型返回的行数较少，缺少的部分只能留空或保留原文
        while len(translated_texts) < expected_len:
            translated_texts.append(original_group[len(translated_texts)]['text'])
            
        # 如果模型返回的行数过多，将多余的行追加到最后一行
        if len(lines) > expected_len:
            extra = " ".join(lines[expected_len:])
            translated_texts[-1] += " " + extra
            
        # 在直接模式下，我们总是视作成功 (True)，不阻断流程
        return translated_texts, True

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
