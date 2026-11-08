"""探针 10：调色/滤镜/文字/蒙版相关签名与取值范围实测。"""

import socket

HOST, PORT, MAGIC = "127.0.0.1", 10008, 0x47


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
    print(f"[{'OK ' if err==0 else 'ERR'}] {label or code[:100]}\n      -> {body.decode('utf-8', errors='replace')[:200]!r}")


def main():
    with socket.create_connection((HOST, PORT), timeout=60) as sock:
        ev(sock, """
(let ((img (car (gimp-image-new 100 60 RGB))))
  (let ((l (car (gimp-layer-new img "L" 100 60 RGB-IMAGE 100 LAYER-MODE-NORMAL))))
    (gimp-image-insert-layer img l -1 0)
    (gimp-image-set-selected-layers img (vector l))
    (gimp-drawable-fill l FILL-BACKGROUND)
    img))""", "建图")
        img = "(vector-ref (car (gimp-get-images)) 0)"
        drw = f"(vector-ref (car (gimp-image-get-selected-drawables {img})) 0)"

        # 亮度对比度：直接 PDB 调用的取值范围探测
        ev(sock, f"(gimp-drawable-brightness-contrast {drw} 50 20)", "brightness 50 (若范围-1..1会报错)")
        ev(sock, f"(gimp-drawable-brightness-contrast {drw} 0.2 0.1)", "brightness 0.2")
        # 色相饱和度签名（2.10: drawable hue-range hue-offset saturation lightness overlap）
        ev(sock, f"(gimp-drawable-hue-saturation {drw} 0 10 20 0 0)", "hue-sat 6参")
        # levels（已确认 9 参）
        ev(sock, f"(gimp-drawable-levels {drw} 0 0.0 1.0 TRUE 1.2 0.0 1.0 TRUE)", "levels gamma1.2")
        # unsharp GEGL 键名
        ev(sock, f'(gimp-drawable-merge-new-filter {drw} "gegl:unsharp-mask" 0 LAYER-MODE-REPLACE 1.0 "std-dev" 2.0 "scale" 0.5 "threshold" 0.0)', "unsharp std-dev/scale/threshold")
        # 文字：gimp-text-font 2.10 签名 (img drawable x y text border antialias size unit fontname)
        ev(sock, f'(gimp-text-font {img} -1 5 5 "测试ABC" 0 TRUE 20 1 "Sans-serif")', "text-font 2.10式 (unit=1?)")
        # 文字颜色与图层尺寸/偏移
        ev(sock, f"(gimp-text-layer-set-color (car (gimp-image-get-selected-drawables {img})) \"#ffffff\")", "text-layer-set-color")
        ev(sock, f"(number->string (car (gimp-drawable-get-width (car (gimp-image-get-selected-drawables {img})))))", "drawable-get-width")
        # 蒙版常量与过程
        for name in ["gimp-layer-create-mask", "gimp-layer-add-mask", "gimp-image-merge-down",
                     "gimp-selection-is-empty", "gimp-drawable-get-width", "gimp-drawable-get-height",
                     "gimp-text-layer-get-text", "gimp-layer-set-offsets"]:
            ev(sock, f'(gimp-pdb-procedure-exists "{name}")', f"exists {name}")
        ev(sock, "(gimp-layer-create-mask 1 4)", "create-mask type4(SELECTION) 无效图层仅看类型错")
        # 清理
        ev(sock, '(for-each gimp-image-delete (vector->list (car (gimp-get-images))))', "清理")


if __name__ == "__main__":
    main()
