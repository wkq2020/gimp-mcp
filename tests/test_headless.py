"""独立 GIMP 实例的 Scheme 合法性测试：pytest -m headless。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.headless


def _run_batch(exe: str, scheme: str, profile: Path) -> subprocess.CompletedProcess:
    profile.mkdir()
    return subprocess.run(
        [exe, "--new-instance", "--no-data", "--no-splash",
         "--batch-interpreter=plug-in-script-fu-eval", "--batch", scheme, "--quit"],
        env={**os.environ, "GIMP3_DIRECTORY": str(profile)},
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
    )


def test_scheme_snippet_legal(gimp_console, tmp_path):
    tmp = tmp_path / "headless.png"
    snippet = f"""
(let ((img (car (gimp-image-new 64 48 RGB))))
  (let ((l (car (gimp-layer-new img "L" 64 48 RGB-IMAGE 100 LAYER-MODE-NORMAL))))
    (gimp-image-insert-layer img l -1 0)
    (gimp-image-set-selected-layers img (vector l))
    (gimp-image-crop img 32 24 4 4)
    (gimp-drawable-merge-new-filter l "gimp:brightness-contrast" 0 LAYER-MODE-REPLACE 1.0 "brightness" 0.1 "contrast" 0.0)
    (file-png-export 1 img "{tmp.as_posix()}" 0 FALSE 9 TRUE FALSE TRUE TRUE)))
""".strip()
    proc = _run_batch(gimp_console, snippet, tmp_path / "profile")
    assert proc.returncode == 0, f"批处理失败:\n{proc.stdout}\n{proc.stderr}"
    assert tmp.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_scheme_text_snippet_legal(gimp_console, tmp_path):
    snippet = """
(let ((img (car (gimp-image-new 200 80 RGB))))
  (let ((l (car (gimp-layer-new img "L" 200 80 RGB-IMAGE 100 LAYER-MODE-NORMAL))))
    (gimp-image-insert-layer img l -1 0)
    (gimp-image-set-selected-layers img (vector l))
    (let ((f (car (gimp-font-get-by-name "Sans-serif"))))
      (gimp-text-font img -1 5 5 "headless" 0 TRUE 20 f)
      (gimp-image-scale img 100 40)
      (gimp-drawable-histogram l 0 0.0 1.0))))
""".strip()
    proc = _run_batch(gimp_console, snippet, tmp_path / "profile")
    assert proc.returncode == 0, f"批处理失败:\n{proc.stdout}\n{proc.stderr}"
