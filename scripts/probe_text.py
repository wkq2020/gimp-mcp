"""探针 11：GIMP 3.2 字体资源与文字图层流程。"""

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
    print(f"[{'OK ' if err==0 else 'ERR'}] {label or code[:100]}\n      -> {body.decode('utf-8', errors='replace')[:250]!r}")


def main():
    with socket.create_connection((HOST, PORT), timeout=60) as sock:
        for name in ["gimp-font-get-by-name", "gimp-resource-get-by-name",
                     "gimp-resource-get-name", "gimp-resource-id-is-font"]:
            ev(sock, f'(gimp-pdb-procedure-exists "{name}")', f"exists {name}")
        ev(sock, '(gimp-fonts-get-list "Sans")', "fonts-get-list 'Sans'")
        ev(sock, '(gimp-fonts-get-list "")', "fonts-get-list 全部(看形状)")
        ev(sock, '(gimp-font-get-by-name "Sans-serif")', "font-get-by-name")
        ev(sock, '(gimp-resource-get-by-name "gimp-font" "Sans-serif")', "resource-get-by-name")

        ev(sock, """
(let ((img (car (gimp-image-new 200 80 RGB))))
  (let ((l (car (gimp-layer-new img "L" 200 80 RGB-IMAGE 100 LAYER-MODE-NORMAL))))
    (gimp-image-insert-layer img l -1 0)
    (gimp-image-set-selected-layers img (vector l))
    (gimp-drawable-fill l FILL-BACKGROUND)
    img))""", "建图")
        img = "(vector-ref (car (gimp-get-images)) 0)"

        # 用字体资源 ID 调 text-font
        ev(sock, f'(let ((f (car (gimp-font-get-by-name "Sans-serif")))) (gimp-text-font {img} -1 5 5 "测试ABC" 0 TRUE 20 1 f))', "text-font 用字体资源ID")
        # text-font 的 size-type 单位参数候选
        ev(sock, f'(let ((f (car (gimp-font-get-by-name "Sans-serif")))) (gimp-text-font {img} -1 5 40 "px?" 0 TRUE 20 0 f))', "text-font unit=0")
        # 文字层属性
        drw = f"(vector-ref (car (gimp-image-get-selected-drawables {img})) 0)"
        ev(sock, f"(gimp-text-layer-get-text {drw})", "get-text")
        ev(sock, f'(gimp-text-layer-set-color {drw} "#ffffff")', "set-color 字符串")
        ev(sock, f"(gimp-text-layer-set-color {drw} '(255 255 255))", "set-color 列表")
        ev(sock, f"(number->string (car (gimp-drawable-get-width {drw})))", "文字层宽")
        ev(sock, f"(gimp-layer-set-offsets {drw} 100 40)", "set-offsets")
        ev(sock, '(for-each gimp-image-delete (vector->list (car (gimp-get-images))))', "清理")


if __name__ == "__main__":
    main()
