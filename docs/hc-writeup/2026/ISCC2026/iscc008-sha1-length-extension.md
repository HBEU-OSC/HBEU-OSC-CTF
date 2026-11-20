---
title: "ISCC 2026 - Crypto - SHA1 长度扩展攻击"
type: writeup
date: 2026-11-20
authors:
  - "杨心凌"
competition: "ISCC 2026"
category: "Crypto"
description: "利用 SHA1 长度扩展伪造 admin 身份 token，绕过服务端校验。"
comments: true
---

# SHA1 长度扩展攻击

> 比赛：ISCC 2026　方向：Crypto　作者：杨心凌
>
> 仅在赛事授权的题目环境中复现。Token 与 Flag 已按投稿规范脱敏。

## 题目信息

- **题目描述：** 服务器用 `token = sha1(secret_key + user_data)` 校验身份，`secret_key` 长度 12 字节且未知。题目泄露了一个普通用户的数据与 token，要求伪造 `role=admin` 的请求获取 Flag（flag 为 15 位数字）。
- **附件：** 题目提供提交脚本 [`check.py`](assets/iscc008-check.py)。
- **关键线索：**
  - `secret_key` 长度 12 字节（已知长度是长度扩展攻击的前提）。
  - 泄露数据：`user_data = user=normal&role=normal`
  - 泄露 token：`0f467e2a…f37b`（完整值已按投稿规范脱敏）

## 解题思路

SHA1（以及 MD5）是 Merkle–Damgård 结构：`hash(secret || data)` 的结果只依赖“已处理分组的状态”。已知 `secret` 长度时，可以在 `data` 后拼接 SHA1 填充（`0x80` + 若干 `0x00` + 64 位长度），再把 `&role=admin` 追加到 padding 之后，从已知 digest 继续压缩，得到新的合法 token。

攻击要点：

1. 原 message 长度 = 12（secret）+ 24（user_data）= 36 字节。SHA1 填充后：36 + 1（0x80）+ 19（0x00）= 56，再加 8 字节长度 = 64 字节，正好 1 个分组。
2. 用 HashTools 的 “SHA1 Length Extension”：输入原始 message（不含 secret，但填 secret 长度 12）、原 digest、追加数据 `&role=admin`，得到新 digest 与新 message。
3. 把新 hex message 作为参数提交，服务端拼接 secret 后重新计算 SHA1，得到的正是伪造 token，且 `role` 被解析为 admin。

## 分析与复现

### 第一步：确认长度与分组结构

- secret 长度 = 12
- user_data = `user=normal&role=normal`（24 字节）
- 拼接后 36 字节，SHA1 填充到 64 字节（1 个分组）

### 第二步：HashTools 生成伪造 token

打开 HashTools → SHA1 Length Extension：

- Original message：`user=normal&role=normal`
- Secret length：12
- Append：`&role=admin`

得到新 token：`956a06c8…dac2`（完整值已脱敏）。

### 第三步：构造提交载荷并发送

新 message 的 hex 以 `757365723d6e6f726d616c26726f6c653d6e6f726d616c8000...` 开头（末尾为若干 `0x00` 填充与追加的 `&role=admin`，原稿截断）。

```bash
python check.py http://<靶场地址> - <hex_message> <forged_token>
```

### 第四步：获取 Flag

服务端校验通过并把 `role` 解析为 admin，返回 15 位数字 flag。

## 核心代码

附件 `check.py` 封装了发送逻辑（由原稿的 3.py 复制，未做改动）：

```python
# 见附件 assets/iscc008-check.py
```

手工调用格式：

```bash
python check.py <url> - <hex_payload> <token>
```

## 结果验证

使用伪造 token 提交后，服务端返回管理员身份与 15 位数字 flag，提交平台判定正确。

## 复盘与经验

- **关键知识点：** Merkle–Damgård 结构的长度扩展性质；`secret || data` 直接拼接后哈希不能当 MAC 用。
- **防御措施：** 改用 HMAC（如 `hmac.new(key, msg, hashlib.sha256)`），或采用 SHA-256/512 等更安全的构造；不要把 secret 简单前缀拼接后当签名。
- **注意：** 长度扩展只适用于 `H(key || msg)` 形式；`H(msg || key)` 不适用该攻击。

## 参考资料

- [Wikipedia - Length extension attack](https://en.wikipedia.org/wiki/Length_extension_attack) — 原理与示例。
- [Wikipedia - Merkle–Damgård construction](https://en.wikipedia.org/wiki/Merkle%E2%80%93Damg%C3%A5rd_construction) — 分组哈希结构。
