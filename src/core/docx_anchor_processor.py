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
        
        # 稀有 Unicode 符号标记 (与 EPUB 保持一致)
        self.GS = "⟬" # Group Start
        self.GE = "⟭" # Group End
        self.AS = "⦗" # Anchor Start
        self.AE = "⦘" # Anchor End
        
        # 内部标签使用的括号
        self.TS = "⟦" 
        self.TE = "⟧"
        
        # 块级分隔符池
        self.BLOCK_DELIMS = "⧖⧗⧘⧙⧚⧛⧜⧝⧞⧟⨀⨁⨂⨃⨄⨅⨆⨇⨈⨉⨊⨋⨌⨍⨎⨏⨐⨑⨒⨓⨔⨕⨖⨗⨘⨙⨚⨛⨜⨝⨞⨟"

    def get_block_delimiters(self, index):
        char = self.BLOCK_DELIMS[index % len(self.BLOCK_DELIMS)]
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
        核心逻辑：提取 DOCX 段落内容，将格式运行 <w:r> 转化为带编号的锚点。
        """
        format_tags = []
        local_counter = [1]

        def recursive_extract(node):
            if node.name == 't': # w:t 标签
                return node.get_text().replace('<', '&lt;').replace('>', '&gt;')
            
            if node.name == 'r': # w:r 标签 (Run)
                # 核心改进：为每一个 run 分配一个唯一 ID，确保 1:1 映射
                tag_id = f"{self.AS}{local_counter[0]}{self.AE}"
                local_counter[0] += 1
                
                tag_info = {
                    'id': tag_id,
                    'tag': 'r',
                    'type': 'run'
                }
                if include_nodes:
                    tag_info['node'] = node # 仅在还原阶段需要内存引用
                format_tags.append(tag_info)

                t_node = node.find('t', recursive=False)
                if t_node:
                    inner_text = t_node.get_text().replace('<', '&lt;').replace('>', '&gt;')
                    return f"{self.TS}{inner_text}{self.TE}{tag_id}"
                else:
                    return tag_id
                
            # 处理其他子节点 (如 w:p 中的特殊标签)
            child_parts = []
            if hasattr(node, 'children'):
                for child in node.children:
                    if hasattr(child, 'name') and child.name:
                        child_parts.append(recursive_extract(child))
            return "".join(child_parts)

        full_text = recursive_extract(element)
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
            if not text.strip():
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
                'size': len(text),
                'global_idx': idx
            })
        return blocks

    def format_for_ai(self, group_blocks):
        """同 EPUB"""
        lines = [self.GS]
        for i, block in enumerate(group_blocks):
            ds, de = self.get_block_delimiters(i)
            lines.append(f"{ds}{block['text']}{de}")
        lines.append(self.GE)
        return "\n".join(lines)

    def validate_and_parse_response(self, response_text, original_group):
        """
        [彻底移除结构校验] 宽容解析：不再校验锚点一致性或符号闭合。
        """
        # 1. 尝试提取 ⟬ ⟭ 内部内容
        pattern = re.escape(self.GS) + r'([\s\S]*)' + re.escape(self.GE)
        group_match = re.search(pattern, response_text)
        if group_match:
            content = group_match.group(1).strip()
        else:
            content = response_text.strip()
            
        translated_texts = []
        last_pos = 0
        
        # 2. 按顺序提取块
        for i in range(len(original_group)):
            ds, de = self.get_block_delimiters(i)
            block_pattern = re.escape(ds) + r'(.*?)' + re.escape(de)
            match = re.search(block_pattern, content[last_pos:], re.DOTALL)
            
            if match:
                block_text = match.group(1).strip()
                translated_texts.append(block_text)
                last_pos += match.end()
            else:
                # 容错：追加原文保持对齐
                translated_texts.append(original_group[i]['text'])
        
        return translated_texts, True

    def restore_xml(self, original_block, translated_text, soup):
        """
        [最可靠方案] 手术式还原：直接修改 original_block['element'] 内部已有的 run 节点。
        不再清空或重建 XML 树，只更新文本内容。
        """
        # 建立 ID 到原有 run 节点的映射
        # original_block['formats'] 包含了提取时记录的节点引用
        node_map = {}
        for f in original_block['formats']:
            num_match = re.search(r'(\d+)', f['id'])
            if num_match:
                node_map[int(num_match.group(1))] = f['node']

        # 解析翻译后的文本，按顺序提取出每个锚点对应的文字
        # 我们寻找 ⟦...⟧⦗n⦘ 结构
        pattern = re.escape(self.TS) + r'(.*?)' + re.escape(self.TE) + re.escape(self.AS) + r'(\d+)' + re.escape(self.AE)
        matches = list(re.finditer(pattern, translated_text))
        
        # 记录哪些节点已被更新，用于处理那些没有文字但有 ID 的节点（如 w:br）
        updated_ids = set()
        
        for m in matches:
            trans_inner = m.group(1)
            node_id = int(m.group(2))
            
            if node_id in node_map:
                run_node = node_map[node_id]
                # 找到该 run 下的 w:t (或是 t)
                t_node = run_node.find(['t', 'w:t'])
                if t_node:
                    t_node.string = trans_inner
                else:
                    # 如果原本没有 t 节点但现在翻译出了文字，则创建一个
                    new_t = soup.new_tag('w:t')
                    new_t['xml:space'] = 'preserve'
                    new_t.string = trans_inner
                    run_node.append(new_t)
                updated_ids.add(node_id)
        
        # 处理可能的“孤儿”锚点（即没有翻译出 ⟦⟧ 的锚点，或者纯 ID 锚点）
        # 只要 ID 在翻译文本中出现，说明它被保留了
        solo_pattern = re.escape(self.AS) + r'(\d+)' + re.escape(self.AE)
        for m in re.finditer(solo_pattern, translated_text):
            node_id = int(m.group(1))
            if node_id not in updated_ids and node_id in node_map:
                # 这种节点由于没有包围 ⟦⟧，意味着它是不可翻译节点（如 w:br）
                # 只要它在译文中出现了，我们就保持其原本在 XML tree 中的位置
                # 由于我们根本没有清空 original_block['element']，所以它本身就在那里
                pass

        # 这个方案最强大的一点在于：我们根本不需要做任何重建工作。
        # original_block['element'] 是 BeautifulSoup 中原始 XML 树的一个节点。
        # 我们在提取时记录了它的子节点引用，现在直接通过这些引用修改了它们的内容。
        # 整个文档的结构、命名空间、段落属性完全没动。

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
