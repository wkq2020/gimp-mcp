"""探针 9：自适应收敛 file-jpeg-export / file-webp-export 的完整签名。

算法：从 (proc 1 img file) 起，每次按错误提示 "expected type: T for argument N"
在位置 N 插入对应类型的哑元，直到调用成功。
"""

import re
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


def ev(sock, code):
    payload = code.encode("utf-8")
    sock.sendall(bytes([MAGIC, (len(payload) >> 8) & 0xFF, len(payload) & 0xFF]) + payload)
    h = recv_exact(sock, 4)
    _, err, hi, lo = h
    body = recv_exact(sock, (hi << 8) | lo) if (hi or lo) else b""
    return err, body.decode("utf-8", errors="replace")


def solve(sock, proc, outfile):
    args: list[str] = []
    for _ in range(25):
        code = f"({proc} 1 (vector-ref (car (gimp-get-images)) 0) \"{outfile}\" {' '.join(args)})"
        err, body = ev(sock, code)
        if err == 0:
            print(f"[收敛] {proc} 成功: 参数列表 = [{' '.join(args)}]  共{len(args)}参")
            return args
        m = re.search(r"expected type: (\w+) for argument (\d+)", body)
        if not m:
            print(f"[失败] {proc}: {body.strip()[:160]}")
            return None
        typ, pos = m.group(1), int(m.group(2))
        idx = pos - 4  # 前3个位置是 run-mode/image/file，转为 args 下标
        if idx < 0 or idx > len(args):
            print(f"[异常] {proc}: 位置 {pos} 越界（当前 {len(args)} 参）: {body.strip()[:120]}")
            return None
        dummy = {"string": '"x"', "numeric": "1", "integer": "1", "float": "1.0"}.get(typ, "1")
        args.insert(idx, dummy)
        print(f"  位置{pos} 需要 {typ}，插入 {dummy} -> [{' '.join(args)}]")
    print(f"[超限] {proc} 未收敛")
    return None


def main():
    with socket.create_connection((HOST, PORT), timeout=60) as sock:
        ev(sock, """
(let ((img (car (gimp-image-new 64 48 RGB))))
  (gimp-image-insert-layer img (car (gimp-layer-new img "L" 64 48 RGB-IMAGE 100 LAYER-MODE-NORMAL)) -1 0)
  img)""")
        jpg = str(OUT / "solve.jpg").replace("\\", "/")
        webp = str(OUT / "solve.webp").replace("\\", "/")
        solve(sock, "file-jpeg-export", jpg)
        solve(sock, "file-webp-export", webp)
        ev(sock, '(for-each gimp-image-delete (vector->list (car (gimp-get-images))))')


if __name__ == "__main__":
    main()
