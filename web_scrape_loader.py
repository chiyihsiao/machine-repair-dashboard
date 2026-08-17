from __future__ import annotations

import re
import shutil
from datetime import datetime
from typing import Any

import pandas as pd

SOURCE_URL = (
    "https://script.google.com/a/sanban.com.tw/macros/s/"
    "AKfycbzRm55JbcUpfuIzqSYdAlJ8HaBHdBQYdjehubL3DWFYPCZNfJz5_Xfa1h2TaOdac8JW/exec"
)
DATE_RE = re.compile(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})")
REPORT_RE = re.compile(r"[【\[]\s*(\d{1,2})/(\d{1,2})(?:\s+\d{1,2}:\d{2})?\s*完工回報")
ID_RE = re.compile(r"R20[0-9A-Za-z]+")


def load_requests_from_web(url: str = SOURCE_URL, headless: bool = True, timeout_ms: int = 60000) -> pd.DataFrame:
    """用 Playwright 讀取 Apps Script 歷史資料，並建立可分析的日期欄位。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "缺少 Playwright。請先執行：pip install playwright && playwright install chromium"
        ) from exc

    browser = None
    page = None
    records: list[dict[str, Any]] = []
    try:
        with sync_playwright() as p:
            launch_options = {
                "headless": headless,
                "args": ["--disable-gpu", "--disable-dev-shm-usage", "--no-sandbox"],
            }
            # Streamlit Cloud 透過 packages.txt 安裝系統 Chromium；本機 Windows
            # 沒有該執行檔時，則使用 playwright install 的瀏覽器。
            system_chromium = shutil.which("chromium") or shutil.which("chromium-browser")
            if system_chromium:
                launch_options["executable_path"] = system_chromium
            browser = p.chromium.launch(**launch_options)
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(8000)

            frame = None
            for candidate in page.frames:
                try:
                    if candidate.locator("#tab-history").count() > 0:
                        frame = candidate
                        break
                except Exception:
                    continue
            if frame is None:
                raise RuntimeError("找不到包含報修系統內容的 userHtmlFrame")

            frame.locator("#tab-history").wait_for(state="visible", timeout=10000)
            frame.locator("#tab-history").click()
            rows_locator = frame.locator("#historyTableBody tr")
            rows_locator.first.wait_for(state="attached", timeout=timeout_ms)
            frame.wait_for_timeout(1500)

            # allRequests 提供 completionTime 等 DOM 表格未完整顯示的欄位。
            source_records = frame.evaluate(
                """() => typeof allRequests === 'undefined' ? [] : allRequests"""
            )
            source_by_id = {
                str(item.get("id", "")).strip(): item
                for item in source_records
                if isinstance(item, dict) and item.get("id")
            }

            for row in rows_locator.all():
                cells = row.locator("td").all()
                if len(cells) < 6:
                    continue
                texts = [cell.inner_text().strip() for cell in cells]
                request_id = _extract_request_id(texts[0])
                source = source_by_id.get(request_id, {})

                application_date = _date_only(source.get("submitDate")) or _first_full_date(texts[0])
                applicant = str(source.get("applicant") or _extract_applicant(texts[0])).strip()
                target_date = _date_only(source.get("targetDate"))
                estimated_date = _date_only(source.get("estimatedCompleteDate"))
                completion_time = _date_only(source.get("completionTime"))
                completion_note = str(source.get("completionNote") or texts[5] or "").strip()
                actual_completion = completion_time or _extract_report_date(completion_note, application_date)
                status_raw = str(source.get("status") or texts[4] or "").strip()
                worker = str(source.get("worker") or _extract_worker(texts[4])).strip()

                links = _extract_row_links(row)
                if not links:
                    links = _extract_source_links(source)

                display_date = "\n".join(
                    part for part in [
                        application_date,
                        request_id,
                        applicant,
                        f"希望: {target_date}" if target_date else "",
                        f"預計: {estimated_date}" if estimated_date else "",
                    ] if part
                ) or texts[0]
                display_status = status_raw + (f"承辦：{worker}" if worker and "承辦" not in status_raw else "")
                records.append({
                    "報修單號": request_id,
                    "報修日期／單號": display_date,
                    "申請日期": application_date,
                    "申請月份": _month_label(application_date),
                    "希望完成日": target_date,
                    "預計完成日": estimated_date,
                    "實際完工日期": actual_completion,
                    "完工回報日期": actual_completion,
                    "實際完工月份": _month_label(actual_completion) if actual_completion else "未完工",
                    "完成日來源": "completionTime" if completion_time else ("完工回報備註" if actual_completion else ""),
                    "維修天數": _day_delta(application_date, actual_completion),
                    "逾期天數": _day_delta(estimated_date, actual_completion),
                    "設備名稱": str(source.get("machineName") or texts[1]).strip(),
                    "故障狀況": str(source.get("description") or texts[2]).strip(),
                    "圖片連結清單": links,
                    "目前狀態": display_status,
                    "原始狀態": status_raw,
                    "維修進度備註": completion_note,
                    "報修人": applicant or "工廠員工",
                    "承辦人": worker or "未指派/待審核",
                    "精確進度狀態": _normalize_status(status_raw),
                    "報修月份": _month_label(application_date),
                })
    except Exception as exc:
        debug_path = "web_scrape_debug.png"
        if page is not None:
            try:
                page.screenshot(path=debug_path, full_page=True)
            except Exception:
                debug_path = "無法產生截圖"
        raise RuntimeError(f"來源網頁載入或資料擷取失敗：{exc}（診斷截圖：{debug_path}）") from exc

    return pd.DataFrame(records)


def _extract_row_links(row) -> list[tuple[str, str]]:
    links = []
    for anchor in row.locator("a").all():
        label = anchor.inner_text().strip()
        href = anchor.get_attribute("href") or ""
        if label in {"報修圖", "完工圖"} and href.startswith(("http://", "https://")):
            links.append((label, href))
    return links


def _extract_source_links(source: dict[str, Any]) -> list[tuple[str, str]]:
    links = []
    for key, label in (("repairPhoto", "報修圖"), ("finishPhoto", "完工圖")):
        value = str(source.get(key) or "").strip()
        if value.startswith(("http://", "https://")):
            links.append((label, value))
    return links


def _extract_request_id(value: str) -> str:
    match = ID_RE.search(str(value or ""))
    return match.group(0) if match else ""


def _date_only(value: Any) -> str:
    match = DATE_RE.search(str(value or ""))
    return f"{match.group(1)}/{int(match.group(2)):02d}/{int(match.group(3)):02d}" if match else ""


def _first_full_date(value: str) -> str:
    return _date_only(value)


def _extract_report_date(note: str, application_date: str) -> str:
    match = REPORT_RE.search(str(note or ""))
    if not match:
        return ""
    year = int(application_date[:4]) if application_date[:4].isdigit() else datetime.now().year
    month, day = int(match.group(1)), int(match.group(2))
    if application_date and month < int(application_date[5:7]):
        year += 1
    return f"{year:04d}/{month:02d}/{day:02d}"


def _extract_applicant(value: str) -> str:
    lines = [line.strip() for line in str(value).splitlines() if line.strip()]
    for line in lines:
        if not line.startswith("R20") and not line.startswith("希望") and not line.startswith("預計") and not line.startswith("202"):
            return line
    return "工廠員工"


def _extract_worker(value: str) -> str:
    match = re.search(r"承辦[:：]\s*([^\n]+)", str(value or ""))
    return match.group(1).strip() if match else ""


def _day_delta(start: str, end: str):
    if not start or not end:
        return None
    try:
        return (datetime.strptime(end, "%Y/%m/%d") - datetime.strptime(start, "%Y/%m/%d")).days
    except ValueError:
        return None


def _normalize_status(value: str) -> str:
    value = str(value or "")
    if "已完成" in value or "完工" in value:
        return "已完成"
    if "主管已駁回" in value or "駁回" in value:
        return "主管已駁回"
    if "待驗收" in value:
        return "待主管審核"
    if "維修中" in value:
        return "維修中"
    if "待主管審核" in value:
        return "待主管審核"
    return "設備課待處理"


def _month_label(value: str) -> str:
    match = DATE_RE.search(str(value or ""))
    return f"{int(match.group(2)):02d}月" if match else "未分類"
