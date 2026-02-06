import asyncio
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to sys.path to ensure we can import the plugin
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import nonebot
from nonebot import logger

# Initialize NoneBot to load configuration
nonebot.init()

# Load necessary plugins
# We need localstore for storage paths and our own plugin for logic
nonebot.load_plugin("nonebot_plugin_localstore")
# nonebot.load_plugin("nonebot_plugin_dify") # We import directly to avoid double loading issues/side effects if possible, but loading is safer for config init

# Manually importing services to avoid full bot startup overhead if possible,
# but `get_plugin_config` relies on global state.
# Let's try importing the specific functions we need.
try:
    from nonebot_plugin_dify.services.profiler import process_single_group_profile
    from nonebot_plugin_dify.services.private_profiler import process_user_profiles
except ImportError:
    # If direct import fails (e.g. due to package structure), try loading the plugin first
    nonebot.load_plugin("nonebot_plugin_dify")
    from nonebot_plugin_dify.services.profiler import process_single_group_profile
    from nonebot_plugin_dify.services.private_profiler import process_user_profiles


async def run_manual_profile(args):
    target_date = datetime.strptime(args.date, "%Y-%m-%d")

    # Parse time or use default 03:00:00
    if args.time:
        time_parts = list(map(int, args.time.split(":")))
        target_time = target_date.replace(hour=time_parts[0], minute=time_parts[1], second=time_parts[2])
    else:
        # Default to 03:00:00 as per common schedule
        target_time = target_date.replace(hour=3, minute=0, second=0)

    # Calculate window
    end_time = target_time
    start_time = end_time - timedelta(hours=24)

    logger.info("Manual Profiler Run")
    logger.info(f"Target Date: {args.date}")
    logger.info(f"Time Window: {start_time} -> {end_time}")
    logger.info(f"Type: {args.type}")
    logger.info(f"Adapter: {args.adapter}")
    logger.info(f"ID: {args.id}")

    if args.type == "group":
        await process_single_group_profile(args.adapter, args.id, start_time, end_time)
        logger.info("Group profiling task completed.")
    elif args.type == "private":
        # process_user_profiles expects a list of (adapter, user_id) tuples
        await process_user_profiles([(args.adapter, args.id)], start_time, end_time)
        logger.info("Private profiling task completed.")
    else:
        logger.error(f"Unknown type: {args.type}")


def main():
    parser = argparse.ArgumentParser(description="Manually trigger Dify profiler for a specific date/window.")
    parser.add_argument(
        "--type",
        type=str,
        required=True,
        choices=["group", "private"],
        help="Type of profiling: 'group' or 'private'",
    )
    parser.add_argument("--adapter", type=str, required=True, help="Adapter name (e.g., 'OneBot V11')")
    parser.add_argument("--id", type=str, required=True, help="Group ID or User ID")
    parser.add_argument(
        "--date",
        type=str,
        required=True,
        help="Target date in YYYY-MM-DD format (this sets the END of the 24h window)",
    )
    parser.add_argument("--time", type=str, help="Specific time in HH:MM:SS format (default: 03:00:00)")

    args = parser.parse_args()

    asyncio.run(run_manual_profile(args))


if __name__ == "__main__":
    main()
