"""pytest 公共夹具。"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gimp_client import GimpClient, GimpConnectionError  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def gimp_console() -> str:
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/GIMP 3/bin",
        Path("C:/Program Files/GIMP 3/bin"),
    ]
    for directory in candidates:
        matches = sorted(directory.glob("gimp-console-3.*.exe"), reverse=True)
        if matches:
            return str(matches[0])
    for name in ("gimp-console-3.0", "gimp-console-3.2", "gimp-console"):
        executable = shutil.which(name)
        if executable:
            return executable
    pytest.skip("未找到 GIMP 3 console，跳过需要 GIMP 的测试")


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def live_client(gimp_console, tmp_path_factory) -> GimpClient:
    root = tmp_path_factory.mktemp("gimp-live")
    profile = root / "profile"
    profile.mkdir()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    command = [
        gimp_console, "--new-instance", "--no-data", "--no-splash",
        "--batch-interpreter=plug-in-script-fu-eval", "--batch",
        f'(plug-in-script-fu-server 1 "127.0.0.1" {port} "")',
    ]
    client = GimpClient(port=port, timeout=3, reconnect_retries=0)
    ready = False
    with (root / "gimp.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command, env={**os.environ, "GIMP3_DIRECTORY": str(profile)},
            stdout=log, stderr=log,
        )
        try:
            deadline = time.monotonic() + 90
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    client.connect()
                    ready = True
                    break
                except GimpConnectionError:
                    threading.Event().wait(0.1)
            if not ready:
                pytest.fail(f"专用 GIMP 未启动，日志: {root / 'gimp.log'}")
            client.timeout = 60
            client._sock.settimeout(60)
            yield client
        finally:
            if process.poll() is None:
                if ready:
                    client.timeout = 3
                    if client._sock is not None:
                        client._sock.settimeout(3)
                    try:
                        client.eval("(gimp-quit 1)")
                    except GimpConnectionError:
                        pass
                else:
                    process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            client.close()


def _image_ids(client) -> set[int]:
    body = client.eval_string(
        '(let loop ((ids (vector->list (car (gimp-get-images)))) (acc ""))'
        ' (if (null? ids) acc'
        ' (loop (cdr ids) (string-append acc " " (number->string (car ids))))))'
    )
    return {int(value) for value in body.split()}


@pytest.fixture()
def image_scope(live_client):
    before = _image_ids(live_client)
    yield
    for image_id in _image_ids(live_client) - before:
        live_client.eval(f"(gimp-image-delete {image_id})")


@pytest.fixture()
def fresh_image(live_client, image_scope):
    from tools import files

    info = files.new_image(live_client, 320, 180, "rgb")
    return live_client, info


@pytest.fixture()
def preview_link(tmp_path):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    link = allowed / ".previews"
    if os.name == "nt":
        result = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(link), str(outside)],
            capture_output=True, timeout=10,
        )
        assert result.returncode == 0, result.stderr
    else:
        link.symlink_to(outside, target_is_directory=True)
    try:
        yield link, outside
    finally:
        if os.name == "nt":
            os.rmdir(link)
        else:
            link.unlink()
