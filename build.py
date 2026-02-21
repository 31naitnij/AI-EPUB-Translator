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
        "--clean",
        "--collect-all=markdown",
        "--collect-all=lxml",
        "--collect-all=ebooklib",
        "--collect-all=PySide6",
        # Add src to search path
        "--paths=src",
        # Force include src modules
        "--hidden-import=src",
        "main.py"
    ]
    
    print("Building with command:", " ".join(command))
    subprocess.run(command, check=True)

if __name__ == "__main__":
    build()
