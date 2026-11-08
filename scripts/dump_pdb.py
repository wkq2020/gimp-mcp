"""通过 gimp-console 的 python-fu-eval 内省 PDB，输出过程签名。

用法: dump_pdb.py <gimp-console路径> <输出文件> [正则过滤词...]
"""

import subprocess
import sys

INTROSPECT = r'''
import gi
gi.require_version("Gimp", "3.0")
from gi.repository import Gimp, GLib

pdb = Gimp.get_pdb()

def dump_pattern(pattern):
    names = pdb.query_procedures("", "", "", "", "", "", "", pattern)
    for name in sorted(names):
        try:
            proc = pdb.lookup_procedure(name)
            args = []
            for pspec in proc.get_arguments():
                args.append(f"{pspec.name}:{pspec.value_type.name}")
            rets = [f"{p.name}:{p.value_type.name}" for p in proc.get_return_values()]
            print(f"PROC {name}")
            print(f"  ARGS {' | '.join(args)}")
            print(f"  RETS {' | '.join(rets)}")
        except Exception as e:
            print(f"PROC {name} ERROR {e}")

for pat in __PATTERNS__:
    print(f"### PATTERN {pat}")
    dump_pattern(pat)
'''

DEFAULT_PATTERNS = [
    "filter", "gauss", "unsharp", "histogram", "levels", "brightness",
    "hue-sat", "desaturate", "text", "layer", "selection", "export",
    "image-crop", "image-scale", "image-resize", "image-rotate", "image-flip",
    "file-load", "file-save", "image-new", "image-get", "item-get",
    "context-set", "image-select", "version",
]


def main():
    exe, out_path = sys.argv[1], sys.argv[2]
    patterns = sys.argv[3:] or DEFAULT_PATTERNS
    script = INTROSPECT.replace("__PATTERNS__", repr(patterns))
    cmd = [
        exe,
        "--batch-interpreter=python-fu-eval",
        "--batch", script,
        "--batch", "import gi; gi.require_version('Gimp','3.0'); from gi.repository import Gimp; Gimp.quit(0)",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(proc.stdout)
        if proc.stderr:
            f.write("\n### STDERR\n" + proc.stderr)
    print(f"exit={proc.returncode} stdout {len(proc.stdout)} chars -> {out_path}")


if __name__ == "__main__":
    main()
