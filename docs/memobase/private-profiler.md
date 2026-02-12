# 私聊画像工作流 (Memobase 增强版)

本文档描述改造后的私聊画像工作流 (PRIVATE_PROFILER_WORKFLOW)，采用**双分支并行策略**。

## 设计理念

| 输出 | 目标存储 | 用途 |
|------|---------|------|
| 时序对话数据 | **Memobase** | 用户画像、长期记忆（跨场景共享） |
| `user_profile` + `personalization_summary` | **personalizations.json** | Bot 行为、个性化配置 |

### 为什么私聊只需要双分支？

与群聊的**三分支结构**（Bot对话 + 旁观消息 + Bot配置）不同，私聊采用**双分支结构**：

| 场景 | 消息类型 | 处理方式 |
|------|---------|---------|
| **群聊** | Bot 对话 (`@Bot → Bot回复`) | Insert Data (分支 A) |
| **群聊** | 旁观消息 (用户没@Bot的普通发言) | Add Profile (分支 B) |
| **群聊** | 群组配置 | LLM 分析 (分支 C) |
| **私聊** | 全部消息 (都是用户与Bot的对话) | HTTP Request 直接调用 API (分支 A) |
| **私聊** | 个人配置 | LLM 分析 (分支 B) |

**关键区别**：
- 群聊中存在"旁观消息"（用户A和用户B聊天，Bot只是旁观），这些消息没有Bot回复，无法通过 Insert Data 处理，需要 Add Profile 分支直接写入
- 私聊中**所有消息都是用户与Bot的对话**，不存在旁观消息，Insert Data 已覆盖全部内容
- 因此私聊**不需要** Add Profile 分支

---

## Workflow 结构

```
Start (接收 query 变量)
    ↓
Code Node: parse_chat_history (提取并转换)
    ↓
    ├─ [并行分支 A: 用户记忆] ────────────────────────┐
    │   Get or Create User (Memobase 插件)           │
    │       ↓                                        │
    │   HTTP Request: Insert Blob (直接调用 API)      │  → 写入 Memobase
    │                                                │
    └─ [并行分支 B: Bot 配置] ────────────────────────┤
        LLM Node: 个人画像分析 (原有逻辑)              │
            ↓                                        │
        End: 返回 JSON ──────────────────────────────┘  → personalizations.json
```

**并行执行**：两条分支同时进行，互不影响。

> **关键改进**: 分支 A 使用 HTTP Request 直接调用 Memobase API，绕过 Dify 插件的单对话限制，支持传入完整的多轮 messages 数组。

---

## 输入 XML 格式

私聊画像工作流接收的 XML 结构示例（由 NoneBot 插件生成）：

```xml
<context>
<user_profile>
用户持续专注于实用信息查询，如麦当劳优惠券等，表现为简洁直接的命令式交流...
</user_profile>

<chat_history>
[2025-03-15T20:30:00.000000] User: 刚刚读完《三体》第三部，结局太致郁了
[2025-03-15T20:30:05.000000] Bot: 是啊，程心这个角色一直很有争议。不过在大宇宙的尺度下，一切或许都是必然。你最触动的情节是哪一段？
[2025-03-15T20:31:10.000000] User: 可能是云天明送的那颗星星吧，跨越光年的浪漫
[2025-03-15T20:31:15.000000] Bot: "送你一颗星星"，确实是极致的浪漫... 同时也承载了极致的责任。那段童话也很精彩！
[2025-03-15T20:32:00.000000] User: 对，童话里的隐喻太深了，没看解析完全不懂
[2025-03-15T20:32:03.000000] Bot: 哈，那正是大刘的厉害之处嘛！要不要我给你找点深度的解析文章看看？
</chat_history>

<personalization>
<previous>
用户偏好结合猫娘角色扮演与功能性互动，需在提供实用信息时保持趣味性...
</previous>
<recent_interactions>
[2025-03-15T20:32:00.000000] User: 对，童话里的隐喻太深了，没看解析完全不懂
[2025-03-15T20:32:03.000000] Bot: 哈，那正是大刘的厉害之处嘛！要不要我给你找点深度的解析文章看看？
</recent_interactions>
</personalization>
</context>
```

**格式说明**：
- `<chat_history>`: **交替排列的完整对话流**，格式 `[timestamp] Role: message`
- 消息已按时间戳排序，User 和 Bot 消息交替出现
- Code 节点会解析并转换格式，同时**过滤非真实 Bot 回复的消息**
  - 只保留昵称为 "Bot" 的 assistant 消息（真实的 Bot 回复）
  - 过滤掉昵称为 "工具系统"、"感知系统" 等的 assistant 消息（拦截插件、工具输出等中间数据）

---

## Code 节点配置

**节点名称**：`parse_chat_history`

**输入变量**：
- `query`: `{{#sys.query#}}`
- `user`: `{{#sys.user#}}` (格式如 `onebotv11+private+123456789`)

**代码 (Python)**：

```python
import re
import uuid
import json
from datetime import datetime

# 示例 UUID，请务必替换为您自己的固定 UUID
NAMESPACE_PRIVATE = uuid.UUID('22222222-2222-2222-2222-222222222222')

def user_id_to_uuid(adapter: str, user_id: str) -> str:
    """将用户 ID 转换为确定性 UUID（包含 adapter 前缀确保跨平台唯一）"""
    combined_id = f"{adapter}:{user_id}"
    return str(uuid.uuid5(NAMESPACE_PRIVATE, combined_id))

def parse_timestamp(ts_str: str) -> datetime:
    """解析时间戳，失败返回最小时间"""
    try:
        return datetime.fromisoformat(ts_str.strip())
    except:
        return datetime.min

def main(query: str, user: str = "") -> dict:
    """解析 XML 输入，提取交替对话并转换为 Memobase 格式"""
    
    # 处理转义的换行符
    query = query.replace('\\n', '\n')
    
    # 从 sys.user 参数提取 adapter 和 user_id
    adapter = "unknown"
    user_id = "unknown"
    if user:
        user_match = re.match(r'^(\w+)\+private\+(\d+)', user)
        if user_match:
            adapter = user_match.group(1)
            user_id = user_match.group(2)
    
    # 提取 <chat_history> 内容（已经是交替排列的）
    chat_match = re.search(r'<chat_history>(.*?)</chat_history>', query, re.DOTALL)
    chat_history_raw = chat_match.group(1).strip() if chat_match else ""
    
    # 解析交替对话到 OpenAI 兼容的 messages 数组
    messages = []
    
    # 匹配格式: [timestamp] Role: message 或 [timestamp] ROLE nickname: message
    pattern = r'\[([^\]]+)\]\s*(User|Bot|Assistant|USER|BOT|ASSISTANT)(?:\s+(\w+))?:\s*(.+?)(?=\n\[|\Z)'
    
    for match in re.finditer(pattern, chat_history_raw, re.DOTALL | re.IGNORECASE):
        timestamp_str, role, nickname, content = match.groups()
        content = content.strip()
        if not content:
            continue
            
        # 标准化角色名称
        normalized_role = "user" if role.lower() == "user" else "assistant"
        
        # 过滤非真实 Bot 回复的 assistant 消息
        if normalized_role == "assistant" and nickname and nickname != "Bot":
            continue
        
        messages.append({
            "role": normalized_role,
            "content": content,
            "created_at": timestamp_str.strip()
        })
    
    # 如果还没有 user_id，尝试从消息中提取
    if user_id == "unknown" and chat_history_raw:
        nickname_match = re.search(r'USER\s+([^:]+):', chat_history_raw, re.IGNORECASE)
        if nickname_match:
            user_id = nickname_match.group(1).strip()
    
    # 构建对话流程概览（用于调试/日志）
    conversation_flow = " → ".join([
        f"{'U' if m['role'] == 'user' else 'A'}[{m.get('created_at', '')[:10]}]"
        for m in messages[:10]
    ])
    
    memobase_user_id = user_id_to_uuid(adapter, user_id) if user_id != "unknown" else user_id
    
    # 构建 Memobase API 请求体（用于 HTTP Request 节点）
    # 注意: 必须使用 ensure_ascii=True，否则 Dify HTTP Request 节点
    # 发送含中文的 body 时会报 'ascii' codec 编码错误
    insert_blob_body = json.dumps({
        "blob_type": "chat",
        "blob_data": {
            "messages": messages
        }
    }, ensure_ascii=True)
    
    return {
        "user_id": memobase_user_id,
        "original_id": user_id,
        "adapter": adapter,
        "messages": messages,
        "messages_json": json.dumps(messages, ensure_ascii=False),
        "insert_blob_body": insert_blob_body,  # HTTP Request 请求体
        "message_count": len(messages),
        "conversation_flow": conversation_flow
    }
```

**输出变量**：

| 变量名 | 类型 | 描述 |
|--------|------|------|
| `user_id` | String | UUID 格式的 Memobase 用户 ID |
| `original_id` | String | 原始用户 ID |
| `adapter` | String | 适配器名称 |
| `messages` | Array | OpenAI 兼容的 messages 数组 |
| `messages_json` | String | messages 的 JSON 字符串格式 |
| `insert_blob_body` | String | **HTTP Request 请求体** (含 blob_type + blob_data) |
| `message_count` | Number | 总消息数 |
| `conversation_flow` | String | 对话流程概览（调试用） |

---


## 分支 A 配置：用户记忆

### 1. Get or Create User (Memobase 插件)
- `user_id`: `{{#parse_chat_history.user_id#}}`

### 2. HTTP Request: Insert Blob

> **为什么不用插件？** Dify Memobase 插件的 `Insert Data` 只接受 `user_message` + `assistant_message` 两个字符串，固定创建仅含 2 条消息的 ChatBlob。私聊需要插入完整的多轮对话（8+ 条消息），因此绕过插件直接调用 Memobase API。

**节点类型**：HTTP Request

**配置**：

| 项目 | 值 |
|------|----|
| Method | `POST` |
| URL | `http://<MEMOBASE_HOST>:8019/api/v1/blobs/insert/{{#parse_chat_history.user_id#}}` |
| Authorization | Bearer Type: `<MEMOBASE_API_KEY>` |
| Headers | Content-Type: `application/json` |
| Body Type | Raw (JSON) |
| Body | `{{#parse_chat_history.insert_blob_body#}}` |
| Timeout | 30s |

> **注意**：配置时请手动输入各字段值，避免从文档复制粘贴（可能引入不可见字符导致编码错误）。

**请求体格式**（由 Code 节点自动生成）：
```json
{
  "blob_type": "chat",
  "blob_data": {
    "messages": [
      {"role": "user", "content": "你好", "created_at": "03-15 20:30"},
      {"role": "assistant", "content": "你好呀！", "created_at": "03-15 20:30"},
      {"role": "user", "content": "今天天气怎么样", "created_at": "03-15 20:31"},
      {"role": "assistant", "content": "今天晴天~", "created_at": "03-15 20:31"}
    ]
  }
}
```

**成功响应**：
```json
{"data": {"id": "<blob_id>", "chat_results": []}, "errno": 0, "errmsg": ""}
```

> **私聊优势**：私聊包含完整的多轮 user + assistant 交替对话，Memobase 可以最准确地提取记忆和事件。

---

## 分支 B 配置：Bot 配置 (保持原有逻辑)

### System Prompt

```
# 角色
你是一位对话分析、个人行为建模和用户偏好总结方面的专家，擅长从对话中挖掘用户的性格特征、兴趣偏好和沟通习惯。

# 任务
根据用户提示中提供的私聊上下文信息，更新该用户的个人画像，并总结其个性化偏好要求。你的输出**必须**是一个有效的 JSON 对象。

# 输出 JSON 模式
你的输出**必须**是一个有效的 JSON 对象，且只能包含 JSON 内容，前后不得添加任何文本。结构如下：
{
  "user_profile": "<更新后的个人画像文本>",
  "personalization_summary": "<更新后的个性化偏好摘要文本>"
}

# 指令
1. **个人画像更新**：分析用户的兴趣爱好、性格特征、交流习惯、对AI的态度。
2. **个性化偏好总结**：提取显性要求和隐性偏好。
3. 如果没有足够的新信息，可以保留原画像/摘要，或对该字段返回空字符串。
4. 确保最终输出是纯 JSON 对象，严禁包含 Markdown 代码块标记。
```

### User Prompt

```
{{#sys.query#}}
```

---

## End 节点配置

**输出变量**：`{{#llm.text#}}`

> Memobase 写入结果不需要返回给 NoneBot，只需保证 LLM 分析结果正常返回。

---

## 数据流总结

```
NoneBot 私聊消息记录 (已按时间排序)
    ↓
┌─────────────────────────────────────────────────────────────┐
│ limit_private_chat_history_length()                         │
├─────────────────────────────────────────────────────────────┤
│ 输出: "[Time1] User: ...\n[Time2] Bot: ...\n..."            │
│       (交替排列的完整对话流)                                  │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ parse_chat_history (Dify Code Node)                         │
├─────────────────────────────────────────────────────────────┤
│ 1. 提取 <chat_history> 内容                                  │
│ 2. 解析为 OpenAI 兼容的 messages 数组                         │
│ 3. 生成 user_id (UUID)                                       │
│ 4. 构建 insert_blob_body (HTTP 请求体 JSON)                  │
└─────────────────────────────────────────────────────────────┘
    ↓                              ↓
┌──────────────┐             ┌─────────────┐
│  分支 A      │             │  分支 B     │
│  HTTP Req    │             │  LLM 分析   │
│  Insert Blob │             │             │
└──────┬───────┘             └──────┬──────┘
       ↓                            ↓
┌─────────────┐              ┌──────────────────┐
│ Memobase    │              │ Return JSON      │
│ Buffer      │              │                  │
│ → LLM处理   │              └────────┬─────────┘
└──────┬──────┘                       ↓
       ↓                     ┌──────────────────┐
┌─────────────┐              │ personalizations │
│ Events +    │              │     .json        │
│ Profiles    │              └──────────────────┘
└─────────────┘
```

---

## 与群聊画像工作流的区别

| 方面 | 私聊 | 群聊 |
|------|------|------|
| 用户数量 | 单用户 | 多用户 |
| Iteration 节点 | 不需要 | 需要（遍历用户） |
| 消息来源 | `<chat_history>` (交替) | `<chat_history>` (交替) |
| 写入方式 | HTTP Request (完整多轮) | Insert Data 插件 (单对话对) |
| 对话配对 | 直接使用 | 检测 @Bot → Bot reply |
| 旁观消息处理 | 无（都是对话） | Add Profile 直接写入 |
| UUID 命名空间 | `NAMESPACE_PRIVATE` | `NAMESPACE_GROUP` |
