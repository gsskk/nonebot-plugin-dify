from typing import Set, Optional
import warnings

from nonebot import get_plugin_config
from pydantic import BaseModel, model_validator


class AppType:
    CHATBOT = "chatbot"
    CHATFLOW = "chatflow"
    AGENT = "agent"
    WORKFLOW = "workflow"


class Config(BaseModel):
    dify_api_base: str = "https://api.dify.ai/v1"
    """dify app的api url，如果是自建服务，参见dify API页面"""

    dify_main_app_api_key: str = "app-xxx"
    """dify app的api key，参见dify API页面"""

    dify_main_app_type: str = "chatbot"
    """dify助手类型 chatbot(或chatflow，对应聊天助手)/agent(对应Agent)/workflow(对应工作流)，默认为chatbot"""

    # for backward compatibility
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
    dify_api_max_retries: Optional[int] = None
    dify_api_retry_base_delay: Optional[float] = None
    dify_api_retry_max_delay: Optional[float] = None
    dify_api_circuit_breaker_threshold: Optional[int] = None
    dify_api_circuit_breaker_timeout: Optional[int] = None
    dify_api_batch_size: Optional[int] = None
    dify_api_batch_delay: Optional[float] = None

    @model_validator(mode="after")
    def _deprecate_old_vars(self) -> "Config":
        if self.dify_api_key:
            warnings.warn(
                "Config 'dify_api_key' is deprecated, please use 'dify_main_app_api_key'.",
                DeprecationWarning,
            )
            # if new key is not set (still default), use old key
            if self.dify_main_app_api_key == "app-xxx":
                self.dify_main_app_api_key = self.dify_api_key

        if self.dify_app_type:
            warnings.warn(
                "Config 'dify_app_type' is deprecated, please use 'dify_main_app_type'.",
                DeprecationWarning,
            )
            # if new type is not set (still default), use old type
            if self.dify_main_app_type == "chatbot":
                self.dify_main_app_type = self.dify_app_type
        return self

    dify_convsersation_max_messages: int = 20
    """dify目前不支持设置历史消息长度，暂时使用超过最大消息数清空会话的策略，缺点是没有滑动窗口，会突然丢失历史消息"""

    dify_ignore_prefix: Set[str] = ["/", "."]
    """忽略词，指令以本 Set 中的元素开头不会触发词库回复"""

    dify_expires_in_seconds: int = 3600
    """会话过期的时间，单位秒"""

    dify_timeout_in_seconds: int = 90
    """请求dify超时的时间，单位秒"""

    # New properly named configuration
    # Session Management
    session_max_messages: int = 20
    """会话最大消息数，超过后清空会话（由于dify不支持设置历史消息长度的限制）"""

    session_expires_seconds: int = 3600
    """会话过期的时间，单位秒"""

    session_share_in_group: bool = False
    """是否在群组里共享同一个session"""

    # Message Processing
    ignore_prefix: Set[str] = ["/", "."]
    """忽略词，指令以本 Set 中的元素开头不会触发回复"""

    message_max_length: int = 200
    """记录单条聊天消息的最大长度"""

    message_desensitization_enable: bool = True
    """是否开启消息脱敏功能，默认为True"""

    # Image Upload
    image_upload_enable: bool = False
    """是否开启图片上传功能，注意需要`nonebot_plugin_alconna`对具体adapter支持图片上传"""

    image_cache_dir: str = "image"
    """图像缓存的子目录"""

    # Group Chat Settings
    group_chat_history_limit: int = 10
    """个性化回复时在群聊中获取最近消息记录的条数"""

    group_chat_history_size: int = 1024
    """个性化回复时在群聊中获取最近消息记录的最大长度"""

    # User Profiling
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

    # Personalization
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

    # Linger Mode
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

    # Proactive Intervention (Phase 3)
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

    # API Optimization
    api_max_retries: int = 3
    """API调用最大重试次数"""

    api_retry_base_delay: float = 1.0
    """API重试基础延迟时间（秒）"""

    api_retry_max_delay: float = 30.0
    """API重试最大延迟时间（秒）"""

    api_circuit_breaker_threshold: int = 5
    """API熔断器失败阈值"""

    api_circuit_breaker_timeout: int = 300
    """API熔断器超时时间（秒）"""

    api_batch_size: int = 5
    """批处理API调用的批次大小"""

    api_batch_delay: float = 2.0
    """批次之间的延迟时间（秒）"""

    # System Monitoring
    system_admin_user_id: Optional[str] = None
    """用于接收系统关键告警的管理员的“完整用户ID”，可以通过私聊机器人发送 /get_my_id 命令获取"""

    @model_validator(mode="after")
    def _handle_backward_compatibility(self) -> "Config":
        """处理向后兼容性，将旧的dify_*变量映射到新的变量名"""

        # Handle old Dify API settings
        if self.dify_api_key:
            warnings.warn(
                "Config 'dify_api_key' is deprecated, please use 'dify_main_app_api_key'.",
                DeprecationWarning,
            )
            if self.dify_main_app_api_key == "app-xxx":
                self.dify_main_app_api_key = self.dify_api_key

        if self.dify_app_type:
            warnings.warn(
                "Config 'dify_app_type' is deprecated, please use 'dify_main_app_type'.",
                DeprecationWarning,
            )
            if self.dify_main_app_type == "chatbot":
                self.dify_main_app_type = self.dify_app_type

        # Handle session settings
        if self.dify_convsersation_max_messages is not None:
            warnings.warn(
                "Config 'dify_convsersation_max_messages' is deprecated, please use 'session_max_messages'.",
                DeprecationWarning,
            )
            if self.session_max_messages == 20:  # default value
                self.session_max_messages = self.dify_convsersation_max_messages

        if self.dify_expires_in_seconds is not None:
            warnings.warn(
                "Config 'dify_expires_in_seconds' is deprecated, please use 'session_expires_seconds'.",
                DeprecationWarning,
            )
            if self.session_expires_seconds == 3600:  # default value
                self.session_expires_seconds = self.dify_expires_in_seconds

        if self.dify_share_session_in_group is not None:
            warnings.warn(
                "Config 'dify_share_session_in_group' is deprecated, please use 'session_share_in_group'.",
                DeprecationWarning,
            )
            if not self.session_share_in_group:  # default value
                self.session_share_in_group = self.dify_share_session_in_group

        # Handle message processing settings
        if self.dify_ignore_prefix is not None:
            warnings.warn(
                "Config 'dify_ignore_prefix' is deprecated, please use 'ignore_prefix'.",
                DeprecationWarning,
            )
            if self.ignore_prefix == ["/", "."]:  # default value
                self.ignore_prefix = self.dify_ignore_prefix

        if self.dify_single_chat_limit is not None:
            warnings.warn(
                "Config 'dify_single_chat_limit' is deprecated, please use 'message_max_length'.",
                DeprecationWarning,
            )
            if self.message_max_length == 200:  # default value
                self.message_max_length = self.dify_single_chat_limit

        if self.dify_desensitization_enable is not None:
            warnings.warn(
                "Config 'dify_desensitization_enable' is deprecated, please use 'message_desensitization_enable'.",
                DeprecationWarning,
            )
            if self.message_desensitization_enable:  # default value
                self.message_desensitization_enable = self.dify_desensitization_enable

        # Handle image settings
        if self.dify_image_upload_enable is not None:
            warnings.warn(
                "Config 'dify_image_upload_enable' is deprecated, please use 'image_upload_enable'.",
                DeprecationWarning,
            )
            if not self.image_upload_enable:  # default value
                self.image_upload_enable = self.dify_image_upload_enable

        if self.dify_image_cache_dir is not None:
            warnings.warn(
                "Config 'dify_image_cache_dir' is deprecated, please use 'image_cache_dir'.",
                DeprecationWarning,
            )
            if self.image_cache_dir == "image":  # default value
                self.image_cache_dir = self.dify_image_cache_dir

        # Handle group chat settings
        if self.dify_group_chat_history_limit is not None:
            warnings.warn(
                "Config 'dify_group_chat_history_limit' is deprecated, please use 'group_chat_history_limit'.",
                DeprecationWarning,
            )
            if self.group_chat_history_limit == 10:  # default value
                self.group_chat_history_limit = self.dify_group_chat_history_limit

        if self.dify_group_chat_history_size is not None:
            warnings.warn(
                "Config 'dify_group_chat_history_size' is deprecated, please use 'group_chat_history_size'.",
                DeprecationWarning,
            )
            if self.group_chat_history_size == 1024:  # default value
                self.group_chat_history_size = self.dify_group_chat_history_size

        # Handle profiler settings
        if self.dify_profiler_workflow_api_key is not None:
            warnings.warn(
                "Config 'dify_profiler_workflow_api_key' is deprecated, please use 'profiler_workflow_api_key'.",
                DeprecationWarning,
            )
            if self.profiler_workflow_api_key == "":  # default value
                self.profiler_workflow_api_key = self.dify_profiler_workflow_api_key

        if self.dify_profiler_history_limit is not None:
            warnings.warn(
                "Config 'dify_profiler_history_limit' is deprecated, please use 'profiler_history_limit'.",
                DeprecationWarning,
            )
            if self.profiler_history_limit == 50:  # default value
                self.profiler_history_limit = self.dify_profiler_history_limit

        if self.dify_profiler_min_messages is not None:
            warnings.warn(
                "Config 'dify_profiler_min_messages' is deprecated, please use 'profiler_min_messages'.",
                DeprecationWarning,
            )
            if self.profiler_min_messages == 10:  # default value
                self.profiler_min_messages = self.dify_profiler_min_messages

        if self.dify_profiler_chat_history_size is not None:
            warnings.warn(
                "Config 'dify_profiler_chat_history_size' is deprecated, please use 'profiler_chat_history_size'.",
                DeprecationWarning,
            )
            if self.profiler_chat_history_size == 1024:  # default value
                self.profiler_chat_history_size = self.dify_profiler_chat_history_size

        if self.dify_profiler_schedule is not None:
            warnings.warn(
                "Config 'dify_profiler_schedule' is deprecated, please use 'profiler_schedule'.",
                DeprecationWarning,
            )
            if self.profiler_schedule == "0 3 * * *":  # default value
                self.profiler_schedule = self.dify_profiler_schedule

        # Handle personalization settings
        if self.dify_default_personalization is not None:
            warnings.warn(
                "Config 'dify_default_personalization' is deprecated, please use 'default_personalization'.",
                DeprecationWarning,
            )
            default_text = "你叫喵喵，是一位有点傲娇的猫娘，说话时偶尔在句末加'喵~'，但只在心情好时才会这样。你说话简洁直接，不过偶尔会露出一丝可爱。请保持回答简短，不做多余描写，不添加动作或旁白。"
            if self.default_personalization == default_text:  # default value
                self.default_personalization = self.dify_default_personalization

        # Handle private chat settings
        if self.dify_private_personalization_enable is not None:
            warnings.warn(
                "Config 'dify_private_personalization_enable' is deprecated, please use 'private_personalization_enable'.",
                DeprecationWarning,
            )
            if not self.private_personalization_enable:  # default value
                self.private_personalization_enable = self.dify_private_personalization_enable

        if self.dify_private_chat_history_limit is not None:
            warnings.warn(
                "Config 'dify_private_chat_history_limit' is deprecated, please use 'private_chat_history_limit'.",
                DeprecationWarning,
            )
            if self.private_chat_history_limit == 20:  # default value
                self.private_chat_history_limit = self.dify_private_chat_history_limit

        if self.dify_private_chat_history_size is not None:
            warnings.warn(
                "Config 'dify_private_chat_history_size' is deprecated, please use 'private_chat_history_size'.",
                DeprecationWarning,
            )
            if self.private_chat_history_size == 2048:  # default value
                self.private_chat_history_size = self.dify_private_chat_history_size

        if self.dify_private_profiler_min_messages is not None:
            warnings.warn(
                "Config 'dify_private_profiler_min_messages' is deprecated, please use 'private_profiler_min_messages'.",
                DeprecationWarning,
            )
            if self.private_profiler_min_messages == 15:  # default value
                self.private_profiler_min_messages = self.dify_private_profiler_min_messages

        if self.dify_private_profiler_schedule is not None:
            warnings.warn(
                "Config 'dify_private_profiler_schedule' is deprecated, please use 'private_profiler_schedule'.",
                DeprecationWarning,
            )
            if self.private_profiler_schedule == "0 4 * * *":  # default value
                self.private_profiler_schedule = self.dify_private_profiler_schedule

        if self.dify_private_data_retention_days is not None:
            warnings.warn(
                "Config 'dify_private_data_retention_days' is deprecated, please use 'private_data_retention_days'.",
                DeprecationWarning,
            )
            if self.private_data_retention_days == 90:  # default value
                self.private_data_retention_days = self.dify_private_data_retention_days

        # Handle API optimization settings
        if self.dify_api_max_retries is not None:
            warnings.warn(
                "Config 'dify_api_max_retries' is deprecated, please use 'api_max_retries'.",
                DeprecationWarning,
            )
            if self.api_max_retries == 3:  # default value
                self.api_max_retries = self.dify_api_max_retries

        if self.dify_api_retry_base_delay is not None:
            warnings.warn(
                "Config 'dify_api_retry_base_delay' is deprecated, please use 'api_retry_base_delay'.",
                DeprecationWarning,
            )
            if self.api_retry_base_delay == 1.0:  # default value
                self.api_retry_base_delay = self.dify_api_retry_base_delay

        if self.dify_api_retry_max_delay is not None:
            warnings.warn(
                "Config 'dify_api_retry_max_delay' is deprecated, please use 'api_retry_max_delay'.",
                DeprecationWarning,
            )
            if self.api_retry_max_delay == 30.0:  # default value
                self.api_retry_max_delay = self.dify_api_retry_max_delay

        if self.dify_api_circuit_breaker_threshold is not None:
            warnings.warn(
                "Config 'dify_api_circuit_breaker_threshold' is deprecated, please use 'api_circuit_breaker_threshold'.",
                DeprecationWarning,
            )
            if self.api_circuit_breaker_threshold == 5:  # default value
                self.api_circuit_breaker_threshold = self.dify_api_circuit_breaker_threshold

        if self.dify_api_circuit_breaker_timeout is not None:
            warnings.warn(
                "Config 'dify_api_circuit_breaker_timeout' is deprecated, please use 'api_circuit_breaker_timeout'.",
                DeprecationWarning,
            )
            if self.api_circuit_breaker_timeout == 300:  # default value
                self.api_circuit_breaker_timeout = self.dify_api_circuit_breaker_timeout

        if self.dify_api_batch_size is not None:
            warnings.warn(
                "Config 'dify_api_batch_size' is deprecated, please use 'api_batch_size'.",
                DeprecationWarning,
            )
            if self.api_batch_size == 5:  # default value
                self.api_batch_size = self.dify_api_batch_size

        if self.dify_api_batch_delay is not None:
            warnings.warn(
                "Config 'dify_api_batch_delay' is deprecated, please use 'api_batch_delay'.",
                DeprecationWarning,
            )
            if self.api_batch_delay == 2.0:  # default value
                self.api_batch_delay = self.dify_api_batch_delay

        return self


config = get_plugin_config(Config)
