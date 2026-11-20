---
title: "ISCC 2026 - Crypto - 口令的 Base64 偏移加密"
type: writeup
date: 2026-11-20
authors:
  - "杨心凌"
competition: "ISCC 2026"
category: "Crypto"
description: "从多组明文-密文对照推断 Base64 编码后的逐位偏移，还原 admin 口令。"
comments: true
---

# 口令的 Base64 偏移加密

> 比赛：ISCC 2026　方向：Crypto　作者：杨心凌
>
> 仅在赛事授权的题目环境中复现。靶场地址已脱敏，Flag 未在公开稿中保留。

## 题目信息

- **题目描述：** 某企业内部管理系统登录页（`/login`）发生数据泄露，泄露数据包含部分用户的用户名、明文密码以及数据库保存的“加密密码”。需要分析口令加密规律，还原管理员 `admin` 的明文口令并登录获取 Flag。
- **附件与环境：** 原稿未附带可分发文件；需要赛事授权的 Web 环境。
- **关键线索：** 题目给出四组明密文对照与标准 Base64 编码表：

  | 用户名 | 明文口令 | 数据库密文 |
  | --- | --- | --- |
  | alice | `123456` | `MUK2RIa9` |
  | bob | `abcdef` | `YXLmdLbt` |
  | charlie | `qwerty` | `cYfogsXA` |
  | dave | `secret` | `c3Xmgrb7` |

  `admin` 的数据库密文为 `MWnsWaHX`。

## 解题思路

密文长度与明文经过 Base64 编码后的长度一致（6 字节明文 → 8 个 Base64 字符），说明加密不是分组密码，更像是“先 Base64、再按位置偏移字符”。

对 `abcdef` 做 Base64：`abcdef` → `YWJjZGVm`，与密文 `YXLmdLbt` 逐位比较，发现第 i 位字符在 Base64 字母表上向后移动了 i 位（0、1、2…7）。用 `123456`、`qwerty`、`secret` 三组数据复核，规律一致；对超过 8 个字符的明文，偏移按 8 循环。

因此解密方式为：对密文逐位向前偏移 `i mod 8`，再做 Base64 解码。

## 分析与复现

### 第一步：验证偏移规律

```python
import base64

ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"

def shift(text, sign=1):
    out = []
    for i, ch in enumerate(text):
        idx = ALPHA.index(ch)
        out.append(ALPHA[(idx + sign * (i % 8)) % 64])
    return "".join(out)

cipher = "YXLmdLbt"
plain_b64 = shift(cipher, -1)
print(plain_b64)                     # YWJjZGVm
print(base64.b64decode(plain_b64))   # b'abcdef'
```

### 第二步：解密 admin 的密文

```python
admin_cipher = "MWnsWaHX"
admin_b64 = shift(admin_cipher, -1)          # MVlpSVBQ
print(admin_b64)
print(base64.b64decode(admin_b64).decode())  # 得到 admin 口令（已脱敏）
```

得到 admin 的明文口令（该环境已下线，口令仅作算法示例）。

## 核心代码

```python
import base64

ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"

def shift(text, sign=1):
    """在 Base64 字母表上按位置偏移字符，sign=+1 加密、-1 解密。"""
    out = []
    for i, ch in enumerate(text):
        idx = ALPHA.index(ch)
        out.append(ALPHA[(idx + sign * (i % 8)) % 64])
    return "".join(out)

def encrypt(password: str) -> str:
    return shift(base64.b64encode(password.encode()).decode(), +1)

def decrypt(cipher: str) -> str:
    return base64.b64decode(shift(cipher, -1)).decode()

assert encrypt("abcdef") == "YXLmdLbt"
# assert decrypt("MWnsWaHX") == "<admin 口令，已按规范脱敏>"
```

规律只对 Base64 结果中不含 `=` 填充的明文成立；遇到带填充的明文时需要额外处理。

## 结果验证

使用 `admin` 与解出的口令登录 `/login`，页面返回管理员会话，随后提交系统给出的 Flag。Flag 按投稿规范未在本文记录。

## 复盘与经验

- **关键知识点：** Base64 字母表、字符置换/偏移、由多组明密文对反推算法。
- **容易踩的坑：** 直接把密文当 Base64 解码只会得到乱码；必须先还原偏移，且注意 8 位循环。
- **后续改进：** 口令不应使用可逆变换或弱编码保存，应使用带盐慢哈希（Argon2id、bcrypt、scrypt）。

## 参考资料

- [RFC 4648 - Base64 编码](https://www.rfc-editor.org/rfc/rfc4648) — Base64 字母表与填充规则。
