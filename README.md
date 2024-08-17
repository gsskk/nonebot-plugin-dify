# nonebot-plugin-dify


## 📖 介绍

基于 [NoneBot2](https://github.com/nonebot/nonebot2)，该插件用于对接LLMOps平台[Dify](https://github.com/langgenius/dify)。

## 💿 安装

### 使用 nb-cli 安装

在 nonebot2 项目的根目录下打开命令行, 输入以下指令即可安装

    nb plugin install nonebot-plugin-dify



### 使用包管理器安装

在 nonebot2 项目的插件目录下, 打开命令行, 根据你使用的包管理器, 输入相应的安装命令


如pip

    pip install nonebot-plugin-dify

然后打开 nonebot2 项目根目录下的 `pyproject.toml` 文件, 在 `[tool.nonebot]` 部分追加写入

    plugins = ["nonebot_plugin_dify"]



## ⚙️ 配置

在 nonebot2 项目的`.env`文件中添加下表中的配置

| 配置项 | 必填 | 默认值 |                                 说明                                 |
|:-----:|:----:|:----:|:------------------------------------------------------------------:|
| DIFY_API_BASE | 否 | https://api.dify.ai/v1 |                          DIFY API地址，支持自建                           |
| DIFY_API_KEY | 是 | 无 |                            DIFY API KEY                            |
| DIFY_APP_TYPE | 否 | chatbot |                            DIFY APP 类型                             |
| DIFY_IMAGE_UPLOAD_ENABLE | 否 | False | 是否开启上传图片，需要LLM模型支持图片识别，<br />同时需要nonebot_plugin_alconna支持相应Adapter |
| DIFY_EXPIRES_IN_SECONDS | 否 | 3600 |                               会话过期时间                               |

## 🎉 使用
### 对接不同Bot的例子
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

## 👍 特别感谢

- [hanfangyuan4396/dify-on-wechat](https://github.com/hanfangyuan4396/dify-on-wechat)
- [nonebot / nonebot2](https://github.com/nonebot/nonebot2)
