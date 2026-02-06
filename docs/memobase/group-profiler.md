# 群聊画像工作流 (Memobase 增强版)

本文档描述改造后的群聊画像工作流 (PROFILER_WORKFLOW)，采用**三分支并行策略**最大化利用 Memobase 能力。

## 设计理念

### 消息类型与处理策略

| 消息类型 | 描述 | 处理方式 | 结果 |
|---------|------|---------|------|
| **Bot 对话** | 用户 @Bot → Bot 回复 | `Insert Data` → LLM处理 | Events + Profiles (自动) |
| **旁观消息** | 非 @Bot 的普通发言 | `Add Profile` 直接写入 | Profiles (可控) |
| **群组配置** | 群氛围、个性化要求 | 原有 LLM 分析 | personalizations.json |

---

## Workflow 结构

```
Start (接收 query 变量)
    ↓
Code Node: parse_messages (解析并分类消息)
    ↓
    ├─ [并行分支 A: Bot 对话记忆] ─────────────────────┐
    │   Iteration: 遍历 conversations                  │
    │       ├─ Get or Create User (Memobase)          │
    │       └─ Insert Data (Memobase)                 │  → Buffer → LLM → Events/Profiles
    │                                                 │
    ├─ [并行分支 B: 旁观者画像] ───────────────────────┤
    │   Iteration: 遍历 observations                   │
    │       ├─ Get or Create User (Memobase)          │
    │       └─ LLM: 分析特征                           │
    │       └─ Add Profile (Memobase) × N             │  → Profiles (直接写入)
    │                                                 │
    └─ [并行分支 C: Bot 配置] ─────────────────────────┤
        LLM Node: 群组画像分析 (原有逻辑)               │
            ↓                                         │
        End: 返回 JSON ───────────────────────────────┘  → personalizations.json
```

**并行执行**：三条分支同时进行，互不影响。

---

## Code 节点配置

### 节点：parse_messages

**输入变量**：
- `query`: `{{#sys.query#}}`
- `user`: `{{#sys.user_id#}}` (格式如 `onebotv11+group+123456789` 或 `onebotv11+123456789`)

**代码 (Python)**：

```python
import re
import uuid
from collections import defaultdict

# 使用固定的命名空间 UUID，确保同一 user_id 总是生成相同的 UUID
NAMESPACE_GROUP = uuid.UUID('11111111-1111-1111-1111-111111111111')

def user_id_to_uuid(adapter: str, user_id: str) -> str:
    """将用户 ID 转换为确定性 UUID（包含 adapter 前缀确保跨平台唯一）"""
    combined_id = f"{adapter}:{user_id}"
    return str(uuid.uuid5(NAMESPACE_GROUP, combined_id))

def main(query: str, user: str = "") -> dict:
    """从群聊记录中分类提取消息：对话对 vs 旁观消息"""
    
    # 处理转义的换行符
    query = query.replace('\\n', '\n')
    
    # 从 sys.user 参数提取 adapter 和 group_id
    adapter = "unknown"
    group_id = ""
    if user:
        # 支持 adapter+group+id 和 adapter+id 两种格式
        user_match = re.match(r'^(\w+)\+(?:group\+)?(\d+)', user)
        if user_match:
            adapter = user_match.group(1)
            group_id = user_match.group(2)
    
    # 提取 <chat_history> 内容
    chat_match = re.search(r'<chat_history>(.*?)</chat_history>', query, re.DOTALL)
    if not chat_match:
        return {
            "conversations": [],
            "observations": [],
            "adapter": adapter,
            "group_id": group_id
        }
    
    lines = chat_match.group(1).strip().split('\n')
    
    # 解析消息格式: [timestamp] Nickname(UserID)[AT_BOT][IS_BOT]: content
    # [AT_BOT] 标记: 消息是否 @bot
    # [IS_BOT] 标记: 消息是否来自 Bot (role=assistant)
    # 两者都是可选的
    pattern = r'^\[([^\]]+)\]\s*([^(]+)\((\d+)\)(?:(\[AT_BOT\]))?(?:(\[IS_BOT\]))?:\s*(.*)$'
    messages = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        match = re.match(pattern, line)
        if match:
            timestamp, nickname, user_id, at_bot_marker, is_bot_marker, content = match.groups()
            content = content.strip()
            nickname = nickname.strip()
            if not content or not nickname:
                continue
            
            # 使用标记判断
            is_bot = (is_bot_marker == '[IS_BOT]')
            is_at_bot = (at_bot_marker == '[AT_BOT]')
            
            # 过滤非真实 Bot 回复的消息：
            # - 消息来自 Bot
            # - 昵称包含 "工具"、"系统" 等关键词（如 "工具系统"、"感知系统"）
            # 这些通常是拦截插件、工具系统等产生的中间输出，不是真实对话
            if is_bot:
                 # 简单关键词过滤
                 if any(k in nickname for k in ["工具系统", "感知系统", "拦截系统"]):
                     continue
            
            messages.append({
                "timestamp": timestamp.strip(),
                "nickname": nickname,
                "user_id": user_id,
                "content": content,
                "is_bot": is_bot,
                "is_at_bot": is_at_bot
            })
    
    # 分类：对话对 vs 旁观消息
    conversations = []
    observations_map = defaultdict(list)
    used_bot_replies = set()
    
    for i, msg in enumerate(messages):
        if msg["is_bot"]:
            continue
        
        # 检查这条消息后面是否有 Bot 回复
        bot_reply = None
        bot_reply_idx = None
        for j in range(i + 1, min(i + 5, len(messages))):
            if messages[j]["is_bot"] and j not in used_bot_replies:
                bot_reply = messages[j]
                bot_reply_idx = j
                break
            if not messages[j]["is_bot"] and messages[j]["user_id"] != msg["user_id"]:
                if not messages[j]["is_at_bot"]:
                    break
        
        # 使用明确的 [AT_BOT] 标记来判断是否为对话对
        if bot_reply and msg["is_at_bot"]:
            used_bot_replies.add(bot_reply_idx)
            conversations.append({
                "user_id": user_id_to_uuid(adapter, msg["user_id"]),
                "original_id": msg["user_id"],
                "nickname": msg["nickname"],
                "user_message": f"[{msg['timestamp']}] {msg['content']}",
                "assistant_message": f"[{bot_reply['timestamp']}] {bot_reply['content']}"
            })
        else:
            # 旁观消息
            observations_map[msg["user_id"]].append({
                "timestamp": msg["timestamp"],
                "nickname": msg["nickname"],
                "content": msg["content"]
            })
    
    # 转换 observations 为列表格式
    observations = []
    for original_id, msgs in observations_map.items():
        formatted_messages = "\n".join([
            f"[{m['timestamp']}] {m['content']}" 
            for m in msgs
        ])
        observations.append({
            "user_id": user_id_to_uuid(adapter, original_id),
            "original_id": original_id,
            "adapter": adapter,
            "nickname": msgs[0]["nickname"] if msgs else "",
            "messages": formatted_messages,
            "message_count": len(msgs)
        })
    
    return {
        "conversations": conversations,  # → Insert Data (分支 A)
        "observations": observations,    # → Add Profile (分支 B)
        "adapter": adapter,
        "group_id": group_id
    }
```

**输出变量**：

| 变量名 | 类型 | 描述 | 示例值 |
|--------|------|------|--------|
| `conversations` | Array | Bot 对话对，用于 Insert Data | `[{"user_id": "...", "user_message": "...", "assistant_message": "..."}]` |
| `observations` | Array | 旁观消息，用于 Add Profile | `[{"user_id": "...", "messages": "..."}]` |
| `adapter` | String | 适配器名称 | `onebotv11` |
| `group_id` | String | 群组 ID | `123456789` |
---

## 分支 A：Bot 对话记忆 (Insert Data)

### Iteration 节点配置

**迭代输入**：`{{#parse_messages.conversations#}}`

**内部节点**：

#### 1. Get or Create User (Memobase 工具)
- `user_id`: `{{#item.user_id#}}`

#### 2. Insert Data (Memobase 工具)
- `user_id`: `{{#item.user_id#}}`
- `user_message`: `{{#item.user_message#}}`
- `assistant_message`: `{{#item.assistant_message#}}`

---

## 分支 B：旁观者画像 (Add Profile)

**处理**：`parse_messages.observations`

### 固定槽位法（推荐，简单可靠）

让 LLM 输出固定结构的 JSON，每个 topic 最多一个条目，然后在 Iteration 内用多个 Add Profile 节点处理。

```
Iteration: observations
    ├─ Get or Create User
    ├─ LLM Node: 分析用户特征 → 固定结构 JSON
    ├─ Add Profile (槽位1: 基本信息)  ← 条件执行
    ├─ Add Profile (槽位2: 兴趣爱好)  ← 条件执行
    ├─ Add Profile (槽位3: 交流偏好)  ← 条件执行
    ├─ Add Profile (槽位4: 性格特征)  ← 条件执行
    └─ Add Profile (槽位5: 近期动态)  ← 条件执行
```

#### LLM 节点 System Prompt

```
你是用户画像分析专家。根据用户的群聊发言，提取关键特征。

输出格式（纯 JSON，不要 markdown）：
{
  "基本信息": {"sub_topic": "职业", "content": "学生"} | null,
  "兴趣爱好": {"sub_topic": "游戏", "content": "喜欢玩原神"} | null,
  "交流偏好": {"sub_topic": "回复风格", "content": "喜欢幽默"} | null,
  "性格特征": {"sub_topic": "性格标签", "content": "活跃健谈"} | null,
  "近期动态": {"sub_topic": "关注话题", "content": "最近在讨论过年计划"} | null
}
```

#### Code 节点：解析 LLM 输出

> **兼容性提示**：为了确保 Dify 能稳定读取变量，建议将输出结构展平。

```python
import json

def main(llm_output: str) -> dict:
    """解析 LLM 输出，展平为固定槽位变量"""
    try:
        data = json.loads(llm_output.strip())
    except:
        # 如果解析失败，返回全空
        data = {}
    
    profiles = []
    # 定义我们关心的 topic 顺序，确保槽位对应关系固定（可选）
    target_topics = ["基本信息", "兴趣爱好", "交流偏好", "性格特征", "近期动态"]
    
    # 优先按固定顺序提取，如果 LLM 输出包含该 topic 且非空
    for topic in target_topics:
        value = data.get(topic)
        if value and isinstance(value, dict) and value.get("content"):
            profiles.append({
                "topic": topic,
                "sub_topic": value.get("sub_topic", ""),
                "content": value.get("content", "")
            })
            
            
    # 如果 LLM 输出包含 profiles 列表 (Schema B)
    if not profiles and isinstance(data, dict):
        if "profiles" in data and isinstance(data["profiles"], list):
             profiles = data["profiles"]

    # 如果 LLM 输出了列表格式（兼容旧 prompt），也尝试解析
    if not profiles and isinstance(data, list):
         profiles = data

    # 填充到 5 个固定槽位
    result = {}
    for i in range(5):
        prefix = f"p{i+1}"  # p1, p2, p3...
        if i < len(profiles):
            p = profiles[i]
            result[f"{prefix}_valid"] = True
            result[f"{prefix}_topic"] = p.get("topic", "")
            result[f"{prefix}_sub"] = p.get("sub_topic", "")
            result[f"{prefix}_content"] = p.get("content", "")
        else:
            result[f"{prefix}_valid"] = False
            result[f"{prefix}_topic"] = ""
            result[f"{prefix}_sub"] = ""
            result[f"{prefix}_content"] = ""
            
    return result
```

**输出变量 (Output Variables)**：

为了在 Dify 界面中配置，请手动添加以下变量：

| 变量名 | 类型 | 描述 |
|--------|------|------|
| `p1_valid` | Boolean | 槽位 1 是否有数据 |
| `p1_topic` | String | 槽位 1 的主题（如：基本信息） |
| `p1_sub` | String | 槽位 1 的子主题（如：职业） |
| `p1_content` | String | 槽位 1 的内容 |
| `p2_valid` | Boolean | 槽位 2 是否有数据 |
| `p2_topic` | String | |
| `p2_sub` | String | |
| `p2_content` | String | |
| ... | ... | (直到 p5) |

#### Add Profile 配置（每个槽位一个节点）

在 Workflow 中添加 5 个并行的 `Add Profile` 工具节点，每个节点前加一个条件判断。

**槽位 1 配置**：
- **前置条件**：`{{#code.p1_valid#}}` is `true`
- **User ID**: `{{#item.user_id#}}` (来自 Iteration)
- **Topic**: `{{#code.p1_topic#}}`
- **Sub Topic**: `{{#code.p1_sub#}}`
- **Content**: `{{#code.p1_content#}}`

**槽位 2 配置**：
- **前置条件**：`{{#code.p2_valid#}}` is `true`
- **User ID**: `{{#item.user_id#}}`
- **Topic**: `{{#code.p2_topic#}}`
... (以此类推到 p5)


#### Add Profile 节点配置

- `user_id`: `{{#item.user_id#}}`
- `topic`: `近期动态`
- `sub_topic`: `关注话题`
- `content`: `{{#llm.summary#}}`


---

## 分支 C：Bot 配置 (保持原有逻辑)

### LLM 节点配置

**System Prompt**：参考原有的群组画像分析提示词。

**User Prompt**：`{{#sys.query#}}`

### End 节点

**输出变量**：`{{#llm.text#}}`

---

### 注意事项

1. **UUID 生成规则**：包含 adapter 前缀确保跨平台唯一
2. **Insert Data vs Add Profile**：
   - `Insert Data`：数据进入 Buffer，由 Memobase LLM 异步处理
   - `Add Profile`：立即写入，你完全控制内容
3. **Profile Schema 对齐**：使用的 topic/sub_topic 必须与 Memobase 服务端配置一致

---

## 数据流总结

```
群聊消息
    ↓
┌─────────────────────────────────────────────────────────────┐
│ parse_messages                                              │
├─────────────────────────────────────────────────────────────┤
│ conversations: [{user @Bot → Bot reply}]                    │
│ observations: [{普通发言}]                                   │
└─────────────────────────────────────────────────────────────┘
    ↓                    ↓                    ↓
┌─────────┐        ┌─────────┐        ┌─────────┐
│ 分支 A  │        │ 分支 B  │        │ 分支 C  │
│ Insert  │        │ Add     │        │ LLM     │
│ Data    │        │ Profile │        │ 分析    │
└────┬────┘        └────┬────┘        └────┬────┘
     ↓                  ↓                  ↓
┌─────────┐        ┌─────────┐        ┌─────────┐
│Memobase │        │Memobase │        │ Return  │
│ Buffer  │        │ Profile │        │ JSON    │
│ → LLM   │        │ (直接)  │        │         │
└────┬────┘        └─────────┘        └────┬────┘
     ↓                                     ↓
┌─────────┐                          ┌─────────────────┐
│ Events  │                          │personalizations │
│ +Profiles│                         │    .json        │
└─────────┘                          └─────────────────┘
```
