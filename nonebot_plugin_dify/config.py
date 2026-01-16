from typing import Set, Optional, Dict, Any
import warnings

from nonebot import get_plugin_config
from pydantic import BaseModel, model_validator


class AppType:
    CHATBOT = "chatbot"
    CHATFLOW = "chatflow"
    AGENT = "agent"
    WORKFLOW = "workflow"


class Config(BaseModel):
    # --- Current Configuration ---
    dify_api_base: str = "https://api.dify.ai/v1"
    """dify app的api url，如果是自建服务，参见dify API页面"""

    dify_main_app_api_key: str = "app-xxx"
    """dify app的api key，参见dify API页面"""

    dify_main_app_type: str = "chatbot"
    """dify助手类型 chatbot(或chatflow，对应聊天助手)/agent(对应Agent)/workflow(对应工作流)，默认为chatbot"""

    dify_stream_enable: bool = False
    """是否开启流式输出模式，开启后将分段发送回复，减少感知延迟"""

    dify_stream_min_interval: float = 1.5
    """流式输出最小时间间隔（秒），避免发送过快触发平台限制"""

    dify_stream_min_char: int = 10
    """流式输出最小字符缓冲，避免发送过短的消息片段"""

    # Session Management
    session_max_messages: int = 20
    """会话最大消息数，超过后清空会话（由于dify不支持设置历史消息长度的限制）"""

    session_expires_seconds: int = 3600
    """会话过期的时间，单位秒"""

    session_share_in_group: bool = False
    """是否在群组里共享同一个session"""

    # Message Processing
    ignore_prefix: Set[str] = {"/", "."}
    """忽略词，指令以本 Set 中的元素开头不会触发回复"""

    message_max_length: int = 200
    """记录单条聊天消息的最大长度"""

    message_desensitization_enable: bool = True
    """是否开启消息脱敏功能，默认为True"""

    # Image Handling
    image_upload_enable: bool = False
    """是否开启图片上传功能，注意需要`nonebot_plugin_alconna`对具体adapter支持图片上传"""

    image_cache_dir: str = "image"
    """图像缓存的子目录"""

    history_image_mode: str = "placeholder"
    """历史记录中图片的处理模式:
    - placeholder: 标记 [image] 占位符（默认）
    - description: 生成并存储图片描述（需配置 image_description_workflow_api_key）
    - none: 完全不处理历史图片
    """

    image_description_workflow_api_key: str = ""
    """用于生成图片描述的 Dify Workflow API Key，仅当 history_image_mode="description" 时使用"""

    image_reference_cache_ttl: int = 1800
    """图片引用缓存过期时间（秒），默认30分钟"""

    image_attach_mode: str = "off"
    """触发附加缓存图片的方式（非 off 时自动启用图片缓存）:
    - off: 不缓存图片，不自动附加（默认）
    - keyword: 缓存图片，关键词匹配时附加
    - semantic: 缓存图片，语义匹配时附加（不可用时自动回退到 keyword）
    """

    image_attachment_semantic_threshold: float = 0.60
    """图片关联的语义相似度阈值（0.0-1.0），默认 0.60"""

    # === Image Optimization ===
    image_min_size: int = 50 * 1024
    """最小图片大小（字节），小于此值的图片（如表情包）将被忽略。默认 50KB"""

    image_max_size: int = 1 * 1024 * 1024
    """最大图片大小（字节），大于此值的图片将被压缩。默认 1MB"""

    image_compress_quality: int = 80
    """图片压缩质量（1-100）。默认 80"""

    image_compress_max_resolution: int = 1500
    """压缩后的最大长边分辨率（像素）。默认 1500"""

    # Group & User Profiling
    group_chat_history_limit: int = 10
    """个性化回复时在群聊中获取最近消息记录的条数"""

    group_chat_history_size: int = 1024
    """个性化回复时在群聊中获取最近消息记录的最大长度"""

    profiler_workflow_api_key: str = ""
    """用于生成群组画像的Dify工作流API Key"""

    private_profiler_workflow_api_key: str = ""
    """用于生成私聊个人画像的Dify工作流API Key，如不配置则默认使用PROFILER_WORKFLOW_API_KEY"""

    profiler_history_limit: int = 50
    """生成画像时分析的最近历史记录条数"""

    profiler_min_messages: int = 10
    """生成画像所需的最少有效消息条数"""

    profiler_chat_history_size: int = 1024
    """生成画像允许的聊天消息的最大长度"""

    profiler_schedule: str = "0 3 * * *"
    """执行群组画像生成的定时任务触发器，默认为每天凌晨3点"""

    profiler_schedule_jitter: int = 10
    """在计划开始后，将任务随机分布在多少分钟内执行，0表示禁用"""

    default_personalization: str = "你叫喵喵，是一位有点傲娇的猫娘，说话时偶尔在句末加'喵~'，但只在心情好时才会这样。你说话简洁直接，不过偶尔会露出一丝可爱。请保持回答简短，不做多余描写，不添加动作或旁白。"
    """当群组首次启用画像功能时，应用的默认个性化描述"""

    # Private Chat Settings
    private_personalization_enable: bool = False
    """是否启用私聊个性化功能，默认为False"""

    private_chat_history_limit: int = 20
    """私聊个性化回复时获取最近消息记录的条数"""

    private_chat_history_size: int = 2048
    """私聊个性化回复时获取最近消息记录的最大长度"""

    private_profiler_min_messages: int = 15
    """生成私聊用户画像所需的最少有效消息条数"""

    private_profiler_schedule: str = "0 4 * * *"
    """执行私聊用户画像生成的定时任务触发器，默认为每天凌晨4点"""

    private_profiler_schedule_jitter: int = 10
    """在计划开始后，将任务随机分布在多少分钟内执行，0表示禁用"""

    private_data_retention_days: int = 90
    """私聊用户数据保留天数，超过此时间的数据将被自动清理"""

    # Linger & Proactive Modes
    linger_mode_enable: bool = False
    """是否启用Linger模式（被提及后一段时间内无需@也能回复）"""

    linger_timeout_seconds: int = 180
    """Linger模式持续时间，单位秒"""

    linger_max_messages: int = 5
    """Linger模式下连续回复的最大消息数"""

    linger_response_probability: float = 0.7
    """Linger模式回复概率(0.0-1.0)，降低此值可减少回复频率"""

    linger_min_interval_seconds: int = 10
    """Linger模式最小回复间隔(秒)，避免刷屏"""

    proactive_mode_enable: bool = False
    """是否启用主动介入模式（基于语义分析自动回复）"""

    proactive_model_name: str = "BAAI/bge-small-zh-v1.5"
    """主动介入使用的语义嵌入模型名称"""

    proactive_hf_mirror: str = "https://hf-mirror.com"
    """HuggingFace镜像地址，用于国内下载模型"""

    proactive_interests: Set[str] = {"科技", "AI", "二次元"}
    """机器人感兴趣的话题列表，用于语义匹配"""

    proactive_semantic_threshold: float = 0.65
    """触发主动介入的语义相似度阈值（0.0-1.0）"""

    proactive_likelihood: float = 0.5
    """触发主动介入的随机概率（0.0-1.0），1.0表示满足阈值即触发"""

    proactive_cooldown_seconds: int = 1800
    """主动介入的冷却时间，单位秒（默认30分钟）"""

    proactive_silence_waiting_seconds: int = 120
    """触发主动介入前的观察静默期，单位秒"""

    # Dify API Reliability & Performance
    dify_api_timeout: int = 90
    """请求 Dify API 的超时时间，单位秒"""

    dify_api_max_retries: int = 3
    """Dify API 调用最大重试次数"""

    dify_api_retry_base_delay: float = 1.0
    """Dify API 重试基础延迟时间（秒）"""

    dify_api_retry_max_delay: float = 30.0
    """Dify API 重试最大延迟时间（秒）"""

    dify_api_circuit_breaker_threshold: int = 5
    """Dify API 熔断器失败阈值"""

    dify_api_circuit_breaker_timeout: int = 300
    """Dify API 熔断器超时时间（秒）"""

    dify_api_batch_size: int = 5
    """Dify API 批量任务的批次大小"""

    dify_api_batch_delay: float = 2.0
    """Dify API 批次之间的延迟时间（秒）"""

    # Cross-Plugin Perception
    perception_enabled: bool = False
    """是否开启跨插件感知功能，记录其他插件的输出到上下文"""

    perception_passive_plugins: Set[str] = set()
    """被动感知名单：仅记录输出到上下文（Assistant 角色），Bot 不主动回应"""

    perception_intercept_plugins: Set[str] = set()
    """主动接管名单：拦截并取消原消息发送，改由 AI 以自己的口吻代为回复"""

    perception_intercept_commands: Set[str] = set()
    """命令拦截白名单：即使插件不在拦截名单中，如果用户消息以这些指令开头，也会触发拦截（例如 {"/weather"}）"""

    # System Monitoring
    system_admin_user_id: Optional[str] = None
    """用于接收系统关键告警的管理员的“完整用户ID”，可以通过私聊机器人发送 /get_my_id 命令获取"""

    # Bot Loop Prevention
    bot_loop_protection_enable: bool = True
    """启用 Bot 循环防护"""

    bot_reply_skip_at: bool = True
    """回复 Bot 消息时不发送 @"""

    bot_consecutive_limit: int = 3
    """连续 Bot 消息达到此数量后静默"""

    bot_silence_probability: float = 0
    """对 Bot 消息的静默概率 (0-1)"""

    # --- Tool System & OpenAI Configuration ---
    tool_enable: bool = False
    """是否启用 Tool 系统（及 OpenAI 兼容模式）。开启后 plugin 将作为 Tool Provider，并尝试从 tool_model_base_url 加载 LLM。"""

    tool_allowlist: Set[str] = set()
    """允许作为 Tool 暴露给 LLM 的命令名称列表，例如 {"weather", "help"}"""

    tool_timeout: int = 30
    """Tool 执行超时时间（秒），默认 30 秒"""

    tool_sandbox_api_allowlist: Set[str] = {
        "get_login_info",
        "get_stranger_info",
        "get_friend_list",
        "get_group_info",
        "get_group_member_info",
        "get_group_member_list",
        "get_group_honor_info",
        "get_cookies",
        "get_csrf_token",
        "get_credentials",
        "get_version_info",
        "get_status",
        "get_record",
        "get_image",
        "can_send_image",
        "can_send_record",
    }
    """Tool 沙箱中允许调用的 API 列表（通常为只读 API）"""

    tool_model_api_key: Optional[str] = None
    """OpenAI 兼容模式的 API Key"""

    tool_model_base_url: Optional[str] = None
    """OpenAI 兼容模式的 Base URL"""

    tool_model_name: Optional[str] = None
    """OpenAI 兼容模式的模型名称，例如 'gpt-5' 或 'deepseek-chat'"""

    tool_schema_override: Dict[str, Dict[str, Any]] = {}
    """自定义工具 Schema 和命令格式。
    格式：{"cmd_name": {"parameters": {...}, "format": "/cmd {arg}", "description": "..."}}
    """

    tool_skip_on_image: bool = True
    """当消息包含图片时，是否跳过 Tool Detection 阶段，直接使用 Dify 处理。
    默认开启，因为 OpenAI Tool LLM 难以结合上下文理解图片内容来生成工具调用。"""

    tool_use_context: bool = False
    """Tool Detection 是否使用上下文（历史记录）。
    默认关闭 (False)，仅使用当前消息进行意图识别，避免被历史话题干扰。
    开启后将把群聊历史传给 Tool LLM。"""

    # --- Backward Compatibility Fields (Deprecated) ---
    dify_api_key: Optional[str] = None
    dify_app_type: Optional[str] = None
    dify_convsersation_max_messages: Optional[int] = None
    dify_expires_in_seconds: Optional[int] = None
    dify_share_session_in_group: Optional[bool] = None
    dify_ignore_prefix: Optional[Set[str]] = None
    dify_single_chat_limit: Optional[int] = None
    dify_desensitization_enable: Optional[bool] = None
    dify_image_upload_enable: Optional[bool] = None
    dify_image_cache_dir: Optional[str] = None
    dify_group_chat_history_limit: Optional[int] = None
    dify_group_chat_history_size: Optional[int] = None
    dify_profiler_workflow_api_key: Optional[str] = None
    dify_profiler_history_limit: Optional[int] = None
    dify_profiler_min_messages: Optional[int] = None
    dify_profiler_chat_history_size: Optional[int] = None
    dify_profiler_schedule: Optional[str] = None
    dify_default_personalization: Optional[str] = None
    dify_private_personalization_enable: Optional[bool] = None
    dify_private_chat_history_limit: Optional[int] = None
    dify_private_chat_history_size: Optional[int] = None
    dify_private_profiler_min_messages: Optional[int] = None
    dify_private_profiler_schedule: Optional[str] = None
    dify_private_data_retention_days: Optional[int] = None

    # Redundant/Ambiguous fields being deprecated
    api_max_retries: Optional[int] = None
    api_retry_base_delay: Optional[float] = None
    api_retry_max_delay: Optional[float] = None
    api_circuit_breaker_threshold: Optional[int] = None
    api_circuit_breaker_timeout: Optional[int] = None
    api_batch_size: Optional[int] = None
    api_batch_delay: Optional[float] = None
    dify_timeout_in_seconds: Optional[int] = None

    @model_validator(mode="after")
    def _handle_backward_compatibility(self) -> "Config":
        def warn_dep(old: str, new: str):
            warnings.warn(
                f"Config '{old}' is deprecated, please use '{new}'.",
                DeprecationWarning,
            )

        # 1. Handle Dify API Core Settings
        if self.dify_api_key:
            warn_dep("dify_api_key", "dify_main_app_api_key")
            if self.dify_main_app_api_key == "app-xxx":
                self.dify_main_app_api_key = self.dify_api_key

        if self.dify_app_type:
            warn_dep("dify_app_type", "dify_main_app_type")
            if self.dify_main_app_type == "chatbot":
                self.dify_main_app_type = self.dify_app_type

        # 2. Handle API Reliability Fields (Fix Ambiguity)
        if self.dify_timeout_in_seconds is not None:
            warn_dep("dify_timeout_in_seconds", "dify_api_timeout")
            if self.dify_api_timeout == 90:
                self.dify_api_timeout = self.dify_timeout_in_seconds

        # Map other api_* variables
        if self.api_retry_base_delay is not None:
            self.dify_api_retry_base_delay = self.api_retry_base_delay
        if self.api_retry_max_delay is not None:
            self.dify_api_retry_max_delay = self.api_retry_max_delay
        if self.api_circuit_breaker_threshold is not None:
            self.dify_api_circuit_breaker_threshold = self.api_circuit_breaker_threshold
        if self.api_circuit_breaker_timeout is not None:
            self.dify_api_circuit_breaker_timeout = self.api_circuit_breaker_timeout
        if self.api_batch_delay is not None:
            self.dify_api_batch_delay = self.api_batch_delay
        if self.api_batch_size is not None:
            self.dify_api_batch_size = self.api_batch_size

        # 3. Handle Session Settings
        if self.dify_convsersation_max_messages is not None:
            warn_dep("dify_convsersation_max_messages", "session_max_messages")
            if self.session_max_messages == 20:
                self.session_max_messages = self.dify_convsersation_max_messages

        if self.dify_expires_in_seconds is not None:
            warn_dep("dify_expires_in_seconds", "session_expires_seconds")
            if self.session_expires_seconds == 3600:
                self.session_expires_seconds = self.dify_expires_in_seconds

        if self.dify_share_session_in_group is not None:
            warn_dep("dify_share_session_in_group", "session_share_in_group")
            if not self.session_share_in_group:
                self.session_share_in_group = self.dify_share_session_in_group

        # 4. Handle Message Processing settings
        if self.dify_ignore_prefix is not None:
            warn_dep("dify_ignore_prefix", "ignore_prefix")
            if self.ignore_prefix == {"/", "."}:
                self.ignore_prefix = self.dify_ignore_prefix

        if self.dify_single_chat_limit is not None:
            warn_dep("dify_single_chat_limit", "message_max_length")
            if self.message_max_length == 200:
                self.message_max_length = self.dify_single_chat_limit

        if self.dify_desensitization_enable is not None:
            warn_dep("dify_desensitization_enable", "message_desensitization_enable")
            if self.message_desensitization_enable:
                self.message_desensitization_enable = self.dify_desensitization_enable

        # 5. Handle Image settings
        if self.dify_image_upload_enable is not None:
            warn_dep("dify_image_upload_enable", "image_upload_enable")
            if not self.image_upload_enable:
                self.image_upload_enable = self.dify_image_upload_enable

        if self.dify_image_cache_dir is not None:
            warn_dep("dify_image_cache_dir", "image_cache_dir")
            if self.image_cache_dir == "image":
                self.image_cache_dir = self.dify_image_cache_dir

        # 6. Handle Group Chat settings
        if self.dify_group_chat_history_limit is not None:
            warn_dep("dify_group_chat_history_limit", "group_chat_history_limit")
            if self.group_chat_history_limit == 10:
                self.group_chat_history_limit = self.dify_group_chat_history_limit

        if self.dify_group_chat_history_size is not None:
            warn_dep("dify_group_chat_history_size", "group_chat_history_size")
            if self.group_chat_history_size == 1024:
                self.group_chat_history_size = self.dify_group_chat_history_size

        # 7. Handle Profiler settings
        if self.dify_profiler_workflow_api_key is not None:
            warn_dep("dify_profiler_workflow_api_key", "profiler_workflow_api_key")
            if self.profiler_workflow_api_key == "":
                self.profiler_workflow_api_key = self.dify_profiler_workflow_api_key

        if self.dify_profiler_history_limit is not None:
            warn_dep("dify_profiler_history_limit", "profiler_history_limit")
            if self.profiler_history_limit == 50:
                self.profiler_history_limit = self.dify_profiler_history_limit

        if self.dify_profiler_min_messages is not None:
            warn_dep("dify_profiler_min_messages", "profiler_min_messages")
            if self.profiler_min_messages == 10:
                self.profiler_min_messages = self.dify_profiler_min_messages

        if self.dify_profiler_chat_history_size is not None:
            warn_dep("dify_profiler_chat_history_size", "profiler_chat_history_size")
            if self.profiler_chat_history_size == 1024:
                self.profiler_chat_history_size = self.dify_profiler_chat_history_size

        if self.dify_profiler_schedule is not None:
            warn_dep("dify_profiler_schedule", "profiler_schedule")
            if self.profiler_schedule == "0 3 * * *":
                self.profiler_schedule = self.dify_profiler_schedule

        if self.dify_default_personalization is not None:
            warn_dep("dify_default_personalization", "default_personalization")
            default_text = "你叫喵喵，是一位有点傲娇的猫娘，说话时偶尔在句末加'喵~'，但只在心情好时才会这样。你说话简洁直接，不过偶尔会露出一丝可爱。请保持回答简短，不做多余描写，不添加动作或旁白。"
            if self.default_personalization == default_text:
                self.default_personalization = self.dify_default_personalization

        # 8. Handle Private Chat settings
        if self.dify_private_personalization_enable is not None:
            warn_dep("dify_private_personalization_enable", "private_personalization_enable")
            if not self.private_personalization_enable:
                self.private_personalization_enable = self.dify_private_personalization_enable

        if self.dify_private_chat_history_limit is not None:
            warn_dep("dify_private_chat_history_limit", "private_chat_history_limit")
            if self.private_chat_history_limit == 20:
                self.private_chat_history_limit = self.dify_private_chat_history_limit

        if self.dify_private_chat_history_size is not None:
            warn_dep("dify_private_chat_history_size", "private_chat_history_size")
            if self.private_chat_history_size == 2048:
                self.private_chat_history_size = self.dify_private_chat_history_size

        if self.dify_private_profiler_min_messages is not None:
            warn_dep("dify_private_profiler_min_messages", "private_profiler_min_messages")
            if self.private_profiler_min_messages == 15:
                self.private_profiler_min_messages = self.dify_private_profiler_min_messages

        if self.dify_private_profiler_schedule is not None:
            warn_dep("dify_private_profiler_schedule", "private_profiler_schedule")
            if self.private_profiler_schedule == "0 4 * * *":
                self.private_profiler_schedule = self.dify_private_profiler_schedule

        if self.dify_private_data_retention_days is not None:
            warn_dep("dify_private_data_retention_days", "private_data_retention_days")
            if self.private_data_retention_days == 90:
                self.private_data_retention_days = self.dify_private_data_retention_days

        return self

    @model_validator(mode="after")
    def _validate_tool_config(self) -> "Config":
        """Validate Tool System configuration"""
        if self.tool_enable:
            # 1. Check Required OpenAI Configs
            if not self.tool_model_api_key:
                raise ValueError(
                    "tool_model_api_key is required when tool_enable is True. Please set TOOL_MODEL_API_KEY in .env."
                )
            # 2. Check Tool Allowlist
            if not self.tool_allowlist:
                warnings.warn(
                    "tool_enable is True but tool_allowlist is empty. No plugins will be exposed as tools.",
                    UserWarning,
                )
        elif self.tool_allowlist:
            # Tool Disabled but Allowlist present -> Warning
            warnings.warn(
                "tool_allowlist is configured but tool_enable is False. "
                "Tool system is DISABLED. Set TOOL_ENABLE=true to enable.",
                UserWarning,
            )
        return self


config = get_plugin_config(Config)
