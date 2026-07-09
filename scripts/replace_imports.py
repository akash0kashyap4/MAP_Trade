import glob
import os

files = glob.glob("**/*.py", recursive=True)
for fpath in files:
    if "venv" in fpath or ".agents" in fpath or "upstox" in fpath or "replace_imports.py" in fpath:
        continue
    with open(fpath, "r", encoding="utf-8") as f:
        content = f.read()
    
    new_content = content.replace("from upstox", "from groww").replace("import upstox", "import groww")
    
    if new_content != content:
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"Updated {fpath}")
