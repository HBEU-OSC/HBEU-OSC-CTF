---
title: "ISCC 2026 - Crypto - 横填竖取与 Base64"
type: writeup
date: 2026-11-20
authors:
  - "杨心凌"
competition: "ISCC 2026"
category: "Crypto"
description: "Base64 解码后按每行 6 列做横填竖取的逆变换，还原 32 字节情报短句。"
comments: true
---

# 横填竖取与 Base64

> 比赛：ISCC 2026　方向：Crypto　作者：杨心凌
>
> 仅在赛事授权的题目环境中复现。原稿中的密文与还原结果已按投稿规范处理。

## 题目信息

- **题目描述：** 截获一段可疑的加密字符串，需要分析其加密方式，并还原出约 30 字节的明文情报短句。
- **加密方式：** 明文先“横着”填入固定列数（每行 6 列）的表格，再“竖着”按列读出，最后整体做 Base64 编码。
- **密文：** `R3QwdHRyVSAsb2guOTEgICA6OWducCA6b29pQTIgcmU=`
- **关键线索：** 列数固定为 6；Base64 解码后的长度可用于确定表格行数与各列长度。

## 解题思路

1. 先 Base64 解码，得到长度 32 的中间字符串：`Gt0ttrU ,oh.91   :9gnp :ooiA2 re`。
2. 这个中间串是“竖取”的结果，即按列依次拼接。若明文长度 L=32、每行 6 列，则行数 R=ceil(32/6)=6；最后一列只有前 5 行有字符。
3. 逆变换：按各列实际长度把中间串依次切分、填回对应列，再逐行读取即可得到明文。

## 分析与复现

### 第一步：Base64 解码

```python
import base64

s = "R3QwdHRyVSAsb2guOTEgICA6OWducCA6b29pQTIgcmU="
text = base64.b64decode(s).decode()
print(repr(text))
print(len(text))   # 32
```

输出 `'Gt0ttrU ,oh.91   :9gnp :ooiA2 re'`，长度 32。

### 第二步：还原行列表格

列数 6、行数 6；第 c 列的单元格数等于满足 `r*6+c < 32` 的行数 r，本题各列长度为 `[6,6,5,5,5,5]`。

```python
cols = 6
rows = (len(text) + cols - 1) // cols
lengths = [sum(1 for r in range(rows) if r * cols + c < len(text))
           for c in range(cols)]

grid = [[""] * cols for _ in range(rows)]
pos = 0
for c, ln in enumerate(lengths):       # 按列填入
    for r in range(ln):
        grid[r][c] = text[pos]
        pos += 1

plain = "".join("".join(row) for row in grid)   # 按行读出
print(plain)
```

得到明文：`GU9: At 19:20, go to north pier.`（原稿记录中 `GU9` 为情报代号前缀）。

## 核心代码

```python
import base64

def decode(cipher_b64: str, cols: int = 6) -> str:
    text = base64.b64decode(cipher_b64).decode()
    rows = (len(text) + cols - 1) // cols
    lengths = [sum(1 for r in range(rows) if r * cols + c < len(text))
               for c in range(cols)]
    grid = [[""] * cols for _ in range(rows)]
    pos = 0
    for c, ln in enumerate(lengths):
        for r in range(ln):
            grid[r][c] = text[pos]
            pos += 1
    return "".join("".join(row) for row in grid)

if __name__ == "__main__":
    print(decode("R3QwdHRyVSAsb2guOTEgICA6OWducCA6b29pQTIgcmU="))
```

## 结果验证

脚本输出与题目描述中“约 30 字节英文情报短句”一致，为 32 字符的 `GU9: At 19:20, go to north pier.`，提交后平台判定正确。

## 复盘与经验

- **关键知识点：** 换位密码（transposition）的可逆性；横填竖取与竖填横取互为逆过程。
- **容易踩的坑：** 把中间串按行切分后再做列读取（方向搞反）；忽略最后一行不满导致各列长度不等。
- **后续改进：** 单纯“换位 + Base64”不提供任何密码学安全性，真实系统应使用带认证的加密方案。

## 参考资料

- [Wikipedia - Transposition cipher](https://en.wikipedia.org/wiki/Transposition_cipher) — 换位密码的基本形式。
- [Wikipedia - Base64](https://en.wikipedia.org/wiki/Base64) — 编码规则。
