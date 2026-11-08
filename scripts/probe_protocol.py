"""Script-Fu Server 线路协议探针。

用途：实测 GIMP 3 Script-Fu Server 的真实帧格式（任务书第 5 节要求以实测为准）。
运行前提：GIMP 的 Script-Fu Server 已在 127.0.0.1:10008 监听。
"""

import socket
import sys

HOST, PORT = "127.0.0.1", 10008
MAGIC = 0x47  # 'G'


def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("连接被对端关闭")
        buf.extend(chunk)
    return bytes(buf)


def probe(sock: socket.socket, code: str) -> None:
    payload = code.encode("utf-8")
    # 按参考资料的假设帧格式：3 字节请求头 'G' + 2 字节大端长度
    header = bytes([MAGIC, (len(payload) >> 8) & 0xFF, len(payload) & 0xFF])
    sock.sendall(header + payload)
    # 按假设读取 4 字节响应头：'G' + 1 字节错误码 + 2 字节大端长度
    resp_header = recv_exact(sock, 4)
    magic, err, hi, lo = resp_header
    print(f"  请求: {code!r}")
    print(f"  响应头原始字节: {resp_header.hex(' ')}  (magic={magic:#04x}, err={err}, len={(hi << 8) | lo})")
    body = recv_exact(sock, (hi << 8) | lo) if (hi or lo) else b""
    print(f"  响应体: {body.decode('utf-8', errors='replace')!r}")
    print()


def main() -> None:
    with socket.create_connection((HOST, PORT), timeout=30) as sock:
        print(f"已连接 {HOST}:{PORT}\n")
        print("== 用例1：算术 ==")
        probe(sock, "(+ 1 2)")
        print("== 用例2：GIMP 版本 ==")
        probe(sock, "(gimp-version)")
        print("== 用例3：错误表现（不存在的过程） ==")
        probe(sock, "(gimp-this-procedure-does-not-exist 1)")
        print("== 用例4：打印输出 ==")
        probe(sock, '(begin (print "你好 Script-Fu") (print "second"))')
        print("== 用例5：同连接第二次请求（验证连接复用） ==")
        probe(sock, "(* 6 7)")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ConnectionError) as exc:
        print(f"探针失败: {exc}", file=sys.stderr)
        sys.exit(1)
