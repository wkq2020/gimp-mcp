"""探针 5：为缺失过程名寻找 GIMP 3.2.6 替代名。"""

import socket

HOST, PORT = "127.0.0.1", 10008
MAGIC = 0x47

CANDIDATES = [
    # 活动/选中图层
    "gimp-image-set-selected-layers", "gimp-image-get-selected-layers",
    "gimp-image-set-selected-drawables", "gimp-image-get-selected-drawables",
    # 图像文件名
    "gimp-image-get-file", "gimp-image-get-imported-file", "gimp-image-get-exported-file",
    # GEGL 滤镜的调用途径
    "gegl:gaussian-blur", "gegl:unsharp-mask", "gegl:brightness-contrast",
    "gimp-drawable-append-filter", "gimp-filter-new", "gimp-drawable-merge-filter",
    "gimp-drawable-merge-filters", "gimp-image-merge-filter",
    "gimp-drawable-apply-operation", "script-fu-gegl",
    # 直方图补充
    "gimp-drawable-histogram", "gimp-image-get-histogram",
    # 文字补充
    "gimp-text-font", "gimp-text-layer-new", "gimp-text-layer-set-text",
    "gimp-text-layer-set-font", "gimp-text-layer-set-font-size", "gimp-text-layer-set-color",
    "gimp-fonts-get-list",
    # 色阶/曲线
    "gimp-drawable-levels", "gimp-drawable-curves-spline",
    # 其他可能用到
    "gimp-image-set-active-vectors", "gimp-context-push", "gimp-context-pop",
    "gimp-image-undo-group-start", "gimp-image-undo-group-end",
    "gimp-selection-grow", "gimp-selection-feather", "gimp-image-set-resolution",
]


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


def main():
    with socket.create_connection((HOST, PORT), timeout=30) as sock:
        for name in CANDIDATES:
            err, body = ev(sock, f'(gimp-pdb-procedure-exists "{name}")')
            mark = "存在" if (err == 0 and body.strip() == "(1)") else "缺失"
            print(f"{mark}: {name}")


if __name__ == "__main__":
    main()
