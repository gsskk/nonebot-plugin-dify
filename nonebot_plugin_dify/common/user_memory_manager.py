import json
import re
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

import httpx
from nonebot import get_plugin_config
from nonebot.log import logger

from ..config import Config
from .private_chat_recorder import get_messages_since_private, limit_private_chat_history_length
from .user_data_store import user_profile_memory, user_personalization_memory

plugin_config = get_plugin_config(Config)


class UserMemoryManager:
    """
    Manages analysis and updating of individual user profiles and personalization data.
    Uses the same Dify workflow as group chat personalization but with private chat data.
    Includes optimizations for API usage, batching, error handling, and retry logic.
    """

    # Class-level circuit breaker state
    _circuit_breaker_failures = 0
    _circuit_breaker_last_failure = None

    def __init__(self, adapter_name: str):
        self.adapter_name = adapter_name
        self._client: Optional[httpx.AsyncClient] = None
        # Use configurable parameters
        self._max_retries = plugin_config.api_max_retries
        self._base_delay = plugin_config.api_retry_base_delay
        self._max_delay = plugin_config.api_retry_max_delay
        self._circuit_breaker_threshold = plugin_config.api_circuit_breaker_threshold
        self._circuit_breaker_timeout = plugin_config.api_circuit_breaker_timeout

    async def __aenter__(self):
        """Async context manager entry"""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(plugin_config.dify_timeout_in_seconds),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for Dify API requests"""
        api_key = plugin_config.private_profiler_workflow_api_key or plugin_config.profiler_workflow_api_key
        return {"Authorization": f"Bearer {api_key}"}

    def _is_circuit_breaker_open(self) -> bool:
        """Check if circuit breaker is open (API is considered down)"""
        if self._circuit_breaker_failures < self._circuit_breaker_threshold:
            return False

        if self._circuit_breaker_last_failure is None:
            return False

        # Check if timeout has passed
        time_since_failure = (datetime.now() - self._circuit_breaker_last_failure).total_seconds()
        if time_since_failure > self._circuit_breaker_timeout:
            # Reset circuit breaker
            UserMemoryManager._circuit_breaker_failures = 0
            UserMemoryManager._circuit_breaker_last_failure = None
            logger.info("Circuit breaker reset - attempting to reconnect to Dify API")
            return False

        return True

    def _record_api_failure(self):
        """Record an API failure for circuit breaker"""
        UserMemoryManager._circuit_breaker_failures += 1
        UserMemoryManager._circuit_breaker_last_failure = datetime.now()

        if self._circuit_breaker_failures >= self._circuit_breaker_threshold:
            logger.warning(
                f"Circuit breaker opened - Dify API appears to be down. Will retry after {self._circuit_breaker_timeout} seconds"
            )

    def _record_api_success(self):
        """Record an API success - reset circuit breaker if needed"""
        if self._circuit_breaker_failures > 0:
            logger.info("Dify API recovered - resetting circuit breaker")
            UserMemoryManager._circuit_breaker_failures = 0
            UserMemoryManager._circuit_breaker_last_failure = None

    async def _build_xml_input(self, user_id: str) -> str:
        """
        Build XML input for Dify Workflow analysis of private chat data.

        Args:
            user_id: The unique user identifier

        Returns:
            str: XML formatted input for the Dify workflow
        """
        # Get existing user profile and personalization data
        old_user_profile = user_profile_memory.get(self.adapter_name, user_id)
        old_personalization = user_personalization_memory.get(self.adapter_name, user_id)

        # Get private chat messages from the past 24 hours
        # This matches the group chat analysis pattern
        start_time = datetime.now() - timedelta(hours=24)
        all_messages = await get_messages_since_private(self.adapter_name, user_id, start_time)

        # Separate user messages and bot responses for analysis
        user_messages = [msg for msg in all_messages if msg.get("role") == "user"]
        bot_messages = [msg for msg in all_messages if msg.get("role") == "assistant"]

        # Limit message history length to prevent API limits
        user_history_str = limit_private_chat_history_length(user_messages, plugin_config.private_chat_history_size)
        bot_history_str = limit_private_chat_history_length(bot_messages, plugin_config.private_chat_history_size)

        # Build XML structure similar to group chat but for individual user
        xml_input = f"""<context>
<user_profile>
{old_user_profile}
</user_profile>

<user_messages>
{user_history_str}
</user_messages>

<bot_responses>
{bot_history_str}
</bot_responses>

<personalization>
<previous>
{old_personalization}
</previous>
<recent_interactions>
{user_history_str}
</recent_interactions>
</personalization>
</context>"""
        return xml_input

    async def _call_dify_workflow_with_retry(self, payload: Dict, user_id: str = None) -> Optional[Dict]:
        last_exception = None

        for attempt in range(self._max_retries):
            try:
                if not self._client:
                    raise RuntimeError("HTTP client not initialized. Use async context manager.")

                response = await self._client.post(
                    f"{plugin_config.dify_api_base}/workflows/run",
                    headers=self._get_headers(),
                    json=payload,
                )

                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:
                    logger.warning(f"Rate limited by Dify API (attempt {attempt + 1}/{self._max_retries})")
                    if attempt < self._max_retries - 1:
                        delay = min(self._base_delay * (2**attempt), self._max_delay)
                        await asyncio.sleep(delay)
                        continue
                elif response.status_code >= 500:
                    logger.error(f"Server error {response.status_code} from Dify API")
                    if attempt < self._max_retries - 1:
                        delay = min(self._base_delay * (2**attempt), self._max_delay)
                        await asyncio.sleep(delay)
                        continue
                else:
                    logger.error(f"Client error {response.status_code} from Dify API")
                    return None

            except httpx.TimeoutException as e:
                last_exception = e
                logger.error(f"Timeout calling Dify API (attempt {attempt + 1}/{self._max_retries})")
                if attempt < self._max_retries - 1:
                    delay = min(self._base_delay * (2**attempt), self._max_delay)
                    await asyncio.sleep(delay)
                    continue

            except httpx.RequestError as e:
                last_exception = e
                logger.error(f"Request error calling Dify API: {e}")
                if attempt < self._max_retries - 1:
                    delay = min(self._base_delay * (2**attempt), self._max_delay)
                    await asyncio.sleep(delay)
                    continue

            except Exception as e:
                last_exception = e
                logger.error(f"Unexpected error calling Dify API: {e}")
                if attempt < self._max_retries - 1:
                    delay = min(self._base_delay * (2**attempt), self._max_delay)
                    await asyncio.sleep(delay)
                    continue

        logger.error(f"Failed to call Dify API after {self._max_retries} attempts", exc_info=last_exception)
        return None

    async def update_user_memory(self, user_id: str) -> bool:
        logger.info(f"开始更新用户 {self.adapter_name}+private+{user_id} 的画像和个性化要求...")

        try:
            xml_input = await self._build_xml_input(user_id)

            payload = {
                "inputs": {"query": xml_input},
                "response_mode": "blocking",
                "user": f"{self.adapter_name}+private+{user_id}",
            }

            rsp_data = await self._call_dify_workflow_with_retry(payload, user_id)
            if not rsp_data:
                logger.error("Failed to get response from Dify workflow")
                return False

            result = rsp_data.get("data", {}).get("outputs", {}).get("text", "")

            if result:
                success = await self._process_workflow_result(user_id, result)
                if success:
                    logger.info(f"用户 {user_id} 的画像和个性化要求更新流程成功完成。")
                    return True
                else:
                    logger.error("Failed to process workflow result")
                    return False
            else:
                logger.warning("Dify Workflow returned no output")
                return False

        except Exception as e:
            logger.error(f"Error updating user memory: {e}")
            return False

    async def _process_workflow_result(self, user_id: str, result: str) -> bool:
        try:
            cleaned_result = re.sub(r"<think>.*?</think>", "", result, flags=re.DOTALL).strip()
            parsed_result = json.loads(cleaned_result)

            new_user_profile = parsed_result.get("user_profile", "")
            new_personalization_summary = parsed_result.get("personalization_summary", "")

            profile_updated = False
            personalization_updated = False

            if new_user_profile:
                try:
                    user_profile_memory.set(self.adapter_name, user_id, new_user_profile)
                    logger.info(f"用户 {user_id} 画像更新成功。")
                    profile_updated = True
                except Exception as e:
                    logger.error(f"Failed to update user profile: {e}")
            else:
                logger.debug(f"Dify Workflow 未返回新的用户画像，用户 {user_id} 画像未更新。")

            if new_personalization_summary:
                try:
                    user_personalization_memory.set(self.adapter_name, user_id, new_personalization_summary)
                    logger.info(f"用户 {user_id} 个性化要求总结更新成功。")
                    personalization_updated = True
                except Exception as e:
                    logger.error(f"Failed to update user personalization: {e}")
            else:
                logger.debug(f"Dify Workflow 未返回新的个性化要求总结，用户 {user_id} 个性化要求未更新。")

            return profile_updated or personalization_updated

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON format from Dify Workflow: {e}")
            return False
        except Exception as e:
            logger.error(f"Error processing workflow result: {e}")
            return False

    async def batch_update_users(
        self, user_ids: list[str], batch_size: int = 5, delay_between_batches: float = 2.0
    ) -> Tuple[int, int]:
        """
        Update multiple users in batches to optimize API usage.

        Args:
            user_ids: List of user IDs to update
            batch_size: Number of users to process concurrently in each batch
            delay_between_batches: Delay in seconds between batches to avoid rate limiting

        Returns:
            Tuple[int, int]: (successful_updates, total_users)
        """
        logger.info(f"开始批量更新 {len(user_ids)} 个用户的画像 (batch_size={batch_size})")

        successful_updates = 0
        total_users = len(user_ids)

        # Process users in batches
        for i in range(0, total_users, batch_size):
            batch = user_ids[i : i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (total_users + batch_size - 1) // batch_size

            logger.info(f"处理批次 {batch_num}/{total_batches} ({len(batch)} 个用户)")

            # Create tasks for this batch
            tasks = [self.update_user_memory(user_id) for user_id in batch]

            # Execute batch concurrently
            try:
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Count successful updates in this batch
                batch_success = 0
                for j, result in enumerate(results):
                    if isinstance(result, Exception):
                        logger.error(f"批次 {batch_num} 中用户 {batch[j]} 更新失败: {result}")
                    elif result is True:
                        batch_success += 1
                        successful_updates += 1
                    else:
                        logger.warning(f"批次 {batch_num} 中用户 {batch[j]} 更新未成功")

                logger.info(f"批次 {batch_num} 完成: {batch_success}/{len(batch)} 个用户更新成功")

                # Delay between batches (except for the last batch)
                if i + batch_size < total_users:
                    logger.debug(f"等待 {delay_between_batches} 秒后处理下一批次...")
                    await asyncio.sleep(delay_between_batches)

            except Exception as e:
                logger.error(f"批次 {batch_num} 处理时发生错误: {e}")
                continue

        logger.info(f"批量更新完成: {successful_updates}/{total_users} 个用户更新成功")
        return successful_updates, total_users
