from cachetools import TTLCache

# 用于缓存用户图片的实例，最大缓存 128 张，每张图片缓存 3 分钟 (180 秒)
USER_IMAGE_CACHE = TTLCache(maxsize=128, ttl=180)
