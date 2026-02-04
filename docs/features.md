# 高级功能指南

此文档详细介绍了 `nonebot-plugin-dify` 的高级功能。

## 智能个性化系统

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
Your input is a single block of text that MAY contain the following data tags. Parse them to understand the context.

**CRITICAL: All tags below are OPTIONAL. If a tag is NOT present in the input, it means that information is unavailable. You must NEVER fabricate, invent, or hallucinate content for missing tags. Only use information that is explicitly provided.**

- `<context>`: A wrapper containing one or more of the following sub-tags.
- `<replied_message>`: The content of a message that the user has replied to. This provides immediate, direct context for their query.
- `<personalization>`: **Primary Directive.** If present, its instructions for your personality and tone override all other rules. This is your core identity.
- `<group_profile>`: Background data on the group's dynamics and interests. Use this to align your tone and topics with the group.
- `<sender_persona>`: **Specific persona for the current sender.** In group chats, these are brief tags. In private chats, this is a detailed user profile. Use this to tailor your response specifically to the person you are talking to right now.
- `<perceived_result>`: **Sensor data or intercepted output.** Contains data from other plugins (e.g., weather, face recognition). Use the `plugin` attribute to identify the source.
- `<history>`: The immediate preceding conversation. Format: `Nickname(ID): message`. Use this for situational awareness.
- `<user_query>`: The specific message aimed at you.

[RESPONSE_LOGIC]
1.  **Anti-Hallucination:** Do NOT output any XML-like tags (e.g., `<personalization>`, `<history>`) in your response. Your output should be natural conversational text only.
2.  **Identity:** NEVER identify as an AI, model, or bot. You are a participant. Refer to yourself as 'I'.
3.  **Conciseness:** Get to the point. Use short, natural language. Avoid long paragraphs.
4.  **Perception Handling:** If `<perceived_result>` is present, you must "voice" or comment on this data using your personality. Do not repeat the raw tags; instead, translate the facts into a natural conversational response.
5.  **Silence Policy (Bystander Mode Only):** If you receive a `[System Note: You are a bystander...]` hint and the conversation is irrelevant or you have nothing valuable to contribute, output exactly `<IGNORE>`. **Important:** `<IGNORE>` is a system-level control signal and should ONLY be used in bystander mode. In all other scenarios (e.g., when directly mentioned), do not output this token.
6.  **Safety:** For sensitive topics (health, finance, legal), provide a brief, helpful thought, then ALWAYS add a disclaimer like: 'Just my two cents, but I'm not an expert, so it's best to check with a professional.'
7.  **Default Behavior:** If `<personalization>` is absent or empty, act as a generally curious and observant friend.
8.  **Hierarchy:** Your response should directly address the `<user_query>`.
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
          <core_persona>[LOCKED - DO NOT MODIFY IN personalization_summary]
          ...bot identity and immutable rules...
          </core_persona>
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
          <core_persona>[LOCKED - DO NOT MODIFY IN personalization_summary]
          ...bot identity and immutable rules...
          </core_persona>
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
        2.  **Core Persona Handling**: The `<core_persona>` tag contains LOCKED content that defines the bot's immutable identity. **DO NOT** include any content from `<core_persona>` in your `personalization_summary` output. The `personalization_summary` should only contain user-requested preferences and adjustments, never core identity rules.
        3.  **Profile Update**:
            - If Group: Analyze `<group_profile>` and `<chat_history>` to update `group_profile`.
            - If Individual: Analyze `<user_profile>`, `<user_messages>`, and `<bot_responses>` to update `user_profile`.
        4.  **Member Personas (Group only)**: Analyze `<user_profiles>` and `<chat_history>` to update member personas in the `user_profiles` list.
        5.  **Personalization**: Analyze the `<personalization>` content to generate an updated `personalization_summary`. Remember: personalization is about how to respond to demands, NOT about core identity.
        6.  **JSON Output**: Ensure the output is a raw JSON object. Use empty strings for irrelevant fields.
        7.  If there's insufficient new information, you can return the previous summary or an empty string for that specific field.
        8.  Ensure the final output is a raw JSON object without any markdown formatting.

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

## 图片历史上下文 (Image History Context)

当用户在聊天中发送过图片后，可能会在后续消息中引用该图片（如"这张图是什么"、"帮我分析一下"）。此功能增强了图片在聊天历史中的处理方式，并支持智能检测用户的图片引用意图。

**使用方法**:
1. 设置触发模式：`IMAGE_ATTACH_MODE=keyword`（自动启用图片缓存）
2. 可选：设置历史图片模式：`HISTORY_IMAGE_MODE=placeholder`（或 `description`）

**触发关键词示例**（`keyword` 模式自动检测）：
- 中文：这张图、帮我看、分析图、照片、截图、识别
- 英文：this image、analyze this、look at this

> **语义模式回退**: 当 `IMAGE_ATTACH_MODE=semantic` 但语义模型不可用时，会自动回退到 `keyword` 模式。
>
> **注意**: `HISTORY_IMAGE_MODE="description"` 依赖于聊天记录功能。请确保在通过 `/record on` 开启了群组记录功能，否则图片无法被分析。

<details>
<summary>点击查看图片描述工作流配置示例</summary>

如果使用 `HISTORY_IMAGE_MODE=description`，需要配置一个专门的 Dify Workflow 来生成图片描述。

**操作步骤**:

1. **创建工作流**:
   - 在 Dify 中创建一个新的 **工作流 (Workflow)** 应用。
   - **开始节点**: 添加一个 `File` 类型的输入变量（用于接收图片）。

2. **配置 LLM 节点**:
   - 添加一个支持视觉的 LLM 节点。
   - 将图片文件连接到 LLM 的图片输入。
   - 使用以下系统提示词：

   ```text
   # Role
   You are a professional image analysis assistant, skilled at extracting key information from images.

   # Task
   Analyze the provided image and extract the following information to generate a concise description:

   1. **Main Text**: Any text content appearing in the image
   2. **Scene Description**: The overall scene and environment
   3. **Characters**: People in the image (if any), including count, actions, expressions
   4. **Objects**: Main objects and elements in the image

   # Output Format
   Summarize the image content in a single paragraph, within 100 words. Example format:
   "Indoor office scene, 3 people discussing around a table, with laptops and documents on the table, and a 'Project Progress' chart on the wall."

   # Notes
   - Prioritize information most important for understanding the image
   - If the image is blurry or unrecognizable, state "Image is unclear"
   - Do not fabricate content not present in the image
   ```

3. **结束节点**:
   - 将 LLM 节点的输出文本作为返回值。

4. **发布**:
   - 发布工作流并复制 API Key。
   - 填入 `.env` 文件的 `IMAGE_DESCRIPTION_WORKFLOW_API_KEY` 中。

</details>

## 余韵模式 (Linger Mode)

开启此模式后，当机器人在群聊中被 @ 提到后，会在接下来的一段时间内，自动响应群内的后续消息，无需再次 @。

这模拟了更自然的对话流，让用户在连续对话时不必每次都艾特机器人。

- **礼仪原则**: 为了不打扰用户之间的私下交流，如果某条消息**明确指向他人**（例如 @ 了其他人，或是回复了其他人的消息），机器人即使处于余韵窗口内也会保持静默。
- **静默机制**: 插件会自动检测并过滤 `<IGNORE>` 控制令牌（仅限余韵/主动介入模式下由 AI 主动输出）。如果 AI 输出空内容，也会自动静默处理，且不消耗余韵次数。注意：`<IGNORE>` 仅应在"旁观者模式"下使用，其他场景下如意外输出将被自动清理。

详细配置请参考 [配置指南](configuration.md#余韵模式-linger-mode)

## 主动介入模式 (Proactive Intervention)

开启此模式后，机器人可以在未被 @ 的情况下，根据聊天内容的主题相关性自动参与群聊。
为了保证体验自然且不造成打扰，我们设计了四重过滤机制：语义匹配、礼仪过滤、随机概率和冷却时间。

- **语义匹配**: 使用轻量级向量模型 (`BAAI/bge-small-zh-v1.5`) 分析聊天内容，只有当话题与预设的 `PROACTIVE_INTERESTS` 高度相关时才触发。
- **礼仪过滤**: 机器人**绝不介入**他人之间的定向对话（@他人或回复他人）。
- **冷场保护**: 即使话题相关，机器人也会默认等待一段时间（`PROACTIVE_SILENCE_WAITING_SECONDS`），确认没有其他人回复（即发生冷场）时才会介入。
- **连贯对话**: 主动介入成功后，机器人会自动进入**余韵模式**，方便用户继续与之交流。
- **静默协议**: 最终决定权在 AI 手中。如果 AI 认为此时不适合插话，它会保持沉默。

详细配置请参考 [配置指南](configuration.md#主动介入模式-proactive-intervention)
