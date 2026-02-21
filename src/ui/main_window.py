from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QPushButton, QTextEdit, 
                             QComboBox, QFileDialog, QSplitter, QProgressBar,
                             QMessageBox, QGroupBox, QSpinBox, QDoubleSpinBox,
                             QTableWidget, QTableWidgetItem, QHeaderView, 
                             QAbstractItemView, QCheckBox, QPlainTextEdit, QApplication)
from PySide6.QtCore import Qt, QThread, Signal, QCoreApplication, QRect, QSize
from PySide6.QtGui import QFont, QIcon, QPainter, QColor, QTextFormat, QSyntaxHighlighter, QTextCharFormat
import os
import sys
import shutil
import time
import re

from src.core.config_manager import ConfigManager
from src.core.translator import Translator
from src.core.processor import Processor

class SymbolHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.block_format = QTextCharFormat()
        self.block_format.setForeground(QColor("#0055ff")) # 蓝色
        self.block_format.setFontWeight(QFont.Bold)

        self.anchor_format = QTextCharFormat()
        self.anchor_format.setForeground(QColor("#008800")) # 绿色
        self.anchor_format.setFontWeight(QFont.Bold)

        self.error_format = QTextCharFormat()
        self.error_format.setBackground(QColor("#ffcccc")) # 浅红背景
        self.error_format.setUnderlineStyle(QTextCharFormat.SpellCheckUnderline)
        self.error_format.setUnderlineColor(QColor("red"))

    def highlightBlock(self, text):
        # 1. 高亮 [[n]] 块标记，并检查对称性（每行应恰好有一对）
        blocks = re.findall(r'\[\[\d+\]\]', text)
        block_counts = {}
        for b in blocks:
            block_counts[b] = block_counts.get(b, 0) + 1

        for match in re.finditer(r'\[\[\d+\]\]', text):
            tag = match.group()
            if block_counts[tag] != 2:
                self.setFormat(match.start(), match.end() - match.start(), self.error_format)
            else:
                self.setFormat(match.start(), match.end() - match.start(), self.block_format)

        # 2. 高亮 ((A)) 锚点标记，并检查对称性（每行应成对出现）
        anchors = re.findall(r'\(\([A-Z0-9]+\)\)', text)
        anchor_counts = {}
        for a in anchors:
            anchor_counts[a] = anchor_counts.get(a, 0) + 1

        for match in re.finditer(r'\(\([A-Z0-9]+\)\)', text):
            tag = match.group()
            if anchor_counts[tag] % 2 != 0:
                # 不对称，显示错误高亮
                self.setFormat(match.start(), match.end() - match.start(), self.error_format)
            else:
                self.setFormat(match.start(), match.end() - match.start(), self.anchor_format)

class TranslationWorker(QThread):
    progress = Signal(int, int, str, str, bool, str) # current_idx, total, orig, trans, is_finished, error_type
    finished = Signal(bool)
    error = Signal(str)

    def __init__(self, processor, translator, epub_path, max_chars, max_workers, interval, target_indices=None):
        super().__init__()
        self.processor = processor
        self.translator = translator
        self.epub_path = epub_path
        self.max_chars = max_chars
        self.max_workers = max_workers
        self.interval = interval
        self.target_indices = target_indices

    def run(self):
        try:
            # Unified process_run for all modes
            # Unified process_run for all modes
            result = self.processor.process_run(
                self.epub_path,
                self.translator,
                max_workers=self.max_workers,
                interval=self.interval,
                callback=self.progress.emit,
                target_indices=self.target_indices
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))

class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.lineNumberAreaWidth(), 0)

    def paintEvent(self, event):
        self.editor.lineNumberAreaPaintEvent(event)

class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.lineNumberArea = LineNumberArea(self)

        self.blockCountChanged.connect(self.updateLineNumberAreaWidth)
        self.updateRequest.connect(self.updateLineNumberArea)
        self.cursorPositionChanged.connect(self.highlightCurrentLine)

        self.updateLineNumberAreaWidth(0)
        self.highlightCurrentLine()

        # 背景色与 premium 质感
        self.setStyleSheet("background-color: #ffffff; border: 1px solid #dcdcdc; border-radius: 4px;")
        
    def lineNumberAreaWidth(self):
        digits = 1
        max_value = max(1, self.blockCount())
        while max_value >= 10:
            max_value /= 10
            digits += 1
        space = 5 + self.fontMetrics().horizontalAdvance('9') * digits
        return space

    def updateLineNumberAreaWidth(self, _):
        self.setViewportMargins(self.lineNumberAreaWidth(), 0, 0, 0)

    def updateLineNumberArea(self, rect, dy):
        if dy:
            self.lineNumberArea.scroll(0, dy)
        else:
            self.lineNumberArea.update(0, rect.y(), self.lineNumberArea.width(), rect.height())

        if rect.contains(self.viewport().rect()):
            self.updateLineNumberAreaWidth(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.lineNumberArea.setGeometry(QRect(cr.left(), cr.top(), self.lineNumberAreaWidth(), cr.height()))

    def highlightCurrentLine(self):
        extraSelections = []
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            lineColor = QColor("#f0faff") # 极浅蓝提示当前行
            selection.format.setBackground(lineColor)
            selection.format.setProperty(QTextFormat.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            extraSelections.append(selection)
        self.setExtraSelections(extraSelections)

    def lineNumberAreaPaintEvent(self, event):
        painter = QPainter(self.lineNumberArea)
        # 绘制行号区背景
        painter.fillRect(event.rect(), QColor("#f8f8f8"))
        
        block = self.firstVisibleBlock()
        blockNumber = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(blockNumber + 1)
                painter.setPen(QColor("#999999")) # 行号颜色
                painter.drawText(0, top, self.lineNumberArea.width() - 2, self.fontMetrics().height(),
                                 Qt.AlignRight, number)

            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            blockNumber += 1

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI 文档翻译工具")
        self.resize(1100, 800)
        self.config_manager = ConfigManager()
        
        self.init_ui()
        self.load_settings_history()
        self._last_ui_update = 0
        self.current_task_indices = None
        self.current_mode = ""

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # 全局垂直分割器
        self.main_splitter = QSplitter(Qt.Vertical)
        
        # --- 1 & 2. 顶部设置区 (路径 + API) ---
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        
        # 路径选择区
        path_group = QGroupBox("文件与路径")
        path_layout = QVBoxLayout(path_group)
        
        epub_layout = QHBoxLayout()
        self.epub_path_edit = QLineEdit()
        self.epub_path_edit.setPlaceholderText("选择 EPUB 文件...")
        btn_browse_epub = QPushButton("选择文件")
        btn_browse_epub.clicked.connect(self.browse_epub)
        epub_layout.addWidget(QLabel("文档文件:"))
        epub_layout.addWidget(self.epub_path_edit)
        epub_layout.addWidget(btn_browse_epub)
        path_layout.addLayout(epub_layout)

        cache_layout = QHBoxLayout()
        self.cache_path_edit = QLineEdit("cache")
        btn_browse_cache = QPushButton("选择文件夹")
        btn_browse_cache.clicked.connect(self.browse_cache)
        cache_layout.addWidget(QLabel("缓存目录:"))
        cache_layout.addWidget(self.cache_path_edit)
        cache_layout.addWidget(btn_browse_cache)
        path_layout.addLayout(cache_layout)

        output_layout = QHBoxLayout()
        self.output_path_edit = QLineEdit("output")
        btn_browse_output = QPushButton("选择文件夹")
        btn_browse_output.clicked.connect(self.browse_output)
        output_layout.addWidget(QLabel("输出目录:"))
        output_layout.addWidget(self.output_path_edit)
        output_layout.addWidget(btn_browse_output)
        path_layout.addLayout(output_layout)
        
        top_layout.addWidget(path_group)

        # API 配置区
        config_group = QGroupBox("API 配置")
        config_layout = QVBoxLayout(config_group)
        row1 = QHBoxLayout()
        self.history_combo = QComboBox()
        self.history_combo.currentIndexChanged.connect(self.on_history_selected)
        row1.addWidget(QLabel("历史:"))
        row1.addWidget(self.history_combo, 2)
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setPlaceholderText("API Key")
        row1.addWidget(QLabel("Key:"))
        row1.addWidget(self.api_key_edit, 2)
        self.api_url_edit = QLineEdit("https://api.openai.com/v1")
        row1.addWidget(QLabel("URL:"))
        row1.addWidget(self.api_url_edit, 3)
        self.model_edit = QLineEdit("gpt-4o")
        row1.addWidget(QLabel("模型:"))
        row1.addWidget(self.model_edit, 1)
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0, 2)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setValue(0.7)
        row1.addWidget(QLabel("温度:"))
        row1.addWidget(self.temp_spin, 0)
        self.chunk_size_spin = QSpinBox()
        self.chunk_size_spin.setRange(100, 10000)
        self.chunk_size_spin.setValue(1000)
        row1.addWidget(QLabel("分块:"))
        row1.addWidget(self.chunk_size_spin, 1)
        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, 10)
        self.concurrency_spin.setValue(1)
        row1.addWidget(QLabel("并发:"))
        row1.addWidget(self.concurrency_spin, 1)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(0, 5000)
        self.interval_spin.setValue(0)
        self.interval_spin.setSuffix("ms")
        row1.addWidget(QLabel("间隔:"))
        row1.addWidget(self.interval_spin, 1)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(5, 300)
        self.timeout_spin.setValue(60)
        self.timeout_spin.setSuffix("s")
        row1.addWidget(QLabel("超时:"))
        row1.addWidget(self.timeout_spin, 1)
        
        config_layout.addLayout(row1)

        prompt_layout = QHBoxLayout()
        from src.config import DEFAULT_PROMPT
        self.prompt_edit = QTextEdit(DEFAULT_PROMPT)
        # 移除固定高度限制，使其可自适应
        self.prompt_edit.setMinimumHeight(40)
        prompt_layout.addWidget(QLabel("Prompt:"))
        prompt_layout.addWidget(self.prompt_edit)
        config_layout.addLayout(prompt_layout)
        top_layout.addWidget(config_group)
        
        self.main_splitter.addWidget(top_widget)

        # --- 3. 中间对照区 (列表 + 左右分栏) ---
        mid_widget = QWidget()
        mid_layout = QVBoxLayout(mid_widget)
        mid_layout.setContentsMargins(0, 0, 0, 0)
        
        # New Mid Splitter: Table (Left) vs Editors (Right)
        self.mid_splitter = QSplitter(Qt.Horizontal)
        
        # Lane 1: Group Table
        group_widget = QWidget()
        group_layout = QVBoxLayout(group_widget)
        group_layout.setContentsMargins(0,0,0,0)
        
        self.group_table = QTableWidget()
        self.group_table.setColumnCount(3)
        self.group_table.setHorizontalHeaderLabels(["ID", "状态", "分组预览"])
        self.group_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.group_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.group_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.group_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.group_table.itemSelectionChanged.connect(self.on_group_selection_changed)
        
        group_layout.addWidget(QLabel("1. 逻辑分组 (API 单元)"))
        
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("筛选:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["全部", "已翻译", "未翻译", "有错误"])
        self.filter_combo.currentIndexChanged.connect(self.apply_table_filter)
        filter_layout.addWidget(self.filter_combo)
        
        filter_layout.addSpacing(15)
        
        filter_layout.addWidget(QLabel("搜索:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("关键词...")
        self.search_edit.textChanged.connect(self.apply_table_filter)
        filter_layout.addWidget(self.search_edit, 1)
        
        self.search_type_combo = QComboBox()
        self.search_type_combo.addItems(["全文搜索", "仅搜索原文", "仅搜索译文"])
        self.search_type_combo.currentIndexChanged.connect(self.apply_table_filter)
        filter_layout.addWidget(self.search_type_combo)
        
        filter_layout.addStretch()
        group_layout.addLayout(filter_layout)
        
        group_layout.addWidget(self.group_table, 1)
        self.mid_splitter.addWidget(group_widget)

        # Lane 2: Block Table
        block_widget = QWidget()
        block_layout = QVBoxLayout(block_widget)
        block_layout.setContentsMargins(0,0,0,0)
        
        self.block_table = QTableWidget()
        self.block_table.setColumnCount(2)
        self.block_table.setHorizontalHeaderLabels(["ID", "内容预览"])
        self.block_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.block_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.block_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        
        block_layout.addWidget(QLabel("2. 组内分块 (段落)"))
        block_layout.addWidget(self.block_table, 1)
        self.mid_splitter.addWidget(block_widget)
        
        editor_widget = QWidget()
        editor_layout = QVBoxLayout(editor_widget)
        editor_layout.setContentsMargins(0,0,0,0)
        editor_layout.addWidget(QLabel("3. 翻译对照 (组级别)"))

        self.editor_splitter = QSplitter(Qt.Horizontal)
        self.orig_text_edit = CodeEditor()
        self.orig_text_edit.setPlaceholderText("API 请求文本 (带锚点)...")
        self.orig_text_edit.setReadOnly(True)
        self.trans_text_edit = CodeEditor()
        self.trans_text_edit.setPlaceholderText("API 响应译文...")
        
        # 应用高亮器
        self.orig_highlighter = SymbolHighlighter(self.orig_text_edit.document())
        self.trans_highlighter = SymbolHighlighter(self.trans_text_edit.document())
        
        self.editor_splitter.addWidget(self.orig_text_edit)
        self.editor_splitter.addWidget(self.trans_text_edit)
        
        editor_layout.addWidget(self.editor_splitter, 1)
        
        self.btn_save_edit = QPushButton("保存组修改")
        self.btn_save_edit.clicked.connect(self.save_manual_edit)
        editor_layout.addWidget(self.btn_save_edit)
        
        self.mid_splitter.addWidget(editor_widget)
        
        # Set stretch: Group 1, Block 1, Editor 2
        self.mid_splitter.setStretchFactor(0, 1)
        self.mid_splitter.setStretchFactor(1, 1)
        self.mid_splitter.setStretchFactor(2, 2)
        
        mid_layout.addWidget(self.mid_splitter)
        
        self.main_splitter.addWidget(mid_widget)

        # --- 4. 底部控制区 ---
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        
        ctrl_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.btn_prepare = QPushButton("分块并分组")
        self.btn_translate_sel = QPushButton("翻译选中组")
        self.btn_start = QPushButton("开始翻译")
        self.btn_stop = QPushButton("停止")
        self.btn_clear_cache = QPushButton("清除缓存")

        self.btn_output = QPushButton("导出")
        
        self.btn_prepare.clicked.connect(self.prepare_chunks_only)
        self.btn_translate_sel.clicked.connect(self.translate_selected_chunk)
        self.btn_start.clicked.connect(self.start_translation)
        self.btn_stop.clicked.connect(self.stop_translation)
        self.btn_clear_cache.clicked.connect(self.clear_cache)

        self.btn_output.clicked.connect(self.export_epub)
        
        self.btn_translate_sel.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_output.setEnabled(False)

        ctrl_row.addWidget(self.progress_bar)
        ctrl_row.addWidget(self.btn_prepare)
        ctrl_row.addWidget(self.btn_translate_sel)
        ctrl_row.addWidget(self.btn_start)
        ctrl_row.addWidget(self.btn_stop)

        ctrl_row.addWidget(self.btn_clear_cache)
        
        # self.btn_auto_fix = QPushButton("自动修复格式")
        # self.btn_auto_fix.clicked.connect(self.auto_fix_all)
        # ctrl_row.addWidget(self.btn_auto_fix)
        
        ctrl_row.addWidget(self.btn_output)
        bottom_layout.addLayout(ctrl_row)

        self.status_label = QLabel("就绪")
        bottom_layout.addWidget(self.status_label)
        
        self.main_splitter.addWidget(bottom_widget)

        # 将主分割器添加到主布局
        main_layout.addWidget(self.main_splitter)
        
        # 设置初始比例 (Settings, Viewer, Controls)
        self.main_splitter.setStretchFactor(0, 0) # Top
        self.main_splitter.setStretchFactor(1, 1) # Viewer (Maximize)
        self.main_splitter.setStretchFactor(2, 0) # Bottom

        # Internal state
        self.worker = None
        self.processor = None
        self.current_cache_data = None

    def update_status(self, text):
        """更新底部的状态标签并强制刷新 UI"""
        self.status_label.setText(text)
        QCoreApplication.processEvents()

    def browse_epub(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择文件", "", "EPUB Files (*.epub);;All Files (*.*)")
        if file_path:
            self.epub_path_edit.setText(file_path)
            # Try auto-load cache if exists
            self.init_processor_and_chunks(autoload=True)

    def browse_cache(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择缓存目录")
        if dir_path:
            self.cache_path_edit.setText(dir_path)
            self.config_manager.set_value('cache_dir', dir_path)

    def browse_output(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if dir_path:
            self.output_path_edit.setText(dir_path)
            self.config_manager.set_value('output_dir', dir_path)

    def load_settings_history(self):
        # Load Global Paths
        cache_dir = self.config_manager.get_value('cache_dir')
        if cache_dir and os.path.exists(cache_dir):
            self.cache_path_edit.setText(cache_dir)
            
        output_dir = self.config_manager.get_value('output_dir')
        if output_dir and os.path.exists(output_dir):
            self.output_path_edit.setText(output_dir)

        # Load API History
        history = self.config_manager.get_history()
        self.history_combo.clear()
        for h in history:
            self.history_combo.addItem(f"{h.get('model')} - {h.get('api_url')}", h)
        
        if history:
            self.set_settings(history[0])

    def set_settings(self, s):
        self.api_key_edit.setText(s.get('api_key', ''))
        self.api_url_edit.setText(s.get('api_url', ''))
        self.model_edit.setText(s.get('model', 'gpt-4o'))
        self.temp_spin.setValue(s.get('temp', 0.7))
        from src.config import DEFAULT_PROMPT
        self.prompt_edit.setPlainText(s.get('prompt') or DEFAULT_PROMPT)
        self.chunk_size_spin.setValue(s['chunk_size'])
        self.concurrency_spin.setValue(s.get('max_workers', 1))
        self.interval_spin.setValue(s.get('interval', 0))
        self.timeout_spin.setValue(s.get('timeout', 60))

    def get_current_settings(self):
        return {
            'api_key': self.api_key_edit.text().strip(),
            'api_url': self.api_url_edit.text().strip(),
            'model': self.model_edit.text().strip(),
            'temp': self.temp_spin.value(),
            'prompt': self.prompt_edit.toPlainText(),
            'chunk_size': self.chunk_size_spin.value(),
            'max_workers': self.concurrency_spin.value(),
            'interval': self.interval_spin.value(),
            'timeout': self.timeout_spin.value()
        }

    def on_history_selected(self, index):
        if index >= 0:
            s = self.history_combo.itemData(index)
            self.set_settings(s)

    def prepare_chunks_only(self):
        result = self.init_processor_and_chunks()
        if result:
            self.status_label.setText("分块与分组完成。")
            self.btn_translate_sel.setEnabled(True)
            self.btn_output.setEnabled(True)

    def init_processor_and_chunks(self, autoload=False):
        file_path = self.epub_path_edit.text()
        if not file_path or not os.path.exists(file_path):
            if not autoload:
               QMessageBox.warning(self, "警告", "请先选择有效的文件")
            return False

        settings = self.get_current_settings()
        cache_dir = self.cache_path_edit.text()
        self.processor = Processor(cache_dir)
        
        try:
            ext = os.path.splitext(file_path)[1].lower()
            if ext == ".epub":
                self.current_mode = "epub_anchor"
                cache_data = self.processor.process_epub_anchor_init(
                    file_path, settings['chunk_size'], only_load=autoload, callback=self.update_status
                )
            else:
                self.update_status(f"错误: 不支持的文件格式: {ext} (仅支持 .epub)")
                return False
            
            if cache_data is None:
                if autoload: return False
                # Should have been handled by processor raising error or returning None if logic failed
                return False

            self.flat_chunks = []
            self.group_table.setRowCount(0)
            self.group_table.blockSignals(True)
            
            row = 0
            for f_i, f_data in enumerate(cache_data["files"]):
                for c_i, c_data in enumerate(f_data["chunks"]):
                    self.flat_chunks.append((f_i, c_i))
                    
                    self.group_table.insertRow(row)
                    # ID
                    self.group_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
                    # Status
                    status_str = "已翻译" if c_data["trans"] else "未翻译"
                    status_item = QTableWidgetItem(status_str)
                    self.group_table.setItem(row, 1, status_item)
                    
                    # Preview
                    preview = c_data["orig"][:50].replace("\n", " ") + "..."
                    preview_item = QTableWidgetItem(preview)
                    self.group_table.setItem(row, 2, preview_item)
                    
                    # ID
                    id_item = QTableWidgetItem(str(row + 1))
                    self.group_table.setItem(row, 0, id_item)
                    
                    if c_data.get("is_error", False):
                         for col in range(3):
                             self.group_table.item(row, col).setBackground(QColor("#ffaaaa")) # Unify to Red
                    
                    row += 1
            
            self.group_table.blockSignals(False)
            self.current_cache_data = cache_data
            
            # Select first row if exists
            if row > 0:
                self.group_table.selectRow(0)
            
            if autoload:
                self.status_label.setText("已自动加载上次的翻译进度。")
                self.btn_translate_sel.setEnabled(True)
                self.btn_output.setEnabled(True)
                
            self.apply_table_filter()
            return True
        except Exception as e:
            if not autoload:
                QMessageBox.critical(self, "错误", f"分块处理失败: {e}")
            return False

    def on_group_selection_changed(self):
        selected_items = self.group_table.selectedItems()
        if not selected_items: return
        
        # Determine unique rows
        rows = sorted(list(set(item.row() for item in selected_items)))
        if not rows: return
        
        # Preview first selected row
        first_row = rows[0]
        self.load_group_into_editor(first_row)
        self.update_block_table(first_row)
        
        if len(rows) > 1:
            self.status_label.setText(f"已选择 {len(rows)} 个分组待翻译")

    def apply_table_filter(self):
        """根据当前筛选器和搜索框的选择显示或隐藏表格行"""
        if not hasattr(self, 'current_cache_data') or not self.current_cache_data:
            return
            
        filter_text = self.filter_combo.currentText()
        search_kw = self.search_edit.text().strip().lower()
        search_type = self.search_type_combo.currentText()
        
        self.group_table.blockSignals(True)
        
        for row in range(self.group_table.rowCount()):
            f_idx, c_idx = self.flat_chunks[row]
            chunk = self.current_cache_data["files"][f_idx]["chunks"][c_idx]
            
            # --- 1. 状态筛选 ---
            match_status = True
            if filter_text == "已翻译":
                match_status = bool(chunk.get("trans"))
            elif filter_text == "未翻译":
                match_status = not bool(chunk.get("trans"))
            elif filter_text == "有错误":
                match_status = chunk.get("is_error", False)
            
            # --- 2. 文本搜索 ---
            match_search = True
            if search_kw:
                orig_text = chunk.get("orig", "").lower()
                trans_text = chunk.get("trans", "").lower() or ""
                
                if search_type == "全文搜索":
                    match_search = (search_kw in orig_text) or (search_kw in trans_text)
                elif search_type == "仅搜索原文":
                    match_search = (search_kw in orig_text)
                elif search_type == "仅搜索译文":
                    match_search = (search_kw in trans_text)
                
            self.group_table.setRowHidden(row, not (match_status and match_search))
            
        self.group_table.blockSignals(False)
            
    def update_block_table(self, group_idx):
        if not hasattr(self, 'flat_chunks') or not self.current_cache_data: return
        
        f_idx, g_idx = self.flat_chunks[group_idx]
        group = self.current_cache_data["files"][f_idx]["chunks"][g_idx]
        block_indices = group.get("block_indices", [])
        
        self.block_table.setRowCount(0)
        self.block_table.blockSignals(True)
        for i, b_idx in enumerate(block_indices):
            self.block_table.insertRow(i)
            self.block_table.setItem(i, 0, QTableWidgetItem(str(b_idx + 1)))
            
            block_meta = self.current_cache_data["all_blocks"][b_idx]
            preview = block_meta["text"][:100].replace("\n", " ")
            self.block_table.setItem(i, 1, QTableWidgetItem(preview))
        self.block_table.blockSignals(False)

    def load_group_into_editor(self, flat_idx):
        if not hasattr(self, 'flat_chunks') or not self.flat_chunks: return
        
        ch_idx, ck_idx = self.flat_chunks[flat_idx]
        
        # 1. Before loading new, SYNC current editor content back to memory 
        # BUT ONLY if we're switching to a DIFFERENT chunk (避免覆盖 on_progress 刚更新的翻译)
        if hasattr(self, 'current_indices') and self.current_cache_data:
             old_f_idx, old_c_idx = self.current_indices
             # 只有在切换到不同块时才回写，避免覆盖最新翻译
             if (old_f_idx, old_c_idx) != (ch_idx, ck_idx):
                 self.current_cache_data["files"][old_f_idx]["chunks"][old_c_idx]["trans"] = self.trans_text_edit.toPlainText()
        
        cache_data = self.current_cache_data
        
        if cache_data and ch_idx < len(cache_data["files"]):
            chunk = cache_data["files"][ch_idx]["chunks"][ck_idx]
            self.orig_text_edit.setPlainText(chunk["orig"])
            self.trans_text_edit.setPlainText(chunk["trans"])
            self.current_indices = (ch_idx, ck_idx)
            self.current_flat_idx_view = flat_idx # track which row is in editor
            self.status_label.setText(f"查看：ID {flat_idx + 1}")

    def translate_selected_chunk(self):
        # Translate ALL selected rows
        if not self.processor:
            if not self.init_processor_and_chunks(): return 

        # Get selected rows BEFORE any potential re-init (though we avoided it above)
        selected_items = self.group_table.selectedItems()
        rows = sorted(list(set(item.row() for item in selected_items)))
        
        if not rows:
            QMessageBox.warning(self, "提示", "请先在列表中选择要翻译的块")
            return

        # --- 实时反馈优化 ---
        # 记录当前任务的选中索引，用于进度计算
        self.current_task_indices = rows
        
        # 立即跳转并定位到第一个选中项
        first_row = rows[0]
        self.group_table.selectRow(first_row)
        if hasattr(self, 'flat_chunks') and hasattr(self, 'current_cache_data'):
            f_idx, c_idx = self.flat_chunks[first_row]
            chunk = self.current_cache_data["files"][f_idx]["chunks"][c_idx]
            self.orig_text_edit.setPlainText(chunk["orig"])
            self.trans_text_edit.setPlainText(chunk["trans"] or "")

        settings = self.get_current_settings()
        translator = Translator(
            settings['api_key'], 
            settings['api_url'], 
            settings['model'], 
            settings['temp'], 
            settings['prompt']
        )
        
        file_path = self.epub_path_edit.text()
        
        self.btn_start.setEnabled(False)
        self.btn_translate_sel.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_output.setEnabled(False)
        self.btn_clear_cache.setEnabled(False)
        
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(len(rows))

        self.worker = TranslationWorker(
            self.processor, 
            translator, 
            file_path,
            settings['chunk_size'],
            max_workers=settings['max_workers'],
            interval=settings['interval'],
            target_indices=rows, # Pass list of flat indices
        )
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()
        self.status_label.setText(f"选定块翻译执行中... (共 {len(rows)} 块)")

    def start_translation(self):
        if not self.init_processor_and_chunks(): return

        settings = self.get_current_settings()
        if not settings['api_key']:
            QMessageBox.warning(self, "警告", "请填入 API Key")
            return

        # Save to history
        self.config_manager.save_config(settings)
        self.load_settings_history()

        translator = Translator(
            settings['api_key'], 
            settings['api_url'], 
            settings['model'], 
            settings['temp'], 
            settings['prompt'],
            timeout=settings['timeout']
        )

        file_path = self.epub_path_edit.text()
        self.btn_start.setEnabled(False)
        self.btn_translate_sel.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_output.setEnabled(False)
        self.btn_clear_cache.setEnabled(False)
        
        self.worker = TranslationWorker(
            self.processor, 
            translator, 
            file_path,
            settings['chunk_size'],
            max_workers=settings['max_workers'],
            interval=settings['interval'],
            # No target_indices = Process ALL from Resume point
        )
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()
        self.current_task_indices = None # 清除选定项记忆，回归全局进度
        self.status_label.setText("全部翻译执行中...")

    def stop_translation(self):
        if self.processor:
            self.processor.status = "stopped"
            # 强化停止时的提示语，告知用户正在优雅退出
            self.status_label.setText("正在等待当前段落完成并保存后停止...")

    def on_progress(self, current_idx, total, orig, trans, is_finished, error_type="ok"):
        # 1. Update In-Memory Cache (Critical for Review) - ALWAYS update cache
        if hasattr(self, 'flat_chunks') and hasattr(self, 'current_cache_data'):
            f_idx, c_idx = self.flat_chunks[current_idx]
            if self.current_cache_data:
                chunk = self.current_cache_data["files"][f_idx]["chunks"][c_idx]
                chunk["trans"] = trans
                # 只有在 chunk 完成时才更新错误类型，流式过程中保持原本状态或默认 ok
                if is_finished:
                    chunk["error_type"] = error_type
                    chunk["is_error"] = (error_type != "ok")
        
        # 2. 实时跟随：只要开始翻译或更新，就选中该行
        cur_row = self.group_table.currentRow()
        if cur_row != current_idx:
            # 立即选中当前正在处理的行，消除“停留在上一行”的延迟感
            self.group_table.selectRow(current_idx)
        else:
            # 如果当前行已经被选中（例如第一个），则手动刷新编辑器内容
            self.load_group_into_editor(current_idx)

        # 3. 进度条与状态栏反馈
        if hasattr(self, 'current_task_indices') and self.current_task_indices:
            # 如果是局部翻译，进度基于选中块
            try:
                task_pos = self.current_task_indices.index(current_idx) + (1 if is_finished else 0.5)
                self.progress_bar.setValue(int(task_pos))
                task_status = f"翻译选定块: {self.current_task_indices.index(current_idx)+1}/{len(self.current_task_indices)}"
            except ValueError:
                task_status = f"进度: {current_idx+1}/{total}"
        else:
            # 全量翻译
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(current_idx + (1 if is_finished else 0))
            task_status = f"全局进度: {current_idx+1}/{total}"

        now = time.time()
        # 处理编辑器实时显示 (流式)
        if not is_finished:
            if now - self._last_ui_update > 0.05: # 减少节流，提升平滑度
                self.status_label.setText(f"{task_status} (流式传输中...)")
                
                # 更新编辑器内容
                if self.group_table.currentRow() == current_idx:
                    self.orig_text_edit.setPlainText(orig)
                    self.trans_text_edit.setPlainText(trans)
                
                self._last_ui_update = now
            return

        # 当一个 chunk 完成时，更新列表状态
        if current_idx < self.group_table.rowCount():
            status_item = self.group_table.item(current_idx, 1)
            if status_item:
                f_idx, c_idx = self.flat_chunks[current_idx]
                chunk = self.current_cache_data["files"][f_idx]["chunks"][c_idx]
                
                status_item.setText("已翻译")
                
                # 颜色逻辑：统一使用红色标注所有错误
                if chunk.get("is_error", False):
                     bg_color = QColor("#ffaaaa") # Red for all errors
                else:
                     bg_color = Qt.transparent
                     
                for col in range(self.group_table.columnCount()):
                    self.group_table.item(current_idx, col).setBackground(bg_color)
        
        
        # 4. 根据当前筛选状态更新可见性
        self.apply_table_filter()
        self.status_label.setText(f"{task_status} (当前块已保存)")

    def save_manual_edit(self):
        if not self.processor or not self.current_cache_data:
            QMessageBox.warning(self, "警告", "没有加载的文件或缓存。")
            return
            
        file_path = self.epub_path_edit.text()
        
        # 1. Sync current editor content to memory
        if hasattr(self, 'current_indices'):
            ch_idx, ck_idx = self.current_indices
            trans_text = self.trans_text_edit.toPlainText()
            self.current_cache_data["files"][ch_idx]["chunks"][ck_idx]["trans"] = trans_text
             
            # Update table UI
            if hasattr(self, 'current_flat_idx_view'):
                row = self.current_flat_idx_view
                self.group_table.item(row, 1).setText("已翻译")
                for col in range(self.group_table.columnCount()):
                    self.group_table.item(row, col).setBackground(Qt.transparent)
            
            # --- CRITICAL FIX START ---
            # 2. Persist to Disk (Individual Chunk)
            flat_idx = self.current_flat_idx_view
            chunk_data = self.current_cache_data["files"][ch_idx]["chunks"][ck_idx]
            
            # 2.1 Re-validate format on manual save
            error_type = self.processor.check_chunk_format(file_path, trans_text, expected_count=len(chunk_data.get("block_indices", [])))
            chunk_data["error_type"] = error_type
            if error_type == "ok":
                chunk_data["is_error"] = False
                # Apply to mirror if valid
                try:
                    self.processor.save_chunk(file_path, flat_idx, chunk_data)
                    self.processor.apply_chunk_to_mirror(file_path, self.current_cache_data, flat_idx)
                    self.status_label.setText(f"修改已保存至磁盘并更新导出镜像 (ID: {flat_idx+1})")
                    
                    # Update UI color
                    for col in range(self.group_table.columnCount()):
                        self.group_table.item(row, col).setBackground(Qt.transparent)
                        
                except Exception as e:
                    QMessageBox.critical(self, "错误", f"保存失败: {e}")
                    return
            else:
                chunk_data["is_error"] = True
                self.processor.save_chunk(file_path, flat_idx, chunk_data) # Save even if invalid
                
                # 颜色逻辑：统一使用红色标注所有错误
                if chunk_data.get("is_error", False):
                    bg_color = QColor("#ffaaaa") # Red for all errors
                else:
                    bg_color = Qt.transparent
                
                self.status_label.setText(f"修改已保存 (ID: {flat_idx+1})")
                if chunk_data.get("is_error", False):
                    self.status_label.setText(f"修改已保存，但检测到格式错误 (ID: {flat_idx+1})")
                    QMessageBox.warning(self, "格式警告", "检测到格式错误（行数或锚点不一致）。\n该组已变红，且暂时不会用于生成最终文档。")
                
                # Update UI color
                for col in range(self.group_table.columnCount()):
                    self.group_table.item(row, col).setBackground(bg_color)
                
                self.apply_table_filter() # Re-apply filter after manual edit






    def clear_cache(self):
        file_path = self.epub_path_edit.text()
        if not file_path:
            QMessageBox.warning(self, "警告", "请先选择文件")
            return
            
        cache_dir = self.cache_path_edit.text()
        proc = Processor(cache_dir)
        
        # 获取新旧两种可能的路径
        folder_cache = proc.get_cache_dir_path(file_path)
        legacy_cache = proc.get_legacy_cache_path(file_path)
        
        reply = QMessageBox.question(self, '确认清除', '确定要清除当前书籍的翻译缓存吗？这将导致翻译重新开始。',
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            deleted = False
            # 1. robustly delete new folder cache
            if os.path.exists(folder_cache):
                import shutil
                try:
                    # 使用 ignore_errors=True 强制删除，防止被文件锁阻塞
                    shutil.rmtree(folder_cache, ignore_errors=True)
                    # Double check if it's gone, if not, try once more or just proceed
                    if os.path.exists(folder_cache):
                        shutil.rmtree(folder_cache, ignore_errors=True)
                    deleted = True
                except Exception as e:
                    QMessageBox.warning(self, "警告", f"清除缓存文件夹时遇到问题: {e}")
            
            # 2. 删除旧版单文件缓存
            if os.path.exists(legacy_cache):
                try:
                    os.remove(legacy_cache)
                    deleted = True
                except:
                    pass
                
            # 3. Always clear internal state regardless of file deletion success
            # This ensures "Zombie" data doesn't persist in memory
            self.current_cache_data = None
            if hasattr(self, 'flat_chunks'):
                self.flat_chunks = []
            self.group_table.setRowCount(0)
            self.block_table.setRowCount(0)
            self.orig_text_edit.clear()
            self.trans_text_edit.clear()
            self.status_label.setText("缓存已清除，请重新点击 '分块并分组'")
            
            if deleted:
                QMessageBox.information(self, "成功", f"已清除缓存目录:\n{folder_cache}")
            else:
                QMessageBox.information(self, "提示", "未发现现有缓存或缓存已被清除。")

    def on_finished(self, complete):
        self.btn_start.setEnabled(True)
        self.btn_translate_sel.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_output.setEnabled(True)
        self.btn_clear_cache.setEnabled(True)
        
        # Refresh table statuses just in case
        if hasattr(self, 'processor'):
             # We could reload cache to verify, but simple UI update is enough usually
             pass
        
        if complete:
            self.save_manual_edit()
            if self.worker and hasattr(self.worker, 'target_indices') and self.worker.target_indices:
                self.status_label.setText(f"选中块翻译完成。")
            else:
                self.status_label.setText("全部翻译任务已完成！")
                QMessageBox.information(self, "完成", "翻译已结束。")
        else:
            self.status_label.setText("任务已中止。")

    def on_error(self, message):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        QMessageBox.critical(self, "错误", f"发生异常: {message}")

    def export_epub(self):
        file_path = self.epub_path_edit.text()
        if not self.processor:
            QMessageBox.warning(self, "警告", "请先初始化并翻译文件。")
            return

        # cache_file = self.processor.get_cache_filename(file_path)
        # load_cache expects the INPUT file path, not the cache path
        cache_data = self.processor.load_cache(file_path)
        
        if not cache_data:
            QMessageBox.warning(self, "警告", "未找到翻译缓存。")
            return

        output_root = self.output_path_edit.text()
        if not os.path.exists(output_root):
            os.makedirs(output_root)
            
        ext = os.path.splitext(file_path)[1].lower()
        file_ext = ext.lstrip('.')
        target_format = file_ext

        base_name = os.path.splitext(os.path.basename(file_path))[0]
        output_path = os.path.join(output_root, f"translated_{base_name}.{file_ext}")

        try:
            self.status_label.setText("正在导出...")
            msg = self.processor.finalize_translation(file_path, output_path, target_format)
            
            self.status_label.setText("导出成功")
            QMessageBox.information(self, "成功", f"导出完成！\n{msg}")
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "错误", f"导出失败: {e}")
            self.status_label.setText("导出失败")
            

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
