# nonebot-plugin-dify

## 📖 介绍

基于 [NoneBot2](https://github.com/nonebot/nonebot2)，该插件用于对接LLMOps平台[Dify](https://github.com/langgenius/dify)。

它不仅仅是一个简单的转发器，更是一个拥有长期记忆、个性化画像、甚至能主动参与群聊的智能体。

## 💿 安装

### 使用 nb-cli 安装

在 nonebot2 项目的根目录下打开命令行, 输入以下指令即可安装

```bash
nb plugin install nonebot-plugin-dify
```

如果需要使用**主动介入（Proactive Mode）**功能，请安装额外依赖：

```bash
pip install "nonebot-plugin-dify[semantic]"
```

### 使用包管理器安装

在 nonebot2 项目的插件目录下, 打开命令行, 根据你使用的包管理器, 输入相应的安装命令

如pip

```bash
pip install nonebot-plugin-dify
```

如果需要使用**主动介入（Proactive Mode）**功能，请安装额外依赖：

```bash
pip install "nonebot-plugin-dify[semantic]"
```

然后打开 nonebot2 项目根目录下的 `pyproject.toml` 文件, 在 `[tool.nonebot]` 部分追加写入

```toml
plugins = ["nonebot_plugin_dify"]
```

## ⚙️ 配置

在 nonebot2 项目的`.env`文件中添加核心配置。

**📚 完整配置列表与说明请参阅 [配置详细指南](docs/configuration.md)。**

### 核心配置示例

```env
DIFY_API_BASE=https://api.dify.ai/v1
DIFY_MAIN_APP_API_KEY=app-xxxxxxxxxxx
DIFY_MAIN_APP_TYPE=chatflow
DIFY_API_TIMEOUT=90
```

## ✨ 功能特性

本插件支持多种高级功能，包括：
- **流式输出**: 像打字一样逐段回复，降低感知延迟。
- **跨插件感知**: 感知并接管其他插件的输出。
- **私聊/群聊个性化**: 自动生成用户画像，提供定制化回复。
- **余韵模式**: 被 @ 后自动维持一段时间的对话上下文。
- **主动介入**: 基于语义匹配自动参与感兴趣的话题。
- **插件工具化**: 将 NoneBot 插件转化为可调用的 Tools。

**👉 详细功能介绍请参阅 [高级功能指南](docs/features.md)。**

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