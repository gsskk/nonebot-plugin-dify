import os
import shutil
from typing import Literal
from PIL import Image
from nonebot import logger

from ..config import config


class ImageUtils:
    @staticmethod
    def analyze_image(path: str) -> Literal["skip", "compress", "pass"]:
        """
        Analyze the image to determine if it should be skipped, compressed, or passed as is.
        """
        try:
            if not os.path.exists(path):
                logger.warning(f"Image not found: {path}")
                return "skip"

            size = os.path.getsize(path)
            # Check config.image_min_size (default 50KB)
            if size < config.image_min_size:
                logger.debug(f"Image {path} is too small ({size} bytes), skipping.")
                return "skip"

            # Check config.image_max_size (default 1MB)
            if size > config.image_max_size:
                return "compress"

            # Check resolution
            try:
                with Image.open(path) as img:
                    width, height = img.size
                    max_res = config.image_compress_max_resolution
                    if max(width, height) > max_res:
                        return "compress"
            except Exception as e:
                logger.warning(f"Failed to open image for analysis {path}: {e}")
                return "pass"

            return "pass"
        except Exception as e:
            logger.warning(f"Failed to analyze image {path}: {e}")
            return "pass"

    @staticmethod
    def compress_image(path: str) -> str:
        """
        Compress image and overwrite the original file.
        Returns the path to the compressed image.
        """
        temp_path = path + ".tmp"
        try:
            with Image.open(path) as img:
                original_format = img.format

                width, height = img.size
                max_res = config.image_compress_max_resolution

                # Resize logic
                if max(width, height) > max_res:
                    ratio = max_res / max(width, height)
                    new_size = (int(width * ratio), int(height * ratio))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)

                # Save logic
                save_kwargs = {"optimize": True}

                # Use original format or infer from extension
                save_format = original_format
                if not save_format:
                    ext = os.path.splitext(path)[1].lower()
                    if ext in [".jpg", ".jpeg"]:
                        save_format = "JPEG"
                    elif ext == ".png":
                        save_format = "PNG"
                    elif ext == ".webp":
                        save_format = "WEBP"

                if save_format == "JPEG":
                    save_kwargs["quality"] = config.image_compress_quality
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    # Force valid JPEG if original was not

                elif save_format == "WEBP":
                    save_kwargs["quality"] = config.image_compress_quality

                # Processed img might be a copy, or original.
                # img.save will save to file.
                img.save(temp_path, format=save_format, **save_kwargs)

            shutil.move(temp_path, path)
            logger.debug(f"Image compressed to {os.path.getsize(path)} bytes")
            return path

        except Exception as e:
            logger.warning(f"Failed to compress image {path}: {e}")
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return path
