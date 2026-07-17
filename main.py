import sys
import os
import traceback

# Add src to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QMessageBox
from src.ui.main_window import MainWindow

# 全局异常钩子：捕获所有未处理的异常并显示给用户
def global_excepthook(exc_type, exc_value, exc_tb):
    print(f"[GLOBAL EXCEPTION] {exc_type.__name__}: {exc_value}")
    traceback.print_exception(exc_type, exc_value, exc_tb)
    try:
        tb_str = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
        QMessageBox.critical(None, "未捕获的异常", f"{exc_type.__name__}: {exc_value}\n\n{tb_str}")
    except Exception:
        pass

sys.excepthook = global_excepthook

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    if "--direct" in sys.argv:
        window.mode_combo.setCurrentIndex(1)
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
