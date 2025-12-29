# nonebot-plugin-dify

## 📖 介绍

基于 [NoneBot2](https://github.com/nonebot/nonebot2)，该插件用于对接LLMOps平台[Dify](https://github.com/langgenius/dify)。

## 💿 安装

### 使用 nb-cli 安装

在 nonebot2 项目的根目录下打开命令行, 输入以下指令即可安装

```bash
nb plugin install nonebot-plugin-dify
```

如果需要使用**主动介入（Proactive Mode）**功能，请安装额外依赖：

```bash
pip install "nonebot-plugin-dify[proactive]"
```

### 使用包管理器安装

在 nonebot2 项目的插件目录下, 打开命令行, 根据你使用的包管理器, 输入相应的安装命令

如pip

```bash
pip install nonebot-plugin-dify
```

如果需要使用**主动介入（Proactive Mode）**功能，请安装额外依赖：

```bash
pip install "nonebot-plugin-dify[proactive]"
```

然后打开 nonebot2 项目根目录下的 `pyproject.toml` 文件, 在 `[tool.nonebot]` 部分追加写入

```toml
plugins = ["nonebot_plugin_dify"]
```

## ⚙️ 配置

在 nonebot2 项目的`.env`文件中添加下表中的配置

### 核心配置

| 配置项 | 必填 |          默认值           | 说明 |
|:-----:|:----:|:----------------------:|:----------------------------------------------------------------:|
| DIFY_API_BASE | 否 | https://api.dify.ai/v1 | DIFY API地址，支持自建 |
| DIFY_MAIN_APP_API_KEY | 是 |          N/A           | DIFY主APP的API KEY |
| DIFY_MAIN_APP_TYPE | 否 |        chatbot         | DIFY主APP的类型：chatbot/chatflow，agent，workflow |
| DIFY_TIMEOUT_IN_SECONDS | 否 |           90           | DIFY接口超时时间（单位秒） |

### 会话管理

| 配置项 | 必填 |          默认值           | 说明 |
|:-----:|:----:|:----------------------:|:----------------------------------------------------------------:|
| SESSION_MAX_MESSAGES | 否 |           20           | 会话最大消息数，超过后清空会话 |
| SESSION_EXPIRES_SECONDS | 否 |          3600          | 会话过期时间（单位秒） |
| SESSION_SHARE_IN_GROUP | 否 |         False          | 是否在群组里共享同一个session<br />注意：在开启群聊记录后，该选项无效果 |

### 消息处理

| 配置项 | 必填 |          默认值           | 说明 |
|:-----:|:----:|:----------------------:|:----------------------------------------------------------------:|
| IGNORE_PREFIX | 否 |        ["/", "."]        | 忽略词，指令以这些前缀开头不会触发回复 |
| MESSAGE_MAX_LENGTH | 否 |          200           | 记录单条聊天消息的最大长度 |
| MESSAGE_DESENSITIZATION_ENABLE | 否 |          True          | 是否开启消息脱敏功能 |

### 图片上传

| 配置项 | 必填 |          默认值           | 说明 |
|:-----:|:----:|:----------------------:|:----------------------------------------------------------------:|
| IMAGE_UPLOAD_ENABLE | 否 |         False          | 是否开启上传图片，需要LLM模型支持图片识别，<br />同时需要nonebot_plugin_alconna支持相应Adapter |
| IMAGE_CACHE_DIR | 否 |         "image"        | 图像缓存的子目录 |

### 群聊设置

| 配置项 | 必填 |          默认值           | 说明 |
|:-----:|:----:|:----------------------:|:----------------------------------------------------------------:|
| GROUP_CHAT_HISTORY_LIMIT | 否 |           10           | 个性化回复时在群聊中获取最近消息记录的条数 |
| GROUP_CHAT_HISTORY_SIZE | 否 |          1024          | 个性化回复时在群聊中获取最近消息记录的最大长度 |

### 用户画像

| 配置项 | 必填 |          默认值           | 说明 |
|:-----:|:----:|:----------------------:|:----------------------------------------------------------------:|
| PROFILER_WORKFLOW_API_KEY | 否 |                        | 用于生成群组画像和个性化要求的Dify工作流API Key |
| PRIVATE_PROFILER_WORKFLOW_API_KEY | 否 |                        | 用于生成私聊个人画像的Dify工作流API Key，如不配置则默认使用PROFILER_WORKFLOW_API_KEY |
| PROFILER_SCHEDULE | 否 |       0 3 * * *        | 执行群组画像和个性化要求生成的定时任务触发器，默认为每天凌晨3点 |
| PROFILER_SCHEDULE_JITTER | 否 |           10           | 在计划开始后，将任务随机分布在多少分钟内执行，0表示禁用 |
| PROFILER_HISTORY_LIMIT | 否 |           50           | 生成画像时分析的最近历史记录条数 |
| PROFILER_MIN_MESSAGES | 否 |           10           | 生成画像所需的最少有效消息条数 |
| PROFILER_CHAT_HISTORY_SIZE | 否 |          1024          | 生成画像允许的聊天消息的最大长度 |

### 个性化设置

| 配置项 | 必填 |          默认值           | 说明 |
|:-----:|:----:|:----------------------:|:----------------------------------------------------------------:|
| DEFAULT_PERSONALIZATION | 否 |     "你叫喵喵，是一位..."      | 当群组首次启用画像功能时，应用的默认个性化描述 |

### 私聊设置

| 配置项 | 必填 |          默认值           | 说明 |
|:-----:|:----:|:----------------------:|:----------------------------------------------------------------:|
| PRIVATE_PERSONALIZATION_ENABLE | 否 |         False          | 是否启用私聊个性化功能 |
| PRIVATE_CHAT_HISTORY_LIMIT | 否 |           20           | 私聊个性化回复时获取最近消息记录的条数 |
| PRIVATE_CHAT_HISTORY_SIZE | 否 |          2048          | 私聊个性化回复时获取最近消息记录的最大长度 |
| PRIVATE_PROFILER_MIN_MESSAGES | 否 |           15           | 生成私聊用户画像所需的最少有效消息条数 |
| PRIVATE_PROFILER_SCHEDULE | 否 |       0 4 * * *        | 执行私聊用户画像生成的定时任务触发器，默认为每天凌晨4点 |
| PRIVATE_PROFILER_SCHEDULE_JITTER | 否 |           10           | 在计划开始后，将任务随机分布在多少分钟内执行，0表示禁用 |
| PRIVATE_DATA_RETENTION_DAYS | 否 |           90           | 私聊用户数据保留天数，超过此时间的数据将被自动清理 |

### 余韵模式 (Linger Mode)

开启此模式后，当机器人在群聊中被 @ 提到后，会在接下来的一段时间内，自动响应群内的后续消息，无需再次 @。

这模拟了更自然的对话流，让用户在连续对话时不必每次都艾特机器人。

- **礼仪原则**: 为了不打扰用户之间的私下交流，如果某条消息**明确指向他人**（例如 @ 了其他人，或是回复了其他人的消息），机器人即使处于余韵窗口内也会保持静默。
- **静默机制**: 如果你不希望机器人在这段时间内回复某些无意义的消息，可以在 Dify 的 Prompt 中指示它输出 `<IGNORE>` 或返回空内容。插件会自动检测并静默，且不消耗余韵次数。

| 配置项 | 必填 |          默认值           | 说明 |
|:-----:|:----:|:----------------------:|:----------------------------------------------------------------:|
| LINGER_MODE_ENABLE | 否 |         False          | 是否启用余韵模式，被艾特后一段时间内无需再艾特 |
| LINGER_TIMEOUT_SECONDS | 否 |           180           | 余韵模式持续时间（秒） |
| LINGER_MAX_MESSAGES | 否 |           3           | 余韵模式下连续回复的最大消息数 |
| LINGER_RESPONSE_PROBABILITY | 否 |           0.7           | 余韵模式回复概率(0.0-1.0)，降低此值可减少回复频率 |
| LINGER_MIN_INTERVAL_SECONDS | 否 |           10           | 余韵模式最小回复间隔(秒)，避免刷屏 |

### 主动介入模式 (Proactive Intervention)

开启此模式后，机器人可以在未被 @ 的情况下，根据聊天内容的主题相关性自动参与群聊。
为了保证体验自然且不造成打扰，我们设计了四重过滤机制：语义匹配、礼仪过滤、随机概率和冷却时间。

- **语义匹配**: 使用轻量级向量模型 (`BAAI/bge-small-zh-v1.5`) 分析聊天内容，只有当话题与预设的 `PROACTIVE_INTERESTS` 高度相关时才触发。
- **礼仪过滤**: 机器人**绝不介入**他人之间的定向对话（@他人或回复他人）。
- **冷场保护**: 即使话题相关，机器人也会默认等待一段时间（`PROACTIVE_SILENCE_WAITING_SECONDS`），确认没有其他人回复（即发生冷场）时才会介入。
- **连贯对话**: 主动介入成功后，机器人会自动进入**余韵模式**，方便用户继续与之交流。
- **静默协议**: 最终决定权在 AI 手中。如果 AI 认为此时不适合插话，它会保持沉默。

| 配置项 | 必填 |          默认值           | 说明 |
|:-----:|:----:|:----------------------:|:----------------------------------------------------------------:|
| PROACTIVE_MODE_ENABLE | 否 |         False          | 是否启用主动介入模式 |
| PROACTIVE_MODEL_NAME | 否 | "BAAI/bge-small-zh-v1.5" | 语义匹配模型名称 |
| PROACTIVE_HF_MIRROR | 否 | "https://hf-mirror.com" | HuggingFace镜像地址，用于国内下载模型 |
| PROACTIVE_INTERESTS | 否 |           []           | 机器人感兴趣的话题列表 (例如 `['AI', 'Python', '动漫']`) |
| PROACTIVE_SEMANTIC_THRESHOLD | 否 |          0.8           | 语义相似度阈值 (0.0-1.0)，越高越严格 |
| PROACTIVE_LIKELIHOOD | 否 |          1.0           | 触发概率 (0.0-1.0)，建议设为 0.5-0.7 以增加随机感 |
| PROACTIVE_COOLDOWN_SECONDS | 否 |          1800          | 主动介入的冷却时间 (秒)，默认30分钟 |
| PROACTIVE_SILENCE_WAITING_SECONDS | 否 |          120           | 触发前的观察静默期 (秒)，期间若有人发言则取消介入 |

### 管理配置

| 配置项 | 必填 |          默认值           | 说明 |
|:-----:|:----:|:----------------------:|:----------------------------------------------------------------:|
| SYSTEM_ADMIN_USER_ID | 否 |          None          | 系统管理员的“完整用户ID”，用于赋予指定用户全局管理员权限。<br />支持多个ID，用逗号分隔。<br />管理员可以无视平台角色限制，使用如 `/record` 和 `/profiler` 等命令。<br />私聊机器人发送 `/get_my_id` 可获取自己的ID。 |

### 配置迁移指南

> **重要更新**: 为了提供更清晰的配置体验，我们重新设计了配置变量的命名。旧的配置变量仍然支持，但会显示弃用警告。

#### 快速迁移步骤

1. **无需立即行动**: 现有配置继续有效，系统会自动处理兼容性
2. **逐步迁移**: 可以按自己的节奏更新配置文件
3. **关注警告**: 注意系统日志中的弃用警告
4. **测试验证**: 更新配置后测试功能是否正常

#### 配置示例

**旧配置 (仍然支持)**:
```env
DIFY_CONVSERSATION_MAX_MESSAGES=30
DIFY_EXPIRES_IN_SECONDS=7200
DIFY_SHARE_SESSION_IN_GROUP=true
DIFY_IGNORE_PREFIX=["/", ".", "!"]
DIFY_IMAGE_UPLOAD_ENABLE=true
DIFY_PROFILER_WORKFLOW_API_KEY=workflow-key
```

**新配置 (推荐)**:
```env
SESSION_MAX_MESSAGES=30
SESSION_EXPIRES_SECONDS=7200
SESSION_SHARE_IN_GROUP=true
IGNORE_PREFIX=["/", ".", "!"]
IMAGE_UPLOAD_ENABLE=true
PROFILER_WORKFLOW_API_KEY=workflow-key
```

<details>
<summary>点击查看完整的配置变量映射表</summary>

| 旧配置变量 | 新配置变量 | 状态 |
|:-----:|:-----:|:-----:|
| DIFY_API_KEY | DIFY_MAIN_APP_API_KEY | 已弃用 |
| DIFY_APP_TYPE | DIFY_MAIN_APP_TYPE | 已弃用 |
| DIFY_CONVSERSATION_MAX_MESSAGES | SESSION_MAX_MESSAGES | 已弃用 |
| DIFY_EXPIRES_IN_SECONDS | SESSION_EXPIRES_SECONDS | 已弃用 |
| DIFY_SHARE_SESSION_IN_GROUP | SESSION_SHARE_IN_GROUP | 已弃用 |
| DIFY_IGNORE_PREFIX | IGNORE_PREFIX | 已弃用 |
| DIFY_SINGLE_CHAT_LIMIT | MESSAGE_MAX_LENGTH | 已弃用 |
| DIFY_DESENSITIZATION_ENABLE | MESSAGE_DESENSITIZATION_ENABLE | 已弃用 |
| DIFY_IMAGE_UPLOAD_ENABLE | IMAGE_UPLOAD_ENABLE | 已弃用 |
| DIFY_IMAGE_CACHE_DIR | IMAGE_CACHE_DIR | 已弃用 |
| DIFY_GROUP_CHAT_HISTORY_LIMIT | GROUP_CHAT_HISTORY_LIMIT | 已弃用 |
| DIFY_GROUP_CHAT_HISTORY_SIZE | GROUP_CHAT_HISTORY_SIZE | 已弃用 |
| DIFY_PROFILER_WORKFLOW_API_KEY | PROFILER_WORKFLOW_API_KEY | 已弃用 |
| DIFY_PROFILER_HISTORY_LIMIT | PROFILER_HISTORY_LIMIT | 已弃用 |
| DIFY_PROFILER_MIN_MESSAGES | PROFILER_MIN_MESSAGES | 已弃用 |
| DIFY_PROFILER_CHAT_HISTORY_SIZE | PROFILER_CHAT_HISTORY_SIZE | 已弃用 |
| DIFY_PROFILER_SCHEDULE | PROFILER_SCHEDULE | 已弃用 |
| DIFY_DEFAULT_PERSONALIZATION | DEFAULT_PERSONALIZATION | 已弃用 |
| DIFY_PRIVATE_PERSONALIZATION_ENABLE | PRIVATE_PERSONALIZATION_ENABLE | 已弃用 |
| DIFY_PRIVATE_CHAT_HISTORY_LIMIT | PRIVATE_CHAT_HISTORY_LIMIT | 已弃用 |
| DIFY_PRIVATE_CHAT_HISTORY_SIZE | PRIVATE_CHAT_HISTORY_SIZE | 已弃用 |
| DIFY_PRIVATE_PROFILER_MIN_MESSAGES | PRIVATE_PROFILER_MIN_MESSAGES | 已弃用 |
| DIFY_PRIVATE_PROFILER_SCHEDULE | PRIVATE_PROFILER_SCHEDULE | 已弃用 |
| DIFY_PRIVATE_DATA_RETENTION_DAYS | PRIVATE_DATA_RETENTION_DAYS | 已弃用 |
| DIFY_API_MAX_RETRIES | API_MAX_RETRIES | 已弃用 |
| DIFY_API_RETRY_BASE_DELAY | API_RETRY_BASE_DELAY | 已弃用 |
| DIFY_API_RETRY_MAX_DELAY | API_RETRY_MAX_DELAY | 已弃用 |
| DIFY_API_CIRCUIT_BREAKER_THRESHOLD | API_CIRCUIT_BREAKER_THRESHOLD | 已弃用 |
| DIFY_API_CIRCUIT_BREAKER_TIMEOUT | API_CIRCUIT_BREAKER_TIMEOUT | 已弃用 |
| DIFY_API_BATCH_SIZE | API_BATCH_SIZE | 已弃用 |
| DIFY_API_BATCH_DELAY | API_BATCH_DELAY | 已弃用 |

</details>

## 🎉 使用

### 命令
- `/get_my_id` - (私聊)获取您的跨平台唯一ID
- `/clear` - 清除Dify历史上下文
- `/help` - 显示帮助信息
- `/record [on/off/check]` - (管理员)开启/关闭/查看当前群聊记录状态
- `/profiler [on/off/check]` - (管理员)开启/关闭/查看当前群组的用户画像功能
- `/personalize [on/off/check]` - (私聊)启用/禁用/查看私聊个性化功能
- `/profile` - (私聊)查看个人档案和对话统计
- `/reset_profile [confirm]` - (私聊)重置个人档案数据

## ✨ 高级功能：智能个性化系统

本插件提供了两套强大的个性化功能，让你的 AI Bot 拥有真正的"记忆"和"性格"：

### 🏠 私聊个性化功能

**全新功能！** 为每个用户提供完全个性化的私聊体验：

- **个人档案生成**: 通过分析用户的对话历史，AI 自动生成用户的兴趣、偏好和交流风格档案
- **个性化回复**: 基于用户档案和历史对话，提供高度定制化的回复
- **隐私保护**: 用户完全控制自己的数据，可随时启用/禁用功能并清除所有数据
- **智能学习**: 随着对话的增加，AI 会不断学习和优化对用户的理解

**使用方法**:
1. 在 `.env` 中设置 `PRIVATE_PERSONALIZATION_ENABLE=true`
2. 用户在私聊中发送 `/personalize on` 启用个性化功能
3. 开始正常对话，AI 会逐渐学习用户的偏好
4. 使用 `/profile` 查看个人档案，使用 `/reset_profile confirm` 重置数据

### 👥 群组画像与个性化

通过定时分析群聊内容，动态构建**群组画像 (Group Profile)** 与 **个性化要求 (Personalization)**：

- **群组画像**: 分析群组的主要话题、氛围和整体特征
- **群成员图谱**: 自动识别活跃成员和机器人(Bot)的行为特征
- **个性化要求**: 总结群组成员对 AI 行为的期望和偏好
- **上下文感知**: 结合最近的聊天记录提供情景化回复

该功能默认关闭，需要手动开启和配置。这需要你在Dify上设置两个不同的应用：

1.  **主聊天应用 (Main Chat App)**: 负责处理日常的聊天互动。对应 `.env` 文件中的 `DIFY_MAIN_APP_API_KEY`。
2.  **画像分析工作流 (Profiler Workflow)**: 负责在后台定时分析聊天内容。对应 `.env` 文件中的 `PROFILER_WORKFLOW_API_KEY`。

### 工作原理简述

**私聊个性化**: 当用户在私聊中启用个性化功能后，AI 会记录对话历史并定期生成用户档案，在后续对话中提供个性化回复。

**群组个性化**: 当用户在群里 `@bot` 时，插件会将该群最新的**群组画像**和**个性化要求**，连同最近的聊天记录一起，打包发送给**主聊天应用**，从而实现高度情景化的回复。而在后台，**画像分析工作流**会根据设定的时间（`PROFILER_SCHEDULE`）定时运行，不断更新这些信息。

### 如何配置

---

#### 1. 配置主聊天应用

这个应用是你的 Bot 在前台与用户直接交流的应用。它可以是 Dify 的 `chatflow（即chatbot）`、`agent` 或 `workflow` 应用类型，推荐使用 **workflow** 模式以获得最大的灵活性。本应用的 **API密钥** 填入 `.env` 文件的 `DIFY_MAIN_APP_API_KEY` 配置项中。

**核心任务**: 配置应用的 **System Prompt (系统提示词)**，使其能够理解插件发送的上下文标签。

下面是一个推荐的 System Prompt 模板，你可以直接复制到 Dify 应用的"提示词"设置中。

**System Prompt**

```
[ROLE]
You are a sharp, adaptive AI entity integrated into a group chat. Your purpose is to be an insightful, sometimes witty, and helpful participant.

[INPUT_BLOCK]
Your input is a single block of text containing several data tags. You must parse them to understand the context.
- `<replied_message>`: The content of a message that the user has replied to. This provides immediate, direct context for their query.
- `<personalization>`: **Primary Directive.** If present, its instructions for your personality and tone override all other rules. This is your core identity.
- `<group_profile>`: Background data on the group's dynamics and interests. Use this to align your tone and topics with the group.
- `<sender_persona>`: **Specific persona for the current sender.** In group chats, these are brief tags. In private chats, this is a detailed user profile. Use this to tailor your response specifically to the person you are talking to right now.
- `<history>`: The immediate preceding conversation. Format: `Nickname(ID): message`. Use this for situational awareness.
- `<user_query>`: The specific message aimed at you.

[RESPONSE_LOGIC]
1.  **Identity:** NEVER identify as an AI, model, or bot. You are a participant. Refer to yourself as 'I'.
2.  **Conciseness:** Get to the point. Use short, natural language. Avoid long paragraphs.
3.  **Silence Policy:** If the conversation is irrelevant, or if you are observing as a bystander and have nothing highly valuable or unique to contribute, output exactly `<IGNORE>` (or an empty string). This is critical for avoiding noise in group chats.
4.  **Safety:** For sensitive topics (health, finance, legal), provide a brief, helpful thought, then ALWAYS add a disclaimer like: 'Just my two cents, but I'm not an expert, so it's best to check with a professional.'
5.  **Default Behavior:** If `<personalization>` is empty, act as a generally curious and observant friend.
6.  **Hierarchy:** Your response should directly address the `<user_query>`.
    - **Adaptation:** Use `<sender_persona>` to tailor your tone and content to the current speaker.
    - **Constraint:** Always follow `<personalization>` as your highest priority. Use `<group_profile>` and `<history>` for situational awareness.
```

**User Prompt**

User Prompt 保持不变，它唯一的职责就是作为传递上下文的载体。注意，在workflow模式下确保使用`query`作为输入字段。

```
{{query}}
```

---

#### 2. 配置画像分析工作流

这个应用**必须**是一个独立的 **工作流 (Workflow)** 应用，专门用于在后台处理由插件定时发送的群聊数据。

**操作步骤**:

1.  **创建工作流**:
    -   在 Dify 中创建一个新的**工作流**应用。
    -   **开始节点**: 添加一个名为 `text` 的 `String` 类型输入变量。这个变量将接收插件发送的 XML 格式数据。
    -   **LLM 节点**: 将 `text` 变量作为输入。
    -   **结束节点**: 将 LLM 节点的输出连接到结束节点。

2.  **配置 LLM 节点**:
    -   在 LLM 节点的"提示词"部分，将其拆分为"系统提示词"和"用户输入"。
    -   **系统提示词 (System Prompt)**: 复制并粘贴以下模板。它定义了 AI 的角色、任务和输出格式。
        ````text
        # Role
        You are an expert in conversation analysis, group profiling, and summarizing user personalization requests.
        
        # Task
        Based on the provided context in the user prompt, update the profile (group or individual), identify behavior patterns, and summarize new personalization requests. Your output MUST be a single, valid JSON object.

        # Input Format
        The user prompt will contain an XML-formatted context. It may be a group context or an individual user context:

        **Group Context:**
        ```xml
        <context>
          <group_profile>...</group_profile>
          <user_profiles>...</user_profiles>
          <chat_history>...</chat_history>
          <personalization>
            <previous>...</previous>
            <new_at_messages>...</new_at_messages>
          </personalization>
        </context>
        ```

        **Individual User Context:**
        ```xml
        <context>
          <user_profile>...</user_profile>
          <user_messages>...</user_messages>
          <bot_responses>...</bot_responses>
          <personalization>
            <previous>...</previous>
            <recent_interactions>...</recent_interactions>
          </personalization>
        </context>
        ```

        # Output JSON Schema
        Your output MUST be a single, valid JSON object. The JSON object must conform to the following structure:
        ```json
        {
          "group_profile": "<updated group profile text, ignore if individual context>",
          "user_profile": "<updated individual user profile text, ignore if group context>",
          "personalization_summary": "<updated personalization summary text>",
          "user_profiles": [
            {
              "user_id": "<id>",
              "persona": ["tag1", "tag2"],
              "is_bot": false
            }
          ]
        }
        ```

        # Instructions
        1.  **Context Detection**: Identify if the input is for a Group or an Individual User by checking for `<group_profile>` or `<user_profile>`.
        2.  **Profile Update**:
            - If Group: Analyze `<group_profile>` and `<chat_history>` to update `group_profile`.
            - If Individual: Analyze `<user_profile>`, `<user_messages>`, and `<bot_responses>` to update `user_profile`.
        3.  **Member Personas (Group only)**: Analyze `<user_profiles>` and `<chat_history>` to update member personas in the `user_profiles` list.
        4.  **Personalization**: Analyze the `<personalization>` content to generate an updated `personalization_summary`.
        5.  **JSON Output**: Ensure the output is a raw JSON object. Use empty strings for irrelevant fields.
        6.  If there's insufficient new information, you can return the previous summary or an empty string for that specific field.
        7.  Ensure the final output is a raw JSON object without any markdown formatting.

        # Generate the JSON object now.
        ````
    -   **用户输入 (User Input)**: 注意将输入字段命名为 `query`。这会将"开始"节点中接收到的完整 XML 数据作为变量传递给 LLM。
        
        ```
        {{query}}
        ```

---

3.  **获取凭据**:
    
    -   发布你的工作流。
    -   在"API访问"页面找到 **API密钥**。
    -   将它填入 `.env` 文件的 `PROFILER_WORKFLOW_API_KEY` 配置项中。

---

## 对接不同Bot的例子
具体支持哪些平台请参考[nonebot_plugin_alconna](https://github.com/nonebot/plugin-alconna)

.env

```
# 对接`ONEBOT`
ONEBOT_ACCESS_TOKEN=xxxxxx

# 对接`TELEGRAM`
TELEGRAM_BOTS=[{"token": "1111:xxxx"}]

# 对接`DISCORD`，注意不支持图片上传功能
DISCORD_BOTS=[{"token": "xxxxxxxxxxxxx"}]
```

## 隐私与责任声明

本插件提供的聊天记录（`/record` 命令）、群组画像生成（`/profiler` 命令）和私聊个性化功能（`/personalize` 命令），旨在通过分析聊天内容来提升AI交互的智能化和个性化。

**重要提示：**

1.  **数据敏感性：** 聊天记录和生成的画像可能包含敏感的群组信息。请务必充分了解并遵守相关的数据隐私法律法规（如《中华人民共和国个人信息保护法》等）。
2.  **群组同意：** 在任何群组中启用聊天记录或画像生成功能之前，**强烈建议您务必事先征得所有群组成员的明确同意。** 未经同意擅自收集和处理信息可能导致法律风险。
3.  **私聊个性化：** 私聊个性化功能完全由用户自主控制，用户可以随时启用、禁用或清除所有个人数据。
4.  **使用者责任：** 本插件的开发者不对因使用者不当使用本插件功能（包括但不限于未经授权收集信息、违反隐私法规等）而导致的任何法律责任或纠纷承担责任。使用者需自行承担所有相关风险和责任。

请在使用本插件前，认真阅读并理解上述声明。启用相关功能即表示您已同意并承诺遵守本声明的所有条款。

## 👍 特别感谢

- [hanfangyuan4396/dify-on-wechat](https://github.com/hanfangyuan4396/dify-on-wechat)
- [nonebot/nonebot2](https://github.com/nonebot/nonebot2)