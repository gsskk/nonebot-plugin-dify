from nonebot.adapters import Bot, Event
from nonebot import require, on_command, on_message, logger
from nonebot.internal.matcher.matcher import Matcher
from nonebot.plugin import PluginMetadata, inherit_supported_adapters
from nonebot.rule import Rule, to_me
from nonebot.typing import T_State

from .config import config
from .dify_bot import DifyBot
from .common.reply_type import ReplyType
from .common import memory
from .common.utils import get_pic_from_url, save_pic
import os

require("nonebot_plugin_alconna")
from nonebot_plugin_alconna import Image, At, UniMessage, image_fetch

relative_path = os.path.abspath(os.path.dirname(__file__))

dify_bot = DifyBot()

__version__ = "0.1.0"

__plugin_meta__ = PluginMetadata(
    name="dify插件",
    description="接入dify API",
    homepage="",
    usage="",
    type="application",
    config=None,
    supported_adapters=inherit_supported_adapters("nonebot_plugin_alconna"),
    extra={
        "author": "gsskk",
        "priority": 1,
        "version": __version__,
    },
)


async def ignore_rule(event: Event) -> bool:
    msg = event.get_plaintext().strip()

    # 消息以忽略词开头
    if next(
        (x for x in config.dify_ignore_prefix if msg.startswith(x)),
        None,
    ):
        return False

    # at 始终触发
    if event.is_tome():
        return True

    return False

recieve_message: type[Matcher] = on_message(
        rule=Rule(ignore_rule) & to_me(),
        priority=99,
        block=False,
    )


@recieve_message.handle()
async def _(
    bot: Bot,
    event: Event
):
    target = UniMessage.get_target()
    if target.adapter:
        adapter_name = target.adapter.replace("SupportAdapter.","").lower()
    else:
        adapter_name = "default"
    logger.debug(f"Message target adapter: {adapter_name}.")
    msg_plaintext = event.message.extract_plain_text()
    if msg_plaintext == "":
        logger.debug("Ignored empty plaintext message.")
        await recieve_message.finish()

    user_id = event.get_user_id() if event.get_user_id() else "user"
    full_user_id = f"{adapter_name}-{user_id}"
    session_id = f"s-{full_user_id}"

    _session = dify_bot.sessions.get_session(session_id, full_user_id)

    _msg = UniMessage.generate_without_reply(event=event, bot=bot)
    if _msg.has(Image):
        imgs = _msg[Image]
        _img = imgs[0]
        _img_bytes = await image_fetch(event=event, bot=bot, state=T_State, img=_img)
        if _img_bytes: 
            logger.debug(f"Got image {_img.id} from {adapter_name}.")
            
            save_dir = os.path.join(relative_path, config.dify_image_cache_dir)
            _img_path = save_pic(_img_bytes, _img, save_dir)
            memory.USER_IMAGE_CACHE[session_id] = {
                        "id": _img.id,
                        "path": _img_path
                    }
            logger.debug(f"Set image cache: {memory.USER_IMAGE_CACHE[session_id]}, local path: {_img_path}.")
        else:
            logger.warning(f"Failed to fetch image from {adapter_name}.")

    reply_type, reply_content = await dify_bot.reply(msg_plaintext, full_user_id, session_id)

    _uni_message = UniMessage()
    for _reply_type, _reply_content in zip(reply_type, reply_content):
        logger.debug(f"Ready to send {_reply_type}: {type(_reply_content)} {_reply_content}")
        if _reply_type == ReplyType.IMAGE_URL:
            _pic_content = await get_pic_from_url(_reply_content)
            _uni_message += UniMessage(Image(raw=_pic_content))
        else:
            _uni_message += UniMessage(f"{_reply_content}")

    if target.private:
        send_msg = (
                await _uni_message.export()
            )
    else:
        send_msg = (
                await UniMessage([At("user", user_id), "\n" + _uni_message]).export()
        )

    await recieve_message.finish(send_msg)
