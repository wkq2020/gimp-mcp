"""探针 4：批量核验 GIMP 3.2.6 PDB 过程名是否存在。"""

import socket

HOST, PORT = "127.0.0.1", 10008
MAGIC = 0x47

CANDIDATES = [
    # 连接与元信息
    "gimp-version", "gimp-get-images", "gimp-image-get-width", "gimp-image-get-height",
    "gimp-image-get-base-type", "gimp-image-get-layers", "gimp-item-get-name",
    "gimp-item-get-visible", "gimp-layer-get-opacity", "gimp-image-get-active-layer",
    "gimp-image-get-selected-drawables", "gimp-displays-flush", "gimp-image-get-filename",
    # 文件
    "gimp-file-load", "gimp-image-new", "gimp-layer-new", "gimp-image-insert-layer",
    "gimp-file-save", "file-png-export", "file-jpeg-export", "file-webp-export",
    "file-tiff-export", "file-gif-export", "gimp-image-flatten",
    # 几何
    "gimp-image-crop", "gimp-image-scale", "gimp-image-resize", "gimp-image-rotate",
    "gimp-image-flip",
    # 选区
    "gimp-image-select-rectangle", "gimp-image-select-ellipse", "gimp-selection-none",
    "gimp-selection-all", "gimp-selection-invert", "gimp-selection-is-empty",
    "gimp-selection-bounds",
    # 填充与上下文
    "gimp-context-set-foreground", "gimp-drawable-edit-fill", "gimp-drawable-fill",
    "gimp-context-set-opacity",
    # 图层
    "gimp-image-remove-layer", "gimp-image-set-active-layer", "gimp-layer-copy",
    "gimp-item-set-name", "gimp-layer-set-opacity", "gimp-layer-set-mode",
    "gimp-image-get-layer-by-name", "gimp-item-get-by-name",
    # 调色与滤镜（2.x 与 3.x 候选名并列）
    "gimp-drawable-brightness-contrast", "gimp-brightness-contrast",
    "gimp-drawable-levels", "gimp-levels",
    "gimp-drawable-hue-saturation", "gimp-hue-saturation",
    "gimp-drawable-desaturate", "gimp-desaturate",
    "plug-in-gauss", "plug-in-unsharp-mask", "gimp-drawable-merge-new-filter",
    # 文字
    "gimp-text-fontname", "gimp-text-font", "gimp-text-layer-new",
    "gimp-text-layer-set-text", "gimp-fonts-get-list", "gimp-layer-set-offsets",
    # 直方图
    "gimp-histogram", "gimp-drawable-histogram",
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
    missing = []
    with socket.create_connection((HOST, PORT), timeout=30) as sock:
        for name in CANDIDATES:
            err, body = ev(sock, f'(gimp-pdb-procedure-exists "{name}")')
            exists = err == 0 and body.strip() == "(1)"
            if not exists:
                missing.append(name)
                print(f"缺失: {name}  (err={err}, {body.strip()!r})")
    print(f"\n共 {len(CANDIDATES)} 个候选，缺失 {len(missing)} 个")
    if missing:
        print("缺失清单:", ", ".join(missing))


if __name__ == "__main__":
    main()
