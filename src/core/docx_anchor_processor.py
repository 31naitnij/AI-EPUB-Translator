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
        """获取组内第 index 个块的分隔符 (使用 [[n]] 格式)"""
        tag = f"[[{index+1}]]"
        return tag, tag

    def get_inner_delimiters(self, index):
        """获取 DOCX 块内第 index 个标签的分隔符 (使用 ((A)) 格式)"""
        res = ""
        temp = index
        while temp >= 0:
            res = chr(65 + (temp % 26)) + res
            temp = (temp // 26) - 1
        tag = f"(({res}))"
        return tag, tag

    def extract_docx(self, docx_path, callback=None):
        """将 DOCX 完整解压到临时目录"""
        if callback: callback("正在解压 DOCX 文件...")
        self.temp_dir = tempfile.mkdtemp(prefix="docx_trans_")
        with zipfile.ZipFile(docx_path, 'r') as zip_ref:
            zip_ref.extractall(self.temp_dir)
        return self.temp_dir

    def get_xml_files(self):
        """返回 DOCX 中所有包含可能文本内容的 XML 文件 (文档、页眉页脚、注脚、页注、文本框、评论以及词汇表内容)"""
        content_files = []
        word_dir = os.path.join(self.temp_dir, 'word')
        
        if not os.path.exists(word_dir):
            return []

        # 扫描 word/ 目录及其子项目 (如 glossary/)
        for root, dirs, files in os.walk(word_dir):
            for f in files:
                if f.endswith('.xml'):
                    # 匹配主要的文本承载文件
                    if f.startswith(('document', 'header', 'footer', 'footnotes', 'endnotes', 'comments')):
                        content_files.append(os.path.join(root, f))
        
        # 强制排序，确保 document.xml 在最前面（如果有的话），其余按字典序
        content_files.sort(key=lambda x: (not os.path.basename(x).startswith('document'), x))
        return content_files

    def extract_block_with_local_ids(self, element_or_nodes, include_nodes=False):
        """
        核心逻辑：对一个段落片段进行深度折叠和提取。
        支持传入 Element 或 Node List。
        """
        if hasattr(element_or_nodes, 'contents'):
            nodes_list = element_or_nodes.contents
        else:
            nodes_list = element_or_nodes if isinstance(element_or_nodes, list) else [element_or_nodes]

        format_tags = []
        content = "".join(str(n) for n in nodes_list).strip()
        
        while True:
            dummy_xml = f'<root xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">{content}</root>'
            temp_soup = BeautifulSoup(dummy_xml, 'xml')
            all_nodes = [c for c in temp_soup.root.contents if not (isinstance(c, str) and not c.strip())]
            
            if not all_nodes:
                break
            
            changed = False
            # 1. 前缀/后缀折叠 (Prefix/Suffix Folding) - 无文字的结构化标签 (w:rPr, w:proofErr, w:bookmarkStart etc)
            if all_nodes and all_nodes[0].name and not all_nodes[0].get_text(strip=True):
                node = all_nodes[0]
                tag_name = f"{node.prefix}:{node.name}" if node.prefix else node.name
                format_tags.append({
                    'tag': tag_name,
                    'attrs': dict(node.attrs),
                    'content': str(node.decode_contents()) if node.contents else "",
                    'is_folded': True,
                    'fold_type': 'prefix'
                })
                del all_nodes[0]
                content = "".join(str(n) for n in all_nodes)
                changed = True
            elif all_nodes and all_nodes[-1].name and not all_nodes[-1].get_text(strip=True):
                node = all_nodes[-1]
                tag_name = f"{node.prefix}:{node.name}" if node.prefix else node.name
                format_tags.append({
                    'tag': tag_name,
                    'attrs': dict(node.attrs),
                    'content': str(node.decode_contents()) if node.contents else "",
                    'is_folded': True,
                    'fold_type': 'suffix'
                })
                del all_nodes[-1]
                content = "".join(str(n) for n in all_nodes)
                changed = True
            # 2. 包裹折叠 (Wrapping Folding) - 单个容器包裹文本 (w:r, w:t, w:pPr etc)
            elif len(all_nodes) == 1 and all_nodes[0].name:
                node = all_nodes[0]
                tag_name = f"{node.prefix}:{node.name}" if node.prefix else node.name
                # 为了去噪，大部分 DOCX 容器 (r, t) 都应该折叠
                format_tags.append({
                    'tag': tag_name,
                    'attrs': dict(node.attrs),
                    'is_folded': True,
                    'fold_type': 'wrap'
                })
                content = "".join(str(c) for c in node.contents).strip()
                changed = True
            
            if not changed:
                break

        # 处理内部锚点
        dummy_xml = f'<root xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">{content}</root>'
        temp_soup = BeautifulSoup(dummy_xml, 'xml')
        local_counter = [0]
        
        def recursive_extract(node):
            if isinstance(node, str):
                return node.replace('<', '&lt;').replace('>', '&gt;')
            
            if node.name:
                # 特殊处理：透明容器 (w:t) 永远不产生锚点
                if node.name == 't':
                    return "".join(recursive_extract(c) for c in node.children)
                
                # 如果是 w:r 且只包含 w:rPr 和一个 w:t (或一段文字)
                # 我们可以尝试透明化处理，但为了稳妥，暂且只在 recursive_extract 中合并属性
                
                child_parts = []
                props = []
                for child in node.children:
                    if hasattr(child, 'name') and child.name in ['rPr', 'pPr', 'proofErr']:
                        # 将这些属性标签特殊记录，而不产生锚点
                        props.append({
                            'tag': f"{child.prefix}:{child.name}" if child.prefix else child.name,
                            'attrs': dict(child.attrs),
                            'content': str(child.decode_contents()) if child.contents else ""
                        })
                    else:
                        child_parts.append(recursive_extract(child))
                
                inner_text = "".join(child_parts)
                
                # 如果是 w:r 且提取后只有纯文本（无内部锚点），且我们可以将其透明化
                if node.name == 'r' and '⟬' not in inner_text and not props:
                     return inner_text

                delim = self.get_inner_delimiters(local_counter[0])[0]
                local_counter[0] += 1
                tag_name = f"{node.prefix}:{node.name}" if node.prefix else node.name
                
                format_tags.append({
                    'id': delim,
                    'tag': tag_name,
                    'attrs': dict(node.attrs),
                    'type': 'container',
                    'is_internal': True,
                    'inner_props': props  # 这里存储合并的属性
                })
                return f"{delim}{inner_text}{delim}"
            return ""

        final_parts = []
        if temp_soup.root:
            for child in temp_soup.root.contents:
                final_parts.append(recursive_extract(child))
            
        full_text = "".join(final_parts)
        # 更加谨慎地处理空白
        # full_text = re.sub(r'\s+', ' ', full_text).strip()
        
        return full_text, format_tags

    def extract_block_with_local_ids_legacy(self, element, include_nodes=False):
        """
        [旧版保留供参考] 以前将 run 转化为锚点的逻辑。
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
                    return f"{delim}{delim}"
                
            # 处理其他子节点 (如 w:p 中的特殊标签如 w:br, w:tab)
            child_parts = []
            if hasattr(node, 'children'):
                for child in node.children:
                    if hasattr(child, 'name') and child.name:
                        child_parts.append(recursive_extract(child))
            return "".join(child_parts)

        full_text = recursive_extract(element).strip()
        # 终极净化：折叠所有空白字符为单个空格，彻底解决换行导致的统计错误
        full_text = re.sub(r'\s+', ' ', full_text).strip()
        
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

    def normalize_paragraph_breaks(self, p, soup):
        """
        深度平衡逻辑：
        如果 w:r 内部包含 w:br, w:cr, w:tab，则将该 w:r 拆分为多个 w:r，
        确保 breaking tags 最终成为 w:p 的直接子节点。
        """
        import copy
        changed = True
        while changed:
            changed = False
            for child in list(p.children):
                if not hasattr(child, 'name') or not child.name:
                    continue
                
                cname = child.name.split(':')[-1] if ':' in child.name else child.name
                if cname in ['r', 'hyperlink', 'ins', 'sdt']: # 可能包含内容的容器
                    # 检查其子节点是否有 break
                    inner_nodes = list(child.children)
                    break_idx = -1
                    for i, inner in enumerate(inner_nodes):
                        iname = inner.name.split(':')[-1] if inner.name and ':' in inner.name else inner.name
                        if iname in ['br', 'cr', 'tab']:
                            break_idx = i
                            break
                    
                    if break_idx != -1:
                        # 发现内部 break，进行拆分
                        # 1. 提取并移除该 child
                        idx = p.contents.index(child)
                        child.extract()
                        
                        # 2. 分割为: [前部节点] + [Break节点] + [后部节点]
                        before_nodes = inner_nodes[:break_idx]
                        break_node = inner_nodes[break_idx]
                        after_nodes = inner_nodes[break_idx+1:]
                        
                        # 3. 按序插回 p
                        insert_pos = idx
                        if before_nodes:
                            new_before = copy.copy(child)
                            new_before.clear()
                            for n in before_nodes: new_before.append(copy.copy(n))
                            p.insert(insert_pos, new_before)
                            insert_pos += 1
                        
                        p.insert(insert_pos, copy.copy(break_node))
                        insert_pos += 1
                        
                        if after_nodes:
                            new_after = copy.copy(child)
                            new_after.clear()
                            for n in after_nodes: new_after.append(copy.copy(n))
                            p.insert(insert_pos, new_after)
                        
                        changed = True
                        break

    def create_blocks_from_soup(self, soup, include_nodes=False, start_global_idx=0):
        """
        从 DOCX XML 中提取翻译块 (主要是 w:p)。
        支持段落切分：遇到 w:br, w:cr, w:tab 时将段落切分为多个块。
        """
        blocks = []
        paragraphs = soup.find_all(['p', 'w:p'])
        
        for p in paragraphs:
            # 预处理：将嵌套的 break 提升至顶层
            self.normalize_paragraph_breaks(p, soup)

            # 基础打标
            if p.has_attr('data-trans-idx'):
                p_idx_base = p['data-trans-idx']
            else:
                p_idx_base = f"p{start_global_idx + len(blocks)}"
                p['data-trans-idx'] = p_idx_base

            # 执行切分逻辑 (此时 break 已在顶层)
            segments = []
            current_nodes = []
            for child in p.children:
                cname = child.name.split(':')[-1] if child.name and ':' in child.name else child.name
                if cname in ['br', 'cr', 'tab']:
                    if current_nodes:
                        segments.append(current_nodes)
                        current_nodes = []
                    segments.append(child)
                else:
                    current_nodes.append(child)
            if current_nodes:
                segments.append(current_nodes)

            # 过滤并转化为块
            seg_idx = 0
            for seg in segments:
                if isinstance(seg, list):
                    # 这是一个内容片段
                    text, formats = self.extract_block_with_local_ids(seg, include_nodes=include_nodes)
                    
                    # 净化：去除锚点和空白后如果为空，则不作为翻译块（但保留在 XML 中）
                    clean_text = re.sub(r'[\u2A40-\u2AA3\u2B40-\u2BA3\s\u00A0]', '', text)
                    if not clean_text:
                        seg_idx += 1
                        continue
                    
                    global_idx = start_global_idx + len(blocks)
                    blocks.append({
                        'element': p,
                        'segment_idx': seg_idx, 
                        'text': text,
                        'formats': formats,
                        'size': len(clean_text),
                        'global_idx': global_idx,
                        'parent_idx': p_idx_base # 保存父级 ID 为后续映射使用
                    })
                seg_idx += 1
                
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
            # 匹配 [[n]]...[[n]] 格式
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

    def restore_xml(self, original_block, translated_text, soup):
        """
        [手术式还原] 将翻译后的片段还原回其父段落的对应位置。
        """
        p = original_block['element']
        seg_idx_to_restore = original_block.get('segment_idx', 0)
        format_tags = original_block.get('formats', [])
        
        # 1. 重新切分当前 P 标签的节点，定位到要替换的节点集
        segment_map = []
        current_nodes = []
        for child in p.children:
            cname = child.name.split(':')[-1] if child.name and ':' in child.name else child.name
            if cname in ['br', 'cr', 'tab']:
                if current_nodes:
                    segment_map.append(('nodes', current_nodes))
                    current_nodes = []
                segment_map.append(('separator', [child]))
            else:
                current_nodes.append(child)
        if current_nodes:
            segment_map.append(('nodes', current_nodes))
            
        if seg_idx_to_restore >= len(segment_map):
            return 

        target_type, old_nodes = segment_map[seg_idx_to_restore]
        if target_type != 'nodes':
            return

        # 2. 构造翻译后的 XML 片段
        internal_anchors = [f for f in format_tags if f.get('is_internal')]
        folded_tags = [f for f in format_tags if f.get('is_folded')]
        
        current_xml = translated_text
        internal_anchors.sort(key=lambda x: len(x['id']), reverse=True)
        
        for fmt in internal_anchors:
            delim = fmt['id']
            tag = fmt['tag']
            parts = current_xml.split(delim)
            if len(parts) >= 3:
                new_parts = [parts[0]]
                for i in range(1, len(parts) - 1, 2):
                    content = parts[i]
                    
                    # 核心改进：还原被吸收的属性标签 (w:rPr, w:pPr etc)
                    inner_props_xml = ""
                    for p_fmt in fmt.get('inner_props', []):
                        p_attrs_str = " ".join([f'{k}="{v}"' for k, v in p_fmt['attrs'].items()])
                        p_tag = p_fmt['tag']
                        p_content = p_fmt.get('content', "")
                        inner_props_xml += f"<{p_tag} {p_attrs_str}>{p_content}</{p_tag}>"
                    
                    content = inner_props_xml + content

                    # DOCX 特有：w:r 内部的文字必须包裹在 w:t 中 (逻辑已移至最后的 wrap_naked_text)
                    # 此处不再做简单的字符串包裹，交给最后的 BeautifulSoup 处理更稳妥
                    
                    start_t = f"<{tag}"
                    for k, v in fmt['attrs'].items():
                        start_t += f' {k}="{v}"'
                    start_t += ">"
                    new_parts.append(start_t + content + f"</{tag}>")
                    new_parts.append(parts[i+1])
                current_xml = "".join(new_parts)

        # 应用折叠标签
        import copy
        for fmt in reversed(folded_tags):
            ftype = fmt.get('fold_type', 'wrap')
            new_tag = soup.new_tag(fmt['tag'])
            for k, v in fmt['attrs'].items():
                new_tag[k] = v
            
            # 还原内部内容 (针对前缀/后缀折叠的属性标签)
            inner_content = fmt.get('content', "")
            if inner_content:
                inner_dummy = f'<root xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">{inner_content}</root>'
                inner_soup = BeautifulSoup(inner_dummy, 'xml')
                if inner_soup.root:
                    for node in list(inner_soup.root.contents):
                        new_tag.append(copy.copy(node))

            if ftype == 'wrap':
                dummy_xml = f'<root xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">{current_xml}</root>'
                inner_soup = BeautifulSoup(dummy_xml, 'xml')
                if inner_soup.root:
                    for node in list(inner_soup.root.contents):
                        new_tag.append(copy.copy(node))
                current_xml = str(new_tag)
            elif ftype == 'prefix':
                current_xml = str(new_tag) + current_xml
            elif ftype == 'suffix':
                current_xml = current_xml + str(new_tag)

        # 3. 将 current_xml 转化为节点并插入到 P 中正确的位置
        # 注意：必须包含命名空间声明，否则 BeautifulSoup 可能会丢失 w: 前缀
        ns_decl = ' xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        final_dummy = f'<root{ns_decl}>{current_xml}</root>'
        final_soup = BeautifulSoup(final_dummy, 'xml')
        
        # 核心增强：DOCX 绝不允许 naked text
        def wrap_naked_text(parent):
            # 获取副本，因为我们在循环中修改 contents
            contents = list(parent.contents)
            for node in contents:
                if isinstance(node, str) and node.strip():
                    # 在段落级别 (root) 包裹为 w:r/w:t
                    if parent.name == 'root':
                        new_r = final_soup.new_tag("w:r")
                        new_t = final_soup.new_tag("w:t")
                        new_t.string = node
                        new_r.append(new_t)
                        node.replace_with(new_r)
                    # 在 Run 级别包裹为 w:t
                    elif parent.name.endswith(':r') or parent.name == 'r':
                        new_t = final_soup.new_tag("w:t")
                        new_t.string = node
                        node.replace_with(new_t)
                elif hasattr(node, 'children'):
                    wrap_naked_text(node)

        if final_soup.root:
            wrap_naked_text(final_soup.root)
            new_nodes = list(final_soup.root.contents)
        else:
            new_nodes = []

        # 找到 old_nodes 中第一个节点在 p.contents 中的位置
        try:
            first_old_node = old_nodes[0]
            # BeautifulSoup 节点比较使用 ID 或者直接比较
            # 找到索引
            idx = -1
            for i, child in enumerate(p.contents):
                if child is first_old_node:
                    idx = i
                    break
            
            if idx != -1:
                # 移除旧节点
                for node in old_nodes:
                    node.extract()
                # 插入新节点
                for i, node in enumerate(new_nodes):
                    p.insert(idx + i, copy.copy(node))
        except Exception as e:
            print(f"Restore segment error: {e}")

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
