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

                # 检查 run 内部的特殊子节点 (br, tab 等)
                inner_parts = []
                # 注意：我们不能只查找 t，因为 br/tab 也是 run 的子节点且有序
                for child in node.children:
                    if not hasattr(child, 'name') or not child.name:
                        continue
                    
                    cname = child.name.split(':')[-1] if ':' in child.name else child.name
                    if cname == 't':
                        inner_parts.append(child.get_text().replace('<', '&lt;').replace('>', '&gt;'))
                    elif cname in ['br', 'tab', 'cr']:
                        # --- Monolithic Tag Handling ---
                        delim = self.get_inner_delimiters(local_counter[0])[0]
                        local_counter[0] += 1
                        format_tags.append({
                            'id': delim,
                            'tag': cname,
                            'type': 'monolithic',
                            'node': child
                        })
                        inner_parts.append(f"{delim}{delim}")
                
                content = "".join(inner_parts)
                if content:
                    # 如果内容仅由单体标签组成，且原本是单体，则不需要包裹
                    # 但为了对称性，统一使用包裹
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

        full_text = recursive_extract(element).strip()
        
        # --- 优化逻辑：折叠标签 (Tag Folding) ---
        folded_formats = []
        delims_chars = "".join(self.INNER_DELIMS)
        
        changed = True
        while changed:
            changed = False
            # 1. 检查开头的纯单点/空标签 (如空锚点)
            if full_text and full_text[0] in delims_chars:
                char = full_text[0]
                tag_idx = -1
                for idx, fmt in enumerate(format_tags):
                    if fmt['id'] == char:
                        tag_idx = idx
                        break
                
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

            # 2. 检查结尾的纯单点标签
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
        
        for fmt in folded_formats:
            fmt['is_folded'] = True
            format_tags.append(fmt)

        # 终极净化：将内部所有空白字符集（换行、制表符、连续空格）合并为一个空格，模拟浏览器渲染效果
        full_text = re.sub(r'\s+', ' ', full_text).strip()

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
            # 加上 Unicode 空白 \u00A0
            clean_text = re.sub(r'[\u2A40-\u2AA3\u2B40-\u2BA3\s\u00A0]', '', text)
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

    def restore_xml(self, original_block, translated_text, soup):
        """
        [手术式还原] 直接修改 original_block['element'] 内部已有的 run 节点。
        """
        # 分离折叠标签和非折叠标签
        node_map = {f['id']: f['node'] for f in original_block['formats'] if not f.get('is_folded')}
        folded_tags = [f for f in original_block['formats'] if f.get('is_folded')]
        
        # 识别所有 INNER_DELIMS 中的字符
        delims_chars = "".join(self.INNER_DELIMS)
        
        # 1. 处理非折叠(块内)部分
        i = 0
        while i < len(translated_text):
            char = translated_text[i]
            if char in delims_chars and char in node_map:
                # 识别标签类型
                fmt = None
                for f in original_block['formats']:
                    if f['id'] == char:
                        fmt = f
                        break
                
                if fmt and fmt.get('type') == 'monolithic':
                    # 消耗成对字符
                    if i + 1 < len(translated_text) and translated_text[i+1] == char:
                        i += 2
                    else:
                        i += 1
                    continue

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
        
        # 2. 处理折叠标签 (Prefix/Suffix/Wrap)
        # 对于 DOCX，由于 element (w:p) 内部的节点顺序很重要，
        # 我们需要根据 fold_type 重新调整节点在 element 里的位置
        
        for fmt in reversed(folded_tags):
            ftype = fmt.get('fold_type')
            run_node = fmt['node']
            
            if ftype == 'prefix':
                # 将节点移动到开头
                original_block['element'].insert(0, run_node)
            elif ftype == 'suffix':
                # 将节点移动到末尾
                original_block['element'].append(run_node)
            elif ftype == 'wrap':
                # 对于 DOCX，Wrap 通常意味着这个 Paragraph 内部只有一个主要的 Run，
                # 或者本来包裹着。在这种情况下，核心内容已经更新了，我们可以确保它在 element 中。
                # 除非被之前的 prefix/suffix 挤开了。
                # 实际上 DOCX 中 Wrap 的概念较少，除非是特殊的结构。
                # 这里我们只需确保它是 element 的子节点（已在那儿了）。
                pass

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
