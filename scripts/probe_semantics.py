"""扩展探针：验证实现期需要的 Scheme 求值行为。"""

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
    magic, err, hi, lo = h
    body = recv_exact(sock, (hi << 8) | lo) if (hi or lo) else b""
    print(f"[err={err}] {code[:90]!r}\n    -> {body.decode('utf-8', errors='replace')[:300]!r}")


CASES = [
    # 返回值序列化形式
    '(list 1 "a" 2.5)',
    "'(1 2 3)",
    "(number->string 3.14)",
    '(string-append "a" "b" (number->string 42))',
    # 输出过程是否存在
    "(display \"x\")",
    "(newline)",
    # 结构化输出思路：把结果拼成单一字符串
    '(let ((w 1920) (h 1080)) (string-append (number->string w) "x" (number->string h)))',
    # PDB 过程查询（验证过程名是否存在及签名）
    '(gimp-procedural-db-query ".*" ".*" ".*" ".*" ".*" ".*" "gimp-image-scale")',
    # PDB 调用参数错误时的报错形式
    "(gimp-image-get-width 999)",
    # 无活动图像时取活动图像
    "(gimp-image-get-width (car (gimp-get-images)))",
    # 多行脚本
    "(let* ((a 1)\n       (b 2))\n  (+ a b))",
    # 中文字符串往返
    '(string-append "路径" "测试")',
    # 条件与布尔
    "(if (> 3 2) \"yes\" \"no\")",
    "TRUE",
    # 过程存在性检查的惯用法
    '(if (car (gimp-procedural-db-query ".*" ".*" ".*" ".*" ".*" ".*" "^gimp-image-scale$")) "exists" "missing")',
]


def main():
    with socket.create_connection((HOST, PORT), timeout=30) as sock:
        for c in CASES:
            ev(sock, c)


if __name__ == "__main__":
    main()
