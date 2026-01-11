"""
Image Reference Cache Module

Manages caching of the last received image per session to support deferred image analysis.
"""

import os
import shutil
import time
from typing import Dict, Optional
from dataclasses import dataclass
from pathlib import Path

from nonebot import logger
import nonebot_plugin_localstore as store

from ..config import config


# Keywords that indicate user wants to reference an image
IMAGE_REFERENCE_KEYWORDS = [
    # Chinese
    "这张图",
    "这个图",
    "这图",
    "上面的图",
    "上图",
    "图片里",
    "图中",
    "看看这个",
    "帮我看",
    "识别",
    "分析图",
    "图片是什么",
    "图里",
    "照片",
    "截图",
    "这个照片",
    "那张图",
    "刚才的图",
    "之前的图",
    # English
    "this image",
    "the image",
    "this picture",
    "the picture",
    "this photo",
    "the photo",
    "what's this",
    "what is this",
    "analyze this",
    "look at this",
]

# Semantic intent phrases for semantic matching mode
IMAGE_INTENT_PHRASES = [
    "请分析这张图片",
    "帮我看看这个图",
    "识别图片内容",
    "这是什么",
    "图片里是什么",
    "上图里的",
    "上面的图片",
    "分析图片",
    "图片解释",
    "描述一下图片",
    "图片说了什么",
]


@dataclass
class CachedImage:
    """Represents a cached image with metadata."""

    path: str
    timestamp: float
    session_key: str


# Global cache storage
_image_cache: Dict[str, CachedImage] = {}


def _get_session_key(adapter_name: str, group_id: Optional[str], user_id: str) -> str:
    """Generate a unique session key for caching."""
    if group_id:
        return f"{adapter_name}+{group_id}"
    else:
        return f"{adapter_name}+private+{user_id}"


def _get_cache_dir(adapter_name: str, group_id: Optional[str], user_id: str) -> Path:
    """Get the specific cache directory for a session."""
    base_dir = store.get_plugin_cache_dir() / "image_reference" / adapter_name

    if group_id:
        target_dir = base_dir / group_id
    else:
        target_dir = base_dir / f"private_{user_id}"

    return target_dir


def cache_image(
    adapter_name: str,
    group_id: Optional[str],
    user_id: str,
    image_path: str,
) -> None:
    """
    Cache an image for a session. Replaces any previously cached image.

    Args:
        adapter_name: The chat adapter name
        group_id: The group ID (None for private chats)
        user_id: The user ID
        image_path: Path to the image file
    """
    # Only cache if image_attach_mode is not "off" (caching is implicit when attach mode is enabled)
    if config.image_attach_mode == "off":
        return

    session_key = _get_session_key(adapter_name, group_id, user_id)

    # Clean up old cached image if exists (in memory check)
    old_cache = _image_cache.get(session_key)
    if old_cache and old_cache.path != image_path:
        _cleanup_cached_file(old_cache.path)

    # Create a persistent copy of the image
    # Because user_image_cache (handles immediate message processing) might delete the original file
    try:
        # Create target directory
        target_dir = _get_cache_dir(adapter_name, group_id, user_id)
        target_dir.mkdir(parents=True, exist_ok=True)

        file_name = os.path.basename(image_path)
        name, ext = os.path.splitext(file_name)

        # Create a new unique filename for the reference cache
        new_filename = f"ref_{name}_{int(time.time())}{ext}"
        new_path = target_dir / new_filename

        shutil.copy2(image_path, new_path)
        logger.debug(f"Created persistent copy for reference cache: {new_path}")

        _image_cache[session_key] = CachedImage(
            path=str(new_path),
            timestamp=time.time(),
            session_key=session_key,
        )
        logger.debug(f"Cached image for session {session_key}: {new_path}")

    except Exception as e:
        logger.warning(f"Failed to create persistent copy for image cache: {e}")
        # Fallback to using original path
        _image_cache[session_key] = CachedImage(
            path=image_path,
            timestamp=time.time(),
            session_key=session_key,
        )


def get_cached_image(
    adapter_name: str,
    group_id: Optional[str],
    user_id: str,
) -> Optional[str]:
    """
    Get the cached image path for a session if it exists and is not expired.

    Args:
        adapter_name: The chat adapter name
        group_id: The group ID (None for private chats)
        user_id: The user ID

    Returns:
        The image path if valid, None otherwise
    """
    # Only retrieve if image_attach_mode is not "off"
    if config.image_attach_mode == "off":
        return None

    session_key = _get_session_key(adapter_name, group_id, user_id)
    cached = _image_cache.get(session_key)

    if not cached:
        return None

    # Check if expired
    if time.time() - cached.timestamp > config.image_reference_cache_ttl:
        logger.debug(f"Cached image expired for session {session_key}")
        _remove_cache(session_key)
        return None

    # Check if file still exists
    if not os.path.exists(cached.path):
        logger.warning(f"Cached image file no longer exists: {cached.path}")
        _remove_cache(session_key)
        return None

    return cached.path


def should_attach_image(query: str, mode: Optional[str] = None) -> bool:
    """
    Determine if a cached image should be attached based on the query and mode.

    Args:
        query: The user's query text
        mode: The attach mode (defaults to config.image_attach_mode)

    Returns:
        True if the cached image should be attached
    """
    if mode is None:
        mode = config.image_attach_mode

    if mode == "off":
        return False

    if mode == "keyword":
        return _keyword_match(query)

    if mode == "semantic":
        # Try semantic matching, fallback to keyword if unavailable
        result = _semantic_match(query)
        if result is None:
            # Semantic matching unavailable, fallback to keyword
            logger.info("Semantic matching unavailable, falling back to keyword mode")
            return _keyword_match(query)
        return result

    logger.warning(f"Unknown image_attach_mode: {mode}, defaulting to keyword")
    return _keyword_match(query)


def _keyword_match(query: str) -> bool:
    """Check if query contains any image reference keywords."""
    query_lower = query.lower()
    for keyword in IMAGE_REFERENCE_KEYWORDS:
        if keyword.lower() in query_lower:
            logger.debug(f"Keyword match found: '{keyword}' in query")
            return True
    return False


def _semantic_match(query: str) -> Optional[bool]:
    """
    Perform semantic matching to detect image reference intent.

    Returns:
        True/False for match result, or None if semantic matching is unavailable.
    """
    try:
        if not query or len(query.strip()) < 2:
            return False

        from ..services.semantic_matcher import SemanticMatcher

        matcher = SemanticMatcher.get_instance()
        if matcher is None:
            return None

        # Check semantic similarity with image intent phrases
        # get_similarity expects a Set of interests and returns max similarity
        similarity = matcher.get_similarity(query, set(IMAGE_INTENT_PHRASES))

        if similarity > config.image_attachment_semantic_threshold:  # Threshold for image intent
            logger.debug(f"Semantic match found: similarity={similarity:.2f}")
            return True

        return False

    except ImportError:
        logger.debug("SemanticMatcher not available, cannot perform semantic matching")
        return None
    except Exception as e:
        logger.warning(f"Semantic matching failed: {e}")
        return None


def clear_expired_cache() -> int:
    """
    Remove all expired cache entries by scanning the filesystem.
    Also syncs in-memory cache.

    Returns:
        Number of entries removed
    """
    current_time = time.time()
    ttl = config.image_reference_cache_ttl
    removed_count = 0

    # 1. Scan filesystem
    cache_root = store.get_plugin_cache_dir() / "image_reference"
    if cache_root.exists():
        for root, dirs, files in os.walk(cache_root):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    stat = os.stat(file_path)
                    # Use modification time
                    if current_time - stat.st_mtime > ttl:
                        os.remove(file_path)
                        removed_count += 1
                        logger.debug(f"Removed expired cache file: {file_path}")
                except Exception as e:
                    logger.warning(f"Failed to check/remove cache file {file_path}: {e}")

            # Remove empty directories
            try:
                if root != str(cache_root) and not os.listdir(root):
                    os.rmdir(root)
            except Exception:
                pass

    # 2. Sync in-memory cache
    expired_keys = []
    for key, cached in _image_cache.items():
        # Check TTL or if file missing
        if current_time - cached.timestamp > ttl or not os.path.exists(cached.path):
            expired_keys.append(key)

    for key in expired_keys:
        _image_cache.pop(key, None)
        # Note: file deletion handled by filesystem scan above,
        # but double check here just in case (e.g. non-standard paths)

    return removed_count


def _remove_cache(session_key: str) -> None:
    """Remove a cache entry and clean up the file."""
    cached = _image_cache.pop(session_key, None)
    if cached:
        _cleanup_cached_file(cached.path)


def _cleanup_cached_file(path: str) -> None:
    """Safely remove a cached image file."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
            logger.debug(f"Cleaned up cached image file: {path}")
    except Exception as e:
        logger.warning(f"Failed to clean up cached image file {path}: {e}")


def invalidate_cache(
    adapter_name: str,
    group_id: Optional[str],
    user_id: str,
) -> None:
    """
    Explicitly invalidate the cache for a session.

    Args:
        adapter_name: The chat adapter name
        group_id: The group ID (None for private chats)
        user_id: The user ID
    """
    session_key = _get_session_key(adapter_name, group_id, user_id)
    _remove_cache(session_key)
    logger.debug(f"Invalidated image cache for session {session_key}")
