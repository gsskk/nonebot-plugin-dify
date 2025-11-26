import json
from pathlib import Path

import nonebot_plugin_localstore as store

_record_file: Path = store.get_data_file("nonebot_plugin_dify", "group_record_status.json")


def _read_status() -> dict:
    if not _record_file.exists():
        return {}
    return json.loads(_record_file.read_text("utf-8"))


def _write_status(data: dict):
    _record_file.write_text(json.dumps(data, indent=4), encoding="utf-8")


def set_record_status(adapter_name: str, group_id: str, status: bool):
    """设置群组的记录状态"""
    all_statuses = _read_status()
    all_statuses[f"{adapter_name}+{group_id}"] = status
    _write_status(all_statuses)


def get_record_status(adapter_name: str, group_id: str) -> bool:
    """获取群组的记录状态，默认为 False"""
    return _read_status().get(f"{adapter_name}+{group_id}", False)
