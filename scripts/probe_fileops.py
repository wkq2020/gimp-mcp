"""探针 7：实测 GIMP 3.2.6 文件/导出过程的准确签名。

策略：对每个候选签名直接调用，读取成功或错误文本，收敛到真实签名。
"""

import socket
import tempfile
from pathlib import Path

HOST, PORT = "127.0.0.1", 10008
MAGIC = 0x47
OUT = Path(tempfile.gettempdir()) / "gimp_probe_out"
OUT.mkdir(exist_ok=True)


def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf.extend(chunk)
    return bytes(buf)


def ev(sock, code, label=""):
    payload = code.encode("utf-8")
    sock.sendall(bytes([MAGIC, (len(payload) >> 8) & 0xFF, len(payload) & 0xFF]) + payload)
    h = recv_exact(sock, 4)
    _, err, hi, lo = h
    body = recv_exact(sock, (hi << 8) | lo) if (hi or lo) else b""
    status = "OK " if err == 0 else "ERR"
    print(f"[{status}] {label or code[:100]}\n      -> {body.decode('utf-8', errors='replace')[:200]!r}")
    return err, body.decode("utf-8", errors="replace")


def p(name):
    """返回带双引号的 Scheme 字符串字面量（正斜杠路径）。"""
    s = str(OUT / name).replace("\\", "/")
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main():
    with socket.create_connection((HOST, PORT), timeout=60) as sock:
        # 建图（RGB + 图层），img 取返回的 ID
        err, body = ev(sock, """
(let ((img (car (gimp-image-new 64 48 RGB))))
  (gimp-image-insert-layer img (car (gimp-layer-new img "L" 64 48 RGB-IMAGE 100 LAYER-MODE-NORMAL)) -1 0)
  (number->string img))
""", "建图")
        img = body.strip().strip('"').split("#")[0].strip('"')
        print(f"      img id = {img}")

        ev(sock, f'(gimp-file-save 1 {img} {p("a.xcf")!r} {p("a.xcf")})', "gimp-file-save 4参(2.10式)")
        ev(sock, f'(gimp-file-save 1 {img} {p("b.xcf")})', "gimp-file-save 3参")

        ev(sock, f'(file-png-export 1 {img} {p("a.png")} 0 9 1 1 1 1 1)', "png 8参(2.10式)")
        ev(sock, f'(file-png-export 1 {img} {p("b.png")} 0 9 1 1 1 1 1 1 1)', "png 11参")

        ev(sock, f'(file-jpeg-export 1 {img} {p("a.jpg")} 0.9 0.0 1 1 "" 2 1 0 2)', "jpeg 11参(2.10式)")
        ev(sock, f'(file-jpeg-export 1 {img} {p("b.jpg")} 0.9 0.0 1 1 "" 2 1 0 2 0)', "jpeg 12参")

        ev(sock, f'(file-webp-export 1 {img} {p("a.webp")} 0 0 90.0 90.0 0 0 0 0 0 0 0 0 0)', "webp 15参(2.10式)")
        ev(sock, f'(file-webp-export 1 {img} {p("b.webp")} 0 0 90.0 90.0 0 0 0 0 0 0)', "webp 12参")

        ev(sock, f'(file-tiff-export 1 {img} {p("a.tiff")} 1 0)', "tiff 5参(2.10式)")
        ev(sock, f'(file-tiff-export 1 {img} {p("b.tiff")} 1)', "tiff 4参")

        # open_image 反向验证：加载刚导出的 png
        ev(sock, f'(gimp-file-load 1 {p("a.png")} {p("a.png")})', "gimp-file-load 3参")
        ev(sock, f'(gimp-file-load 1 {p("a.png")})', "gimp-file-load 2参")

        ev(sock, f"(gimp-image-delete {img})", "清理")
        # 清理遗留图像
        ev(sock, '(for-each gimp-image-delete (vector->list (car (gimp-get-images))))', "清理全部图像")
        print("\n产出文件:")
        for f in sorted(OUT.glob("*")):
            print(f"  {f.name}: {f.stat().st_size} bytes")


if __name__ == "__main__":
    main()
