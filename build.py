import sys
import subprocess

def build():
    """
    Build the EPUB Translator using PyInstaller.
    This uses explicit --hidden-import for ALL modules to ensure they're bundled.
    """
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",  # No console
        "--name=EPUB_Translator",
        # Add src to search path
        "--paths=src",
        # CRITICAL: Force include ALL modules explicitly
        "--hidden-import=src",
        "--hidden-import=src.config",
        "--hidden-import=src.core",
        "--hidden-import=src.core.cache_manager",
        "--hidden-import=src.core.epub_manager",
        "--hidden-import=src.core.parser",
        "--hidden-import=src.core.translator",
        "--hidden-import=src.core.worker",
        "--hidden-import=src.ui",
        "--hidden-import=src.ui.main_window",
        "--hidden-import=src.ui.settings_widget",
        "--hidden-import=src.ui.file_widget",
        "--hidden-import=src.ui.monitor_widget",
        "main.py"
    ]
    
    print("Building with command:", " ".join(command))
    subprocess.run(command, check=True)

if __name__ == "__main__":
    build()
