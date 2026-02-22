import sys
import subprocess
import os

def build():
    """
    Build the EPUB Translator using PyInstaller and the .spec file.
    The .spec file contains all optimized configurations.
    """
    spec_file = "EPUB_Translator.spec"
    
    if not os.path.exists(spec_file):
        print(f"Error: {spec_file} not found.")
        return

    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        spec_file
    ]
    
    print("Building with command:", " ".join(command))
    try:
        subprocess.run(command, check=True)
        print("\n[SUCCESS] Build completed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Build failed with exit code {e.returncode}")
        sys.exit(e.returncode)

if __name__ == "__main__":
    build()
