"""探针 6：滤镜（GEGL）调用链与直方图签名实测。"""

import socket

HOST, PORT = "127.0.0.1", 10008
MAGIC = 0x47

CANDIDATES = [
    "gimp-drawable-filter-new", "gimp-drawable-filter-configure",
    "gimp-drawable-filter-get-name", "gimp-drawable-get-filters",
    "gimp-drawable-filter-get-arguments", "gimp-drawable-filter-set-aux-input",
    "plug-in-gauss-iir", "plug-in-gauss-rle", "plug-in-gauss-iir2",
    "plug-in-unsharp-mask2", "gimp-image-convert-precision",
]

SCRIPT_SETUP = """
(let ((img (car (gimp-image-new 64 64 RGB))))
  (let ((layer (car (gimp-layer-new img 64 64 RGB-IMAGE "L" 100 LAYER-MODE-NORMAL))))
    (gimp-image-insert-layer img layer -1 0)
    (gimp-image-set-selected-layers img (vector layer))
    img))
"""


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
    print(f"[err={err}] {label or code[:110]!r}\n    -> {body.decode('utf-8', errors='replace')[:400]!r}")
    return err, body.decode("utf-8", errors="replace")


def main():
    with socket.create_connection((HOST, PORT), timeout=60) as sock:
        for name in CANDIDATES:
            err, body = ev(sock, f'(gimp-pdb-procedure-exists "{name}")', name)
        # 建测试图
        err, body = ev(sock, SCRIPT_SETUP, "建图+图层")
        img = body.strip().strip("()")
        # 直方图签名实测（通道 0=HISTOGRAM-VALUE，范围 0..1）
        ev(sock, f"(gimp-drawable-histogram (car (gimp-image-get-selected-drawables {img})) HISTOGRAM-VALUE 0.0 1.0)", "直方图 value 0..1")
        # GEGL 滤镜链实测
        ev(sock, f'(gimp-drawable-filter-new {img} "gegl:gaussian-blur" "blur")', "filter-new gaussian-blur")
        ev(sock, f'(let ((f (car (gimp-drawable-filter-new {img} "gegl:gaussian-blur" "blur")))) (gimp-drawable-filter-configure f LAYER-MODE-REPLACE 100.0 5.0 5.0 0.0 0 "none" FALSE) (gimp-drawable-merge-filter (car (gimp-image-get-selected-drawables {img})) f) "ok")', "configure+merge v1")
        # 清理
        ev(sock, f"(gimp-image-delete {img})", "清理")


if __name__ == "__main__":
    main()
