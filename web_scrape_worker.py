import json
import sys

from web_scrape_loader import load_requests_from_web


if __name__ == "__main__":
    # Windows 預設可能是 CP950；強制 stdout 使用 UTF-8，避免中文資料輸出失敗。
    sys.stdout.reconfigure(encoding="utf-8", errors="strict")
    url = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].strip() else None
    df = load_requests_from_web(url) if url else load_requests_from_web()
    print(json.dumps(df.to_dict(orient="records"), ensure_ascii=False))
