import httpx
from nonebot import logger
import asyncio
import re
import os
from nonebot_plugin_alconna import Image
from typing import List, Dict


async def get_pic_from_url(url: str) -> bytes:
    logger.debug(f"Got image url {url} for download.")
    # 兼容域名`multimedia.nt.qq.com.cn`的TLS套件
    # https://github.com/LagrangeDev/Lagrange.Core/issues/315
    if "multimedia.nt.qq.com.cn" in url:
        import ssl

        SSL_CONTEXT = ssl.create_default_context()
        SSL_CONTEXT.set_ciphers("DEFAULT")  # 或设置为特定的密码套件，例如 'TLS_RSA_WITH_AES_128_CBC_SHA'
        SSL_CONTEXT.options |= ssl.OP_NO_SSLv2
        SSL_CONTEXT.options |= ssl.OP_NO_SSLv3
        SSL_CONTEXT.options |= ssl.OP_NO_TLSv1
        SSL_CONTEXT.options |= ssl.OP_NO_TLSv1_1
        SSL_CONTEXT.options |= ssl.OP_NO_COMPRESSION
        logger.debug("Set TLSv1.2 cipher for multimedia.nt.qq.com.cn.")

    async with httpx.AsyncClient() as client:
        for i in range(3):
            try:
                resp = await client.get(url, timeout=20)
                resp.raise_for_status()
                return resp.content
            except Exception as e:
                logger.error(f"Error downloading {url}, retry {i}/3: {e}")
                await asyncio.sleep(3)
    raise Exception(f"{url} 下载失败！")


def save_pic(img_bytes, img: Image, directory):
    # 获取文件名和扩展名
    filename, file_extension = os.path.splitext(img.id)

    # 如果没有扩展名，则根据mimetype来确定后缀
    if not file_extension:
        # 将mimetype转换为文件扩展名
        mimetype_to_extension = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/bmp": ".bmp",
            "image/tiff": ".tiff",
        }
        file_extension = mimetype_to_extension.get(img.mimetype, ".jpg")

    # 最终文件名
    full_filename = filename + file_extension

    # 确保目录存在
    os.makedirs(directory, exist_ok=True)

    # 保存图片
    file_path = os.path.join(directory, full_filename)
    with open(file_path, "wb") as f:
        f.write(img_bytes)

    return file_path


def parse_markdown_text(text: str) -> List[Dict]:
    """
    解析包含图片和文件链接的混合内容文本。code by sonnet3.5

    参数:
    text (str): Markdown格式文本，包含图片和文件链接

    返回:
    list: 包含不同类型内容（文本、图片、文件）的字典列表，每个字典包含类型和内容键值对

    example:

    text = "这是一篇图片与文件混合的文章\n这是图片1 ![Image1](/file/path/1.jpg)\n这是文件1 [file1](https://example.com/file.pdf)\n这是剩余的部分\n文件2 [file2](/file/path/2.docx)\n这是图片2 ![Image2](https://example.com/image2.png) 末尾文本")
    result = [
        {
            "type": "text",
            "content": "这是一篇图片与文件混合的文章\n    这是图片1"
        },
        {
            "type": "image",
            "content": "/file/path/1.jpg"
        },
        {
            "type": "text",
            "content": "这是文件1"
        },
        {
            "type": "file",
            "content": "https://example.com/file.pdf"
        },
        {
            "type": "text",
            "content": "这是剩余的部分\n    文件2"
        },
        {
            "type": "file",
            "content": "/file/path/2.docx"
        },
        {
            "type": "text",
            "content": "这是图片2"
        },
        {
            "type": "image",
            "content": "https://example.com/image2.png"
        },
        {
            "type": "text",
            "content": "末尾文本"
        }
    ]
    """

    # 定义正则表达式模式，匹配图片和文件链接的Markdown语法
    # (!\[.*?\]\((.*?)\)) 匹配图片: ![alt text](url)
    # (\[.*?\]\((.*?)\)) 匹配文件链接: [text](url)
    pattern = r"(!\[.*?\]\((.*?)\)|\[.*?\]\((.*?)\))"

    # 使用正则表达式分割文本
    # 这将产生一个列表，其中包含文本、完整匹配、图片URL和文件URL
    parts = re.split(pattern, text)

    # 初始化结果列表和当前文本变量
    result = []
    current_text = ""

    # 遍历分割后的部分，每次跳过4个元素
    # 因为每个匹配项产生4个部分：文本、完整匹配、图片URL（如果有）、文件URL（如果有）
    for i in range(0, len(parts), 4):
        # 如果存在文本部分，添加到当前文本
        if parts[i].strip():
            current_text += parts[i].strip()

        # 检查是否存在匹配项（图片或文件）
        if i + 1 < len(parts) and parts[i + 1]:
            # 如果有累积的文本，添加到结果列表
            if current_text:
                result.append({"type": "text", "content": current_text})
                current_text = ""  # 重置当前文本

            # 检查是否为图片
            if parts[i + 2]:
                result.append({"type": "image", "content": parts[i + 2]})
            # 如果不是图片，则为文件
            elif parts[i + 3]:
                result.append({"type": "file", "content": parts[i + 3]})

    # 处理最后可能剩余的文本
    if current_text:
        result.append({"type": "text", "content": current_text})
    return result
