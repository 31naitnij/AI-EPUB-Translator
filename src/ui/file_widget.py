from PySide6.QtWidgets import (QWidget, QVBoxLayout, QPushButton, 
                               QLineEdit, QFileDialog, QGroupBox)
from PySide6.QtCore import QSettings

class FileWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("MyCompany", "EPUBTranslator")
        
        layout = QVBoxLayout(self)
        
        # Input File
        input_group = QGroupBox("Input File")
        input_layout = QVBoxLayout()
        self.input_path_edit = QLineEdit()
        self.input_btn = QPushButton("Browse EPUB...")
        self.input_btn.clicked.connect(self.browse_input)
        input_layout.addWidget(self.input_path_edit)
        input_layout.addWidget(self.input_btn)
        input_group.setLayout(input_layout)
        layout.addWidget(input_group)

        # Output Directory
        output_group = QGroupBox("Output Directory")
        output_layout = QVBoxLayout()
        self.output_path_edit = QLineEdit()
        self.output_btn = QPushButton("Browse Dir...")
        self.output_btn.clicked.connect(self.browse_output)
        output_layout.addWidget(self.output_path_edit)
        output_layout.addWidget(self.output_btn)
        output_group.setLayout(output_layout)
        layout.addWidget(output_group)

        # Cache DB
        cache_group = QGroupBox("Cache Database")
        cache_layout = QVBoxLayout()
        self.cache_path_edit = QLineEdit("translation_cache.db")
        self.cache_btn = QPushButton("Browse DB...")
        self.cache_btn.clicked.connect(self.browse_cache)
        cache_layout.addWidget(self.cache_path_edit)
        cache_layout.addWidget(self.cache_btn)
        cache_group.setLayout(cache_layout)
        layout.addWidget(cache_group)

        # Action Buttons
        self.start_btn = QPushButton("START TRANSLATION")
        self.start_btn.setMinimumHeight(50)
        self.start_btn.setStyleSheet("font-weight: bold; font-size: 14px; background-color: #4CAF50; color: white;")
        layout.addWidget(self.start_btn)

        layout.addStretch()
        
        self.load_settings()

    def browse_input(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select EPUB", "", "EPUB Files (*.epub)")
        if path:
            self.input_path_edit.setText(path)
            self.settings.setValue("last_input", path)

    def browse_output(self):
        path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if path:
            self.output_path_edit.setText(path)
            self.settings.setValue("last_output", path)

    def browse_cache(self):
        path, _ = QFileDialog.getSaveFileName(self, "Select Cache DB", "", "SQLite DB (*.db)")
        if path:
            self.cache_path_edit.setText(path)
            self.settings.setValue("last_cache", path)

    def get_paths(self):
        return {
            "input": self.input_path_edit.text(),
            "output": self.output_path_edit.text(),
            "cache": self.cache_path_edit.text()
        }

    def load_settings(self):
        if self.settings.value("last_input"):
            self.input_path_edit.setText(self.settings.value("last_input"))
        if self.settings.value("last_output"):
            self.output_path_edit.setText(self.settings.value("last_output"))
        if self.settings.value("last_cache"):
            self.cache_path_edit.setText(self.settings.value("last_cache"))
