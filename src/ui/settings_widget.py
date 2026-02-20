from PySide6.QtWidgets import (QWidget, QGroupBox, QFormLayout, QLineEdit, 
                               QDoubleSpinBox, QSpinBox, QTextEdit, QVBoxLayout, 
                               QScrollArea, QComboBox)
from PySide6.QtCore import QSettings

from src.config import DEFAULT_ENDPOINT, DEFAULT_MODEL, DEFAULT_TEMPERATURE, DEFAULT_CHUNK_SIZE, DEFAULT_PROMPT

class SettingsWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("MyCompany", "EPUBTranslator")
        
        layout = QVBoxLayout(self)
        
        # Scroll area for smaller screens
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form_layout = QFormLayout(content)

        # API Settings
        api_group = QGroupBox("API Settings")
        api_layout = QFormLayout()
        
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.endpoint_edit = QLineEdit(DEFAULT_ENDPOINT)
        
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.addItems(["gpt-3.5-turbo", "gpt-4", "deepseek-chat"])
        
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 1.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setValue(DEFAULT_TEMPERATURE)

        api_layout.addRow("API Key:", self.api_key_edit)
        api_layout.addRow("Endpoint:", self.endpoint_edit)
        api_layout.addRow("Model:", self.model_combo)
        api_layout.addRow("Temperature:", self.temp_spin)
        api_group.setLayout(api_layout)
        
        form_layout.addRow(api_group)

        # Translation Settings
        trans_group = QGroupBox("Translation Settings")
        trans_layout = QFormLayout()

        self.chunk_size_spin = QSpinBox()
        self.chunk_size_spin.setRange(100, 5000)
        self.chunk_size_spin.setValue(DEFAULT_CHUNK_SIZE)
        self.chunk_size_spin.setSuffix(" chars")

        trans_layout.addRow("Chunk Size:", self.chunk_size_spin)
        
        # Prompt
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlainText(DEFAULT_PROMPT)
        self.prompt_edit.setMaximumHeight(150)
        
        trans_layout.addRow("System Prompt:", self.prompt_edit)
        trans_group.setLayout(trans_layout)

        form_layout.addRow(trans_group)
        
        scroll.setWidget(content)
        layout.addWidget(scroll)
        
        self.load_settings()

    def get_values(self):
        values = {
            "api_key": self.api_key_edit.text(),
            "endpoint": self.endpoint_edit.text(),
            "model": self.model_combo.currentText(),
            "temperature": self.temp_spin.value(),
            "chunk_size": self.chunk_size_spin.value(),
            "prompt": self.prompt_edit.toPlainText()
        }
        self.save_settings(values)
        return values

    def save_settings(self, values):
        self.settings.setValue("api_key", values["api_key"])
        self.settings.setValue("endpoint", values["endpoint"])
        self.settings.setValue("model", values["model"])
        self.settings.setValue("temperature", values["temperature"])
        self.settings.setValue("chunk_size", values["chunk_size"])
        self.settings.setValue("prompt", values["prompt"])

    def load_settings(self):
        if self.settings.value("api_key"):
            self.api_key_edit.setText(self.settings.value("api_key"))
        if self.settings.value("endpoint"):
            self.endpoint_edit.setText(self.settings.value("endpoint"))
        if self.settings.value("model"):
            self.model_combo.setCurrentText(self.settings.value("model"))
        if self.settings.value("temperature"):
            self.temp_spin.setValue(float(self.settings.value("temperature")))
        if self.settings.value("chunk_size"):
            self.chunk_size_spin.setValue(int(self.settings.value("chunk_size")))
        if self.settings.value("prompt"):
            self.prompt_edit.setPlainText(self.settings.value("prompt"))
