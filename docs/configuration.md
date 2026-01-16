# 配置指南

## 核心配置

| 配置项 | 必填 | 默认值 | 说明 |
|:-----:|:----:|:---:|:---|
| DIFY_API_BASE | 否 | https://api.dify.ai/v1 | DIFY API地址，支持自建 |
| DIFY_MAIN_APP_API_KEY | 是 | N/A | DIFY主APP的API KEY |
| DIFY_MAIN_APP_TYPE | 否 | chatflow | 助手类型：chatflow (推荐) / chatbot (兼容) / agent / workflow |
| DIFY_API_TIMEOUT | 否 | 90 | DIFY接口超时时间（单位秒） |

## 流式输出 (Streaming)

开启流式输出可以显著降低长回复的感知延迟，让回复像打字一样逐段显示。

| 配置项 | 必填 | 默认值 | 说明 |
|:-----:|:----:|:---:|:---|
| DIFY_STREAM_ENABLE | 否 | False | 是否开启流式输出模式 |
| DIFY_STREAM_MIN_INTERVAL | 否 | 1.5 | 流式输出最小时间间隔（秒），避免发送过快触发平台限制 |
| DIFY_STREAM_MIN_CHAR | 否 | 10 | 流式输出最小字符缓冲，避免发送过短的消息片段 |

## 跨插件感知 (Cross-Plugin Perception)

| 配置项 | 必填 | 默认值 | 说明 |
|:-----:|:----:|:---:|:---|
| PERCEPTION_ENABLED | 否 | False | 是否开启跨插件感知功能 |
| PERCEPTION_PASSIVE_PLUGINS | 否 | [] | **感知名单**：仅静默记录插件输出到上下文，Bot 不主动接话。<br />**注意**：留空 `[]` 表示**记录所有插件**（默认）。若需指定特定插件，请填入插件名列表，如 `["plugin_a"]`。 |
| PERCEPTION_INTERCEPT_PLUGINS | 否 | [] | **接管名单**：拦截并“掐掉”原插件消息，由 AI 重新转述输出 |
| PERCEPTION_INTERCEPT_COMMANDS | 否 | [] | **命令强制接管**：只要用户指令以列表中的前缀开头（如 `["/weather"]`），无论该插件是否在接管名单，都强制拦截并由 AI 回复。适合希望 AI 播报特定查询结果的场景。 |

**使用场景**:
1. **统一 Bot 身份**: 将 `nonebot_plugin_weather` 加入 `PERCEPTION_INTERCEPT_PLUGINS`。当用户查天气时，原插件的生硬文本会消失，取而代之的是 Dify AI 甜美的播报。
2. **增强长期记忆**: 将高频插件加入 `PERCEPTION_PASSIVE_PLUGINS`。即便用户没艾特 AI，AI 也会默默记住刚才发生了什么。

## 会话管理

| 配置项 | 必填 | 默认值 | 说明 |
|:-----:|:----:|:---:|:---|
| SESSION_MAX_MESSAGES | 否 | 20 | 会话最大消息数，超过后清空会话 |
| SESSION_EXPIRES_SECONDS | 否 | 3600 | 会话过期时间（单位秒） |
| SESSION_SHARE_IN_GROUP | 否 | False | 是否在群组里共享同一个session<br />注意：在开启群聊记录后，该选项无效果 |

## 消息处理

| 配置项 | 必填 | 默认值 | 说明 |
|:-----:|:----:|:---:|:---|
| IGNORE_PREFIX | 否 | ["/", "."] | 忽略词，指令以这些前缀开头不会触发回复 |
| MESSAGE_MAX_LENGTH | 否 | 200 | 记录单条聊天消息的最大长度 |
| MESSAGE_DESENSITIZATION_ENABLE | 否 | True | 是否开启消息脱敏功能 |

## 图片上传

| 配置项 | 必填 | 默认值 | 说明 |
|:-----:|:----:|:---:|:---|
| IMAGE_UPLOAD_ENABLE | 否 | False | 是否开启上传图片，需要LLM模型支持图片识别，<br />同时需要nonebot_plugin_alconna支持相应Adapter |
| IMAGE_CACHE_DIR | 否 | "image" | 图像缓存的子目录 |

## 图片历史上下文

当用户在聊天中发送过图片后，可能会在后续消息中引用该图片（如"这张图是什么"、"帮我分析一下"）。此功能增强了图片在聊天历史中的处理方式，并支持智能检测用户的图片引用意图。

| 配置项 | 必填 | 默认值 | 说明 |
|:-----:|:----:|:---:|:---|
| HISTORY_IMAGE_MODE | 否 | "placeholder" | 历史记录中图片的处理模式：<br />`placeholder`=标记[image]（默认），`description`=生成描述（**❗每张图都会调用工作流，消耗大量 Token**），`none`=不处理 |
| IMAGE_DESCRIPTION_WORKFLOW_API_KEY | 否 | | 用于生成图片描述的 Dify Workflow API Key（仅 `description` 模式需要） |
| IMAGE_REFERENCE_CACHE_TTL | 否 | 1800 | 图片引用缓存过期时间（秒），默认30分钟 |
| IMAGE_ATTACH_MODE | 否 | "off" | 触发附加缓存图片的方式（非 off 时自动启用图片缓存）：<br />`off`=不缓存（默认），`keyword`=关键词匹配，`semantic`=语义匹配 |
| IMAGE_ATTACHMENT_SEMANTIC_THRESHOLD | 否 | 0.60 | 语义匹配模式下的相似度阈值（0.0-1.0），默认 0.60 |
| IMAGE_MIN_SIZE | 否 | 51200 | 最小图片大小（字节），小于此值的图片（如表情包）将被忽略（默认 50KB） |
| IMAGE_MAX_SIZE | 否 | 1048576 | 最大图片大小（字节），大于此值的图片将被压缩（默认 1MB） |
| IMAGE_COMPRESS_QUALITY | 否 | 80 | 图片压缩质量（1-100）（默认 80） |
| IMAGE_COMPRESS_MAX_RESOLUTION | 否 | 1500 | 压缩后的最大长边分辨率（像素）（默认 1500） |


**👉 详细功能介绍与工作流配置示例请参阅 [高级功能指南 - 图片历史上下文](features.md#图片历史上下文-image-history-context)。**



## 群聊设置

| 配置项 | 必填 | 默认值 | 说明 |
|:-----:|:----:|:---:|:---|
| GROUP_CHAT_HISTORY_LIMIT | 否 | 10 | 个性化回复时在群聊中获取最近消息记录的条数 |
| GROUP_CHAT_HISTORY_SIZE | 否 | 1024 | 个性化回复时在群聊中获取最近消息记录的最大长度 |

## 用户画像

| 配置项 | 必填 | 默认值 | 说明 |
|:-----:|:----:|:---:|:---|
| PROFILER_WORKFLOW_API_KEY | 否 | | 用于生成群组画像和个性化要求的Dify工作流API Key |
| PRIVATE_PROFILER_WORKFLOW_API_KEY | 否 | | 用于生成私聊个人画像的Dify工作流API Key，如不配置则默认使用PROFILER_WORKFLOW_API_KEY |
| PROFILER_SCHEDULE | 否 | 0 3 * * * | 执行群组画像和个性化要求生成的定时任务触发器，默认为每天凌晨3点 |
| PROFILER_SCHEDULE_JITTER | 否 | 10 | 在计划开始后，将任务随机分布在多少分钟内执行，0表示禁用 |
| PROFILER_HISTORY_LIMIT | 否 | 50 | 生成画像时分析的最近历史记录条数 |
| PROFILER_MIN_MESSAGES | 否 | 10 | 生成画像所需的最少有效消息条数 |
| PROFILER_CHAT_HISTORY_SIZE | 否 | 1024 | 生成画像允许的聊天消息的最大长度 |

## 个性化设置

| 配置项 | 必填 | 默认值 | 说明 |
|:-----:|:----:|:---:|:---|
| DEFAULT_PERSONALIZATION | 否 | "你叫喵喵，是一位..." | 当群组首次启用画像功能时，应用的默认个性化描述 |

## 私聊设置

| 配置项 | 必填 | 默认值 | 说明 |
|:-----:|:----:|:---:|:---|
| PRIVATE_PERSONALIZATION_ENABLE | 否 | False | 是否启用私聊个性化功能 |
| PRIVATE_CHAT_HISTORY_LIMIT | 否 | 20 | 私聊个性化回复时获取最近消息记录的条数 |
| PRIVATE_CHAT_HISTORY_SIZE | 否 | 2048 | 私聊个性化回复时获取最近消息记录的最大长度 |
| PRIVATE_PROFILER_MIN_MESSAGES | 否 | 15 | 生成私聊用户画像所需的最少有效消息条数 |
| PRIVATE_PROFILER_SCHEDULE | 否 | 0 4 * * * | 执行私聊用户画像生成的定时任务触发器，默认为每天凌晨4点 |
| PRIVATE_PROFILER_SCHEDULE_JITTER | 否 | 10 | 在计划开始后，将任务随机分布在多少分钟内执行，0表示禁用 |
| PRIVATE_DATA_RETENTION_DAYS | 否 | 90 | 私聊用户数据保留天数，超过此时间的数据将被自动清理 |

## 余韵模式 (Linger Mode)

| 配置项 | 必填 | 默认值 | 说明 |
|:-----:|:----:|:---:|:---|
| LINGER_MODE_ENABLE | 否 | False | 是否启用余韵模式，被艾特后一段时间内无需再艾特 |
| LINGER_TIMEOUT_SECONDS | 否 | 180 | 余韵模式持续时间（秒） |
| LINGER_MAX_MESSAGES | 否 | 3 | 余韵模式下连续回复的最大消息数 |
| LINGER_RESPONSE_PROBABILITY | 否 | 0.7 | 余韵模式回复概率(0.0-1.0)，降低此值可减少回复频率 |
| LINGER_MIN_INTERVAL_SECONDS | 否 | 10 | 余韵模式最小回复间隔(秒)，避免刷屏 |

## 主动介入模式 (Proactive Intervention)

| 配置项 | 必填 | 默认值 | 说明 |
|:-----:|:----:|:---:|:---|
| PROACTIVE_MODE_ENABLE | 否 | False | 是否启用主动介入模式 |
| PROACTIVE_MODEL_NAME | 否 | "BAAI/bge-small-zh-v1.5" | 语义匹配模型名称 |
| PROACTIVE_HF_MIRROR | 否 | "https://hf-mirror.com" | HuggingFace镜像地址，用于国内下载模型 |
| PROACTIVE_INTERESTS | 否 | [] | 机器人感兴趣的话题列表 (例如 `['AI', 'Python', '动漫']`) |
| PROACTIVE_SEMANTIC_THRESHOLD | 否 | 0.8 | 语义相似度阈值 (0.0-1.0)，越高越严格 |
| PROACTIVE_LIKELIHOOD | 否 | 1.0 | 触发概率 (0.0-1.0)，建议设为 0.5-0.7 以增加随机感 |
| PROACTIVE_COOLDOWN_SECONDS | 否 | 1800 | 主动介入的冷却时间 (秒)，默认30分钟 |
| PROACTIVE_SILENCE_WAITING_SECONDS | 否 | 120 | 触发前的观察静默期 (秒)，期间若有人发言则取消介入 |

## 管理配置

| 配置项 | 必填 | 默认值 | 说明 |
|:-----:|:----:|:---:|:---|
| SYSTEM_ADMIN_USER_ID | 否 | None | 系统管理员的“完整用户ID”，用于赋予指定用户全局管理员权限。<br />支持多个ID，用逗号分隔。<br />管理员可以无视平台角色限制，使用如 `/record` 和 `/profiler` 等命令。<br />私聊机器人发送 `/get_my_id` 可获取自己的ID。 |

## 工具系统 (Plugin-as-a-Tool)

将 NoneBot 插件的命令暴露为 Dify 智能体可调用的工具（Tools）。

| 配置项 | 必填 | 默认值 | 说明 |
|:-----:|:----:|:---:|:---|
| TOOL_ENABLE | 否 | False | 是否启用工具系统。开启后，将根据 `TOOL_MODEL_*` 配置连接 OpenAI 兼容模型进行工具检测。此时 `DIFY_MAIN_APP_TYPE` 设置可能会被覆盖。 |
| TOOL_ALLOWLIST | 否 | [] | 允许暴露给 LLM 的命令白名单 (JSON List)。例如 `["weather", "help"]`。 |
| TOOL_TIMEOUT | 否 | 30 | 工具执行超时时间（秒）。 |
| TOOL_SANDBOX_API_ALLOWLIST | 否 | [] | 沙箱环境中允许调用的只读 API (JSON List)。例如 `["get_group_info"]`。 |
| TOOL_SCHEMA_OVERRIDE | 否 | {} | **高级配置**：自定义工具的 Schema、命令格式和别名 (JSON Dict)。<br />用于手动指定复杂参数或为工具起别名。<br />格式详见下文示例。 |
| TOOL_SKIP_ON_IMAGE | 否 | True | 当消息包含图片时，是否跳过 OpenAI 工具检测直接调用 Dify。<br />因为 OpenAI Tool LLM 难以结合上下文理解图片内容来生成工具调用，建议开启此项以利用 Dify 的图像识别能力。 |
| TOOL_USE_CONTEXT | 否 | False | Tool Detection 是否使用聊天上下文（历史记录）。<br />False: 仅使用当前消息判断，避免被历史误导（默认）。<br />True: 包含完整群聊历史，支持多轮对话意图，但可能增加 Token 消耗和误判风险。 |

### OpenAI 兼容模型配置 (工具检测用)

当启用工具系统 (`TOOL_ENABLE=True`) 时，必须配置以下 OpenAI 兼容模型信息，用于第一阶段的工具意图检测。

| 配置项 | 必填 | 默认值 | 说明 |
|:-----:|:----:|:---:|:---|
| TOOL_MODEL_API_KEY | **是** | | OpenAI 兼容模型的 API Key |
| TOOL_MODEL_BASE_URL | 否 | | OpenAI 兼容模型的 Base URL (如 `https://api.deepseek.com`) |
| TOOL_MODEL_NAME | 否 | | 模型名称 (如 `deepseek-chat`) |

### TOOL_SCHEMA_OVERRIDE 示例

**注意**：此配置项是**可选**的。对于简单的 `on_command`（如 `/weather 北京`），系统会自动生成 Schema 并正确执行，**无需**进行额外配置。

**仅在以下情况建议配置**：
1. **复杂参数**：命令需要复杂的参数组合（如 `/cmd -n 10 -t tag`），自动生成的 Schema 无法满足。
2. **效果优化**：自动生成的描述不够准确，希望手动优化以提升 LLM 调用的成功率。

```json
{
  "search": {
    "description": "联网搜索，获取最新信息",
    "parameters": {
      "type": "object",
      "properties": {
        "query": { "type": "string", "description": "搜索关键词" }
      },
      "required": ["query"]
    },
    "format": "/search {query}"
  }
}
```

- **description**: 告诉 LLM 何时使用此工具（这是最重要的字段）。
- **parameters**: 覆盖自动生成的 JSON Schema。
- **format**: 定义如何将工具调用参数转换为 NoneBot 命令字符串。
