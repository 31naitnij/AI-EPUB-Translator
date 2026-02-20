from PySide6.QtWidgets import QWidget, QVBoxLayout, QProgressBar, QTextEdit, QSplitter, QLabel
from PySide6.QtCore import Qt

class MonitorWidget(QWidget):
    def __init__(self):
        super().__init__()
        
        layout = QVBoxLayout(self)
        
        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(100)
        layout.addWidget(self.progress_bar)
        
        # Log Area (Splitter for dual column)
        splitter = QSplitter(Qt.Horizontal)
        
        # Source Column
        source_container = QWidget()
        source_layout = QVBoxLayout(source_container)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_label = QLabel("Original Text")
        source_layout.addWidget(source_label)
        self.source_edit = QTextEdit()
        self.source_edit.setReadOnly(True)
        source_layout.addWidget(self.source_edit)
        
        # Translation Column
        trans_container = QWidget()
        trans_layout = QVBoxLayout(trans_container)
        trans_layout.setContentsMargins(0, 0, 0, 0)
        trans_label = QLabel("Translated Text")
        trans_layout.addWidget(trans_label)
        self.trans_edit = QTextEdit()
        self.trans_edit.setReadOnly(True)
        trans_layout.addWidget(self.trans_edit)
        
        splitter.addWidget(source_container)
        splitter.addWidget(trans_container)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        
        layout.addWidget(splitter)
    
    def append_log(self, source_text, trans_text):
        """Append to log streams."""
        if source_text:
            self.source_edit.append(source_text)
            self.source_edit.ensureCursorVisible()
        if trans_text:
            self.trans_edit.append(trans_text)
            self.trans_edit.ensureCursorVisible()
    
    def new_block(self):
        """Insert separator for new block."""
        self.source_edit.append("\n" + "-"*50 + "\n")
        self.trans_edit.append("\n" + "-"*50 + "\n")
