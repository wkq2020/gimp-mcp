"""探针 8：jpeg/webp 导出签名收敛 + PDB 信息查询过程名探测。"""

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
    print(f"[{status}] {label}\n      -> {body.decode('utf-8', errors='replace')[:180]!r}")
    return err


def q(s):
    return '"' + s.replace("\\", "/").replace('"', '\\"') + '"'


def main():
    with socket.create_connection((HOST, PORT), timeout=60) as sock:
        for name in ["gimp-pdb-get-proc-info", "gimp-pdb-procedure-get-arguments",
                     "gimp-pdb-get-procedure-argument", "gimp-pdb-procedure-get-info",
                     "gimp-pdb-get-procedure-documentation"]:
            ev(sock, f'(gimp-pdb-procedure-exists "{name}")', f"exists {name}")

        ev(sock, """
(let ((img (car (gimp-image-new 64 48 RGB))))
  (gimp-image-insert-layer img (car (gimp-layer-new img "L" 64 48 RGB-IMAGE 100 LAYER-MODE-NORMAL)) -1 0)
  (number->string img))""", "建图")
        # 直接固定用最近图像
        img_expr = "(vector-ref (car (gimp-get-images)) 0)"

        jpg = q(str(OUT / "t.jpg"))
        ev(sock, f"(file-jpeg-export 1 {img_expr} {jpg} 0.9 0.0 1 1 2 1 0 2)", "jpeg 变体1: 无comment")
        ev(sock, f"(file-jpeg-export 1 {img_expr} {jpg} 0.9 0.0 1 1 2 1 0)", "jpeg 变体2: 再少一参")
        ev(sock, f'(file-jpeg-export 1 {img_expr} {jpg} 0.9 0.0 1 1 "" 2 1 0 2)', "jpeg 变体3: comment串")

        webp = q(str(OUT / "t.webp"))
        ev(sock, f"(file-webp-export 1 {img_expr} {webp} 0 0 90.0 90.0)", "webp 变体1: 最短")
        ev(sock, f"(file-webp-export 1 {img_expr} {webp} 0 0 90.0 90.0 0 0 0 0 0)", "webp 变体2: 10参")
        ev(sock, f'(file-webp-export 1 {img_expr} {webp} 0 0 90.0 90.0 "" 0 0 0 0 0 0 0)', "webp 变体3: 中间metadata串")

        ev(sock, '(for-each gimp-image-delete (vector->list (car (gimp-get-images))))', "清理")


if __name__ == "__main__":
    main()
