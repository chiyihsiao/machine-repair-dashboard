import html
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse
import pandas as pd
import plotly.express as px
import streamlit as st


def is_safe_url(value):
    """只允許可供使用者點擊的 HTTP(S) 圖片／附件網址。"""
    try:
        parsed = urlparse(str(value).strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


# 1. 網頁頂部全寬畫面配置
st.set_page_config(page_title="田中工廠設備報修管理戰情監控中心", layout="wide")

# 華麗的前端大標題
st.markdown("<h1 style='text-align: center; color: #1E88E5;'>🏭 田中工廠設備報修管理 ➔ 數據可視化戰情監控中心</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #757575;'>人員維度與維修進度分析</p>", unsafe_allow_html=True)
st.markdown("---")

# --- 🔐 可選密碼保護機制 ---
# 沒有 .streamlit/secrets.toml 時，直接進入分析頁面；
# 若設定 app_password，則恢復原本的登入保護。
def configured_app_password():
    try:
        return str(st.secrets["app_password"]).strip()
    except Exception:
        return ""


def check_password():
    app_password = configured_app_password()
    if not app_password:
        return True

    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
    if st.session_state["password_correct"]:
        return True

    st.markdown("<h3 style='text-align: center; color: #1E88E5; font-weight: bold;'>🏭 田中工廠報修系統 安全登入</h3>", unsafe_allow_html=True)
    user_password = st.text_input("🔑 請輸入工廠專屬連線密碼", type="password")
    if st.button("確認登入", type="primary", use_container_width=True):
        if user_password == app_password:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("❌ 密碼錯誤，請重新輸入！")
    return False

# 🌟 如果密碼正確，才執行後續所有內容
if check_password():

    # ================== 2. 核心功能：自動讀取對方 Apps Script 網頁 ==================
    from merge_records import merge_live_and_local

    def load_and_stitch_perfect_rows_cloud_final():
        try:
            source_url = st.secrets.get("source_web_app_url", "").strip()
        except Exception:
            source_url = ""
        worker = Path(__file__).with_name("web_scrape_worker.py")
        command = [sys.executable, str(worker)]
        if source_url:
            command.append(source_url)
        # Windows 首次啟動 Chromium 或網路較慢時可能超過 35 秒；保留足夠時間完成一次同步。
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "自動瀏覽器程序未正常完成")
        records = json.loads(result.stdout)
        return pd.DataFrame(records)

    try:
        with st.spinner("正在讀取對方報修資料，請稍候（最長約 90 秒）..."):
            df = load_and_stitch_perfect_rows_cloud_final()
    except Exception as e:
        st.error(f"❌ 對方網頁資料讀取失敗：{e}")
        st.info("請確認已執行：pip install playwright，並執行 playwright install chromium。")
        st.stop()

    # 可選的本地歷史資料：將你的 86 筆資料存成同資料夾的 local_records.json 或 local_records.csv。
    # 對方網站資料優先覆蓋相同報修單號；未出現在網站的31筆永久保留為本地歷史資料。
    local_path_json = Path(__file__).with_name("local_records.json")
    local_path_csv = Path(__file__).with_name("local_records.csv")
    local_df = pd.DataFrame()
    try:
        if local_path_json.exists():
            local_df = pd.DataFrame(json.loads(local_path_json.read_text(encoding="utf-8")))
        elif local_path_csv.exists():
            local_df = pd.read_csv(local_path_csv, encoding="utf-8-sig")
    except Exception as e:
        st.warning(f"⚠️ 本地歷史資料載入失敗，暫時只顯示對方網站資料：{e}")
    if not local_df.empty:
        df = merge_live_and_local(df, local_df)
        st.caption(f"目前顯示 {len(df)} 筆：55筆由對方網站同步更新，其餘本地歷史資料永久保留。")

    # 將「是否已實際完工」與來源系統的流程狀態分開，避免把待核准誤當成完工。
    df["完工狀態"] = df["實際完工日期"].fillna("").astype(str).str.strip().map(
        lambda value: "已完工" if value else "尚未完工"
    )

    # ================== 3. Streamlit 前端網頁大螢幕呈現 ==================
    if not df.empty:
        total_cases = len(df)
        completed_cases = int((df["完工狀態"] == "已完工").sum())
        pending_cases = int((df["完工狀態"] == "尚未完工").sum())
        accepted_cases = int((df["精確進度狀態"] == "已完成").sum())

        k1, k2, k3, k4 = st.columns(4)
        k1.markdown(f"<div style='background-color:#E3F2FD; padding:15px; border-radius:10px; text-align:center;'><h4 style='color:#0D47A1;margin:0;'>📋 總報修件數</h4><h2 style='color:#0D47A1;margin:5px 0;'>{total_cases} 件</h2></div>", unsafe_allow_html=True)
        k2.markdown(f"<div style='background-color:#FFEBEE; padding:15px; border-radius:10px; text-align:center;'><h4 style='color:#B71C1C;margin:0;'>⏳ 尚未完工</h4><h2 style='color:#B71C1C;margin:5px 0;'>{pending_cases} 件</h2></div>", unsafe_allow_html=True)
        k3.markdown(f"<div style='background-color:#E8F5E9; padding:15px; border-radius:10px; text-align:center;'><h4 style='color:#1B5E20;margin:0;'>✅ 已有實際完工日</h4><h2 style='color:#1B5E20;margin:5px 0;'>{completed_cases} 件</h2></div>", unsafe_allow_html=True)
        
        rate = (completed_cases / total_cases * 100) if total_cases > 0 else 0.0
        k4.markdown(f"<div style='background-color:#FFF3E0; padding:15px; border-radius:10px; text-align:center;'><h4 style='color:#E65100;margin:0;'>📈 實際完工回報率</h4><h2 style='color:#E65100;margin:5px 0;'>{rate:.1f} %</h2><small style='color:#9A3412;'>核准完成 {accepted_cases} 件</small></div>", unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("### 🔍 智慧人員與時間進度篩選系統")
        f1, f2, f3, f4 = st.columns(4)
        with f1:
            date_basis = st.selectbox("📅 月份分析依據：", ["實際完工月份", "申請月份"])
            month_column = date_basis
            available_months = ["全部月份"] + sorted(df[month_column].dropna().astype(str).unique().tolist())
            selected_month = st.selectbox(f"按【{date_basis}】查詢：", available_months)
        with f2:
            selected_user = st.selectbox("👤 按【報修人員姓名】快速篩選：", ["全部報修人"] + sorted(df["報修人"].dropna().astype(str).unique().tolist()))
        with f3:
            selected_assignee = st.selectbox("👨‍🔧 按【承辦維修人員】快速篩選：", ["全部承辦人"] + sorted(df["承辦人"].dropna().astype(str).unique().tolist()))
        with f4:
            known_statuses = ["全部狀態", "尚未完工", "已完成", "維修中", "待主管審核", "設備課待處理", "主管已駁回"]
            selected_status = st.selectbox("🚦 按【目前進度狀態】精確篩選：", known_statuses)

        filtered_df = df.copy()
        if selected_month != "全部月份": filtered_df = filtered_df[filtered_df[month_column].astype(str) == selected_month]
        if selected_user != "全部報修人": filtered_df = filtered_df[filtered_df["報修人"] == selected_user]
        if selected_assignee != "全部承辦人": filtered_df = filtered_df[filtered_df["承辦人"] == selected_assignee]
        if selected_status == "尚未完工":
            filtered_df = filtered_df[filtered_df["完工狀態"] == "尚未完工"]
        elif selected_status != "全部狀態":
            filtered_df = filtered_df[filtered_df["精確進度狀態"] == selected_status]

        # 每次篩選後都依「申請日期」由新到舊排序，沒有日期的資料固定放在最後。
        filtered_df = filtered_df.copy()
        filtered_df["_申請日期排序"] = pd.to_datetime(filtered_df["申請日期"], errors="coerce")
        filtered_df = (
            filtered_df
            .sort_values("_申請日期排序", ascending=False, na_position="last", kind="stable")
            .drop(columns=["_申請日期排序"])
        )

        st.markdown(f"💡 目前依據選單過濾出：<b style='color:#1E88E5; font-size:18px;'>{len(filtered_df)}</b> 筆符合條件的工廠報修紀錄。", unsafe_allow_html=True)
        st.markdown("---")

        col1, col2 = st.columns(2)
        color_map = {"已完成": "#2ECC71", "維修中": "#3498DB", "待主管審核": "#F39C12", "設備課待處理": "#E74C3C", "主管已駁回": "#8E44AD"}
        
        with col1:
            st.write("**🚨 篩選範圍內：全流程維修進度狀態比例 (圓餅圖)**")
            if not filtered_df.empty:
                pie_data = filtered_df["精確進度狀態"].value_counts().reset_index()
                pie_data.columns = ["狀態", "件數"]
                st.plotly_chart(px.pie(pie_data, values="件數", names="狀態", hole=0.4, height=320, color="狀態", color_discrete_map=color_map), use_container_width=True)
            else:
                st.info("無數據可顯示圓餅圖")

        with col2:
            st.write("**👨‍🔧 各工程師承辦案件狀態比例（橫向堆疊長條圖）**")
            if not filtered_df.empty:
                bar_data = filtered_df.groupby(["承辦人", "精確進度狀態"]).size().reset_index(name="件數")
                engineer_count = max(1, bar_data["承辦人"].nunique())
                bar_height = max(420, min(900, engineer_count * 72))
                fig_bar = px.bar(
                    bar_data,
                    y="承辦人",
                    x="件數",
                    color="精確進度狀態",
                    orientation="h",
                    barmode="stack",
                    text_auto=True,
                    height=bar_height,
                    template="plotly_white",
                    color_discrete_map=color_map,
                )
                fig_bar.update_traces(textposition="inside", textfont_size=13, insidetextanchor="middle")
                fig_bar.update_layout(
                    xaxis_title="總案件數量（件）",
                    yaxis_title="工程師姓名",
                    legend_title="案件狀態",
                    bargap=0.28,
                    font=dict(size=14),
                    margin=dict(l=150, r=35, t=25, b=65),
                    xaxis=dict(tickfont=dict(size=14), title_font=dict(size=16), dtick=1),
                    yaxis=dict(
                        type="category",
                        categoryorder="total ascending",
                        tickfont=dict(size=14),
                        title_font=dict(size=16),
                        automargin=True,
                    ),
                    legend=dict(font=dict(size=13), title_font=dict(size=14)),
                )
                st.plotly_chart(fig_bar, use_container_width=True)
            else:
                st.info("無數據可顯示長條圖")

        st.markdown("---")
        st.markdown("### 📋 歷史報修詳細清單")
        
        if not filtered_df.empty:
            for idx, row_data in filtered_df.iterrows():
                status_now = row_data["精確進度狀態"]
                border_color = color_map.get(status_now, "#9E9E9E")
                
                def force_get_text(val, fallback_msg=""):
                    if pd.isna(val) or str(val).strip().lower() == "nan" or str(val).strip() == "":
                        return html.escape(fallback_msg)
                    # 試算表內容一律 escape，避免文字被誤當成 HTML。
                    return html.escape(str(val)).replace("\n", "<br>")

                date_box = force_get_text(row_data.get("報修日期／單號"), "（未填日期）")
                application_box = force_get_text(row_data.get("申請日期"), "未填")
                completion_box = force_get_text(row_data.get("實際完工日期"), "尚未完工")
                completion_month_box = force_get_text(row_data.get("實際完工月份"), "未完工")
                duration_box = force_get_text(row_data.get("維修天數"), "未計算")
                delay_box = force_get_text(row_data.get("逾期天數"), "未計算")
                source_box = force_get_text(row_data.get("資料來源"), "對方網站同步")
                device_box = force_get_text(row_data.get("設備名稱"), "（未填設備）")
                trouble_box = force_get_text(row_data.get("故障狀況"), "（未填狀況）")
                status_box = force_get_text(row_data.get("目前狀態"), "（無狀態描述）")
                memo_box = force_get_text(row_data.get("維修進度備註"), "無備註")
                
                engineer_assigned = str(row_data.get("承辦人", "未指派")).strip()
                
                # 先整理附件連結，再一次放入同一張卡片；使用無縮排的 HTML，避免被 Markdown 當成程式碼。
                attachment_items = row_data.get("圖片連結清單", [])
                seen = set()
                attachment_links = []
                for item in attachment_items if isinstance(attachment_items, list) else []:
                    if not isinstance(item, (tuple, list)) or len(item) != 2:
                        continue
                    label, link_url = str(item[0]).strip(), str(item[1]).strip()
                    key = (label, link_url)
                    if key not in seen and is_safe_url(link_url):
                        seen.add(key)
                        attachment_links.append((label or "照片連結", link_url))

                links_html = ""
                if attachment_links:
                    links_html = "<div style='margin-top:10px;padding-top:10px;border-top:1px dashed #CBD5E1;background-color:#F8F9FA;'><div style='font-size:13px;color:#475569;font-weight:bold;margin-bottom:6px;'>附件</div>"
                    for label, link_url in attachment_links:
                        safe_label = html.escape(label)
                        safe_url = html.escape(link_url, quote=True)
                        links_html += f"<a href='{safe_url}' target='_blank' rel='noopener noreferrer' style='display:inline-block;margin:3px 8px 3px 0;padding:7px 10px;border:1px solid #90CAF9;border-radius:6px;background-color:#E3F2FD;color:#0D47A1;text-decoration:none;font-size:13px;font-weight:bold;'>點擊觀看 [{safe_label}]</a>"
                    links_html += "</div>"

                card_html = f"""
<div style='border-left:8px solid {border_color};background-color:#F8F9FA;padding:15px;border-radius:5px;margin-bottom:15px;box-shadow:1px 1px 5px rgba(0,0,0,0.05);'><div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;'><span style='font-size:13px;color:#666;'>📋 申請資料<br>{date_box}</span><span style='font-size:12px;color:#475569;text-align:right;'>🗓️ 實際完工日：{completion_box}<br>完工月份：{completion_month_box}</span><span style='background-color:{border_color};color:white;padding:3px 8px;border-radius:12px;font-size:12px;font-weight:bold;'>{html.escape(str(status_now))}</span></div><p style='margin:8px 0;font-size:16px;color:#111;'><b>🛠️ 設備名稱：</b><br><span style='color:#0D47A1;font-weight:bold;'>{device_box}</span></p><p style='margin:8px 0;font-size:15px;color:#333;'><b>🚨 故障狀況：</b><br>{trouble_box}</p><p style='margin:5px 0;font-size:14px;color:#2E7D32;'><b>👨‍🔧 負責工程師：</b><br><span style='background-color:#E8F5E9;padding:2px 6px;border-radius:4px;font-weight:bold;'>{html.escape(engineer_assigned)}</span></p><p style='margin:5px 0;font-size:14px;color:#444;'><b>💬 目前進度狀態：</b><br>{status_box}</p><p style='margin:5px 0;font-size:13px;color:#475569;background-color:#EEF6FF;padding:6px;border-radius:4px;border:1px solid #D7E8FA;'><b>📊 日期分析：</b>申請日 {application_box} ｜ 實際完工日 {completion_box}<br>完工月份：{completion_month_box} ｜ 維修天數：{duration_box} 天 ｜ 逾期天數：{delay_box} 天</p><p style='margin:5px 0;font-size:13px;color:#777;background-color:#FFF;padding:6px;border-radius:4px;border:1px dashed #DDD;'><b>📝 維修備註：</b><br>{memo_box}</p><p style='margin:5px 0;font-size:11px;color:#94A3B8;'>資料來源：{source_box}</p>{links_html}</div>
"""
                st.markdown(card_html, unsafe_allow_html=True)
        else:
            st.info("目前無符合篩選條件的報修案件。")
            
    else:
        st.warning("⚠️ 數據讀取成功，但清洗過後「無符合判定條件」的案件資料。請確認您的 Google 試算表中 A 欄是否包含標準日期格式 (例如 2026/08/12)。")
