"""
Image Description Client Module

Calls external Dify workflow to generate text descriptions for images.
"""

import httpx
from typing import Optional

from nonebot import logger

from ..config import config
from ..core.dify_client import DifyClient


async def generate_image_description(image_path: str, user: str) -> Optional[str]:
    """
    Call a Dify Workflow to generate a text description for an image.

    Args:
        image_path: Path to the image file
        user: The user identifier for the API call

    Returns:
        A text description of the image, or None if generation fails
    """
    api_key = config.image_description_workflow_api_key
    if not api_key:
        logger.debug("Image description workflow API key not configured")
        return None

    try:
        # Upload the image first
        dify_client = DifyClient(api_key, config.dify_api_base)

        import mimetypes
        import os

        file_name = os.path.basename(image_path)
        file_type, _ = mimetypes.guess_type(file_name)

        with open(image_path, "rb") as f:
            files = {"file": (file_name, f, file_type)}
            upload_response = await dify_client.file_upload(user=user, files=files)
            upload_response.raise_for_status()
            upload_data = upload_response.json()
            file_id = upload_data.get("id")

        if not file_id:
            logger.error("Failed to get file ID from upload response")
            return None

        logger.debug(f"Uploaded image for description, file_id: {file_id}")

        # Call the workflow with the uploaded file
        async with httpx.AsyncClient(timeout=httpx.Timeout(config.dify_api_timeout)) as client:
            payload = {
                "inputs": {},
                "response_mode": "blocking",
                "user": user,
                "files": [{"type": "image", "transfer_method": "local_file", "upload_file_id": file_id}],
            }

            response = await client.post(
                f"{config.dify_api_base}/workflows/run",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )

            if response.status_code != 200:
                logger.error(f"Image description workflow failed: HTTP {response.status_code}")
                return None

            result = response.json()
            description = result.get("data", {}).get("outputs", {}).get("text", "")

            if description:
                # Truncate if too long
                max_len = 100
                if len(description) > max_len:
                    description = description[: max_len - 3] + "..."
                logger.debug(f"Generated image description: {description}")
                return description
            else:
                logger.warning("Image description workflow returned empty result")
                return None

    except FileNotFoundError:
        logger.error(f"Image file not found: {image_path}")
        return None
    except httpx.TimeoutException:
        logger.error("Image description workflow timed out")
        return None
    except httpx.RequestError as e:
        logger.error(f"Image description workflow request failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error generating image description: {e}")
        return None
