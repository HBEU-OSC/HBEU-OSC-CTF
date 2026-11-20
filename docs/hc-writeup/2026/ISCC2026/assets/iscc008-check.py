#!/usr/bin/env python3
"""
服务连通性与正常提交示例（只负责发包，不含签名构造逻辑）

用法：
  python3 check.py <目标URL> <明文user_data> <hex格式user_data> <token>
    - 某种方式不需要时，对应位置传 "-" 跳过；
    - 明文提交示例：
        python3 check.py http://172.16.8.6 "user=normal&role=normal" - <token>
    - 十六进制字节提交示例：
        python3 check.py http://172.16.8.6 - <user_data_hex> <token>
"""

import sys
import binascii
import requests


def manual_url_encode(data_bytes: bytes) -> str:
    """逐字节 URL 编码，保留 \x00、\x80 等原始字节。"""
    result = []
    for byte in data_bytes:
        if byte == 0x20:
            result.append('+')
        elif 0x21 <= byte <= 0x7E and chr(byte) not in '=&%+':
            result.append(chr(byte))
        else:
            result.append(f'%{byte:02X}')
    return ''.join(result)


def post_user_data(base_url: str, user_data_bytes: bytes, token: str, label: str):
    encoded = manual_url_encode(user_data_bytes)
    body = f"user_data={encoded}&token={token}"
    try:
        resp = requests.post(
            f"{base_url}/auth",
            data=body.encode('latin-1'),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        print(f"[{label}] HTTP {resp.status_code}")
        print(f"[{label}] 响应: {resp.text.strip()}")
        return resp.status_code, resp.text
    except Exception as e:
        print(f"[{label}] 请求异常: {e}")
        return None, str(e)


def main():
    if len(sys.argv) != 5:
        print(__doc__)
        sys.exit(1)

    base_url = sys.argv[1].rstrip('/')
    plain_arg = sys.argv[2]
    hex_arg = sys.argv[3]
    token = sys.argv[4].strip()

    print("=" * 60)
    print("服务提交示例")
    print("=" * 60)

    if plain_arg != "-":
        print("\n[方式1] 明文字符串提交")
        print(f"  user_data(明文) = {plain_arg}")
        print(f"  token            = {token}")
        post_user_data(base_url, plain_arg.encode('latin-1'), token, "方式1")
    else:
        print("\n[方式1] 已跳过")

    if hex_arg != "-":
        print("\n[方式2] 十六进制字符串转字节后提交")
        print(f"  user_data(hex)   = {hex_arg}")
        print(f"  token            = {token}")
        try:
            user_data_bytes = binascii.unhexlify(hex_arg)
        except (binascii.Error, ValueError):
            print("  [错误] 十六进制格式无效，跳过。")
            return
        post_user_data(base_url, user_data_bytes, token, "方式2")
    else:
        print("\n[方式2] 已跳过")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
