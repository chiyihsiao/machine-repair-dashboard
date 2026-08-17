from __future__ import annotations

import re
from typing import Iterable

import pandas as pd

ID_PATTERN = re.compile(r"(?:R20[0-9A-Za-z]+|LOCAL-\d+)")


def extract_request_id(value) -> str:
    match = ID_PATTERN.search(str(value or ""))
    return match.group(0) if match else ""


def _non_empty(value) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and pd.isna(value):
        return False
    return bool(str(value).strip()) and str(value).strip().lower() != "nan"


def merge_live_and_local(live_df: pd.DataFrame, local_df: pd.DataFrame) -> pd.DataFrame:
    """以報修單號合併即時網站資料與本地歷史資料。

    對應單號：保留本地欄位，但以來源網站的非空欄位覆蓋；
    僅在本地存在：永久保留並標記為「本地永久歷史」；
    僅在來源網站存在：加入並標記為「對方網站同步」。
    """
    live = live_df.copy() if live_df is not None else pd.DataFrame()
    local = local_df.copy() if local_df is not None else pd.DataFrame()
    for frame in (live, local):
        if "報修日期／單號" not in frame.columns:
            frame["報修日期／單號"] = ""
        frame["報修單號"] = frame["報修日期／單號"].map(extract_request_id)

    all_columns = list(dict.fromkeys([*live.columns.tolist(), *local.columns.tolist(), "資料來源", "報修單號"]))
    live_by_id = {row["報修單號"]: row for _, row in live.iterrows() if row["報修單號"]}
    local_by_id = {row["報修單號"]: row for _, row in local.iterrows() if row["報修單號"]}
    all_ids = list(dict.fromkeys([*local_by_id.keys(), *live_by_id.keys()]))

    merged_rows = []
    for request_id in all_ids:
        local_row = local_by_id.get(request_id)
        live_row = live_by_id.get(request_id)
        if local_row is not None:
            values = local_row.to_dict()
        else:
            values = {}
        if live_row is not None:
            for column, value in live_row.to_dict().items():
                if _non_empty(value):
                    values[column] = value
        values["報修單號"] = request_id
        values["資料來源"] = "對方網站同步" if live_row is not None else "本地永久歷史"
        if live_row is not None and local_row is not None:
            values["資料來源"] = "已對應／對方網站優先"
        merged_rows.append({column: values.get(column, "") for column in all_columns})

    result = pd.DataFrame(merged_rows, columns=all_columns)
    if "圖片連結清單" in result.columns:
        result["圖片連結清單"] = result["圖片連結清單"].map(_normalize_links)
    return result


def _normalize_links(value):
    if isinstance(value, list):
        return value
    if not _non_empty(value):
        return []
    # CSV／JSON 匯入時允許用 JSON 陣列保存附件連結。
    try:
        import json
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []
