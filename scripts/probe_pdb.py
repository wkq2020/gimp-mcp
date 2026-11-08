"""探针 3：确定 GIMP 3.2.6 中 PDB 查询过程与图像对象的表示方式。"""

import socket

HOST, PORT = "127.0.0.1", 10008
MAGIC = 0x47


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
    print(f"[err={err}] {code[:100]!r}\n    -> {body.decode('utf-8', errors='replace')[:400]!r}")


CASES = [
    # GIMP 3 中 PDB 查询过程的候选名
    '(gimp-pdb-query ".*" ".*" ".*" ".*" ".*" ".*" ".*" "gimp-image-scale")',
    '(gimp-pdb-procedure-exists "gimp-image-scale")',
    '(gimp-pdb-get-procedure-info "gimp-image-scale")',
    # 新建图像后观察图像/图层的表示（整数 ID 还是对象）
    '(let ((img (car (gimp-image-new 100 80 RGB)))) (gimp-image-get-width img))',
    '(let ((img (car (gimp-image-new 100 80 RGB)))) (gimp-image-get-layers img))',
    # 新建图像的返回值形式（list 还是裸值）
    "(gimp-image-new 64 64 RGB)",
    # 清理刚才建的图像
    '(let ((imgs (gimp-get-images))) (map (lambda (i) (gimp-image-delete i)) (cadr imgs)) (gimp-get-images))',
    "(gimp-get-images)",
]


def main():
    with socket.create_connection((HOST, PORT), timeout=30) as sock:
        for c in CASES:
            ev(sock, c)


if __name__ == "__main__":
    main()
