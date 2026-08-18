from __future__ import annotations

import html
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


st.set_page_config(
    page_title="田中工廠設備報修｜管理儀表板",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


STATUS_COLORS = {
    "已完成": "#16A34A",
    "維修中": "#2563EB",
    "待主管審核": "#D97706",
    "設備課待處理": "#DC2626",
    "主管已駁回": "#7C3AED",
    "尚未完工": "#DC2626",
}
PENDING_STATUSES = {"維修中", "待主管審核", "設備課待處理", "主管已駁回"}


def safe_url(value: str) -> bool:
    try:
        parsed = urlparse(str(value).strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def secret_value(key: str, fallback: str = "") -> str:
    try:
        return str(st.secrets[key]).strip()
    except Exception:
        return fallback


def check_password() -> bool:
    password = secret_value("app_password")
    if not password:
        return True
    if st.session_state.get("password_correct", False):
        return True
    st.markdown("## 🔐 報修管理儀表板登入")
    entered = st.text_input("請輸入系統密碼", type="password")
    if st.button("登入", type="primary"):
        if entered == password:
            st.session_state["password_correct"] = True
            st.rerun()
        st.error("密碼錯誤。")
    return False


def load_dashboard_data() -> pd.DataFrame:
    source_url = secret_value(
        "source_web_app_url",
        "https://script.google.com/a/sanban.com.tw/macros/s/AKfycbzRm55JbcUpfuIzqSYdAlJ8HaBHdBQYdjehubL3DWFYPCZNfJz5_Xfa1h2TaOdac8JW/exec",
    )
    worker = Path(__file__).with_name("web_scrape_worker.py")
    result = subprocess.run(
        [sys.executable, str(worker), source_url],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "自動擷取程序未正常完成")
    live_df = pd.DataFrame(json.loads(result.stdout))

    local_json = Path(__file__).with_name("local_records.json")
    local_csv = Path(__file__).with_name("local_records.csv")
    local_df = pd.DataFrame()
    if local_json.exists():
        local_df = pd.DataFrame(json.loads(local_json.read_text(encoding="utf-8")))
    elif local_csv.exists():
        local_df = pd.read_csv(local_csv, encoding="utf-8-sig")

    if not local_df.empty:
        from merge_records import merge_live_and_local
        return merge_live_and_local(live_df, local_df)
    return live_df


def prepare_data(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    defaults = {
        "精確進度狀態": "設備課待處理",
        "承辦人": "未指派/待審核",
        "報修人": "未提供",
        "申請日期": "",
        "申請月份": "未分類",
        "實際完工日期": "",
        "實際完工月份": "未完工",
        "完工狀態": "尚未完工",
        "希望完成日": "",
        "預計完成日": "",
        "維修天數": None,
        "逾期天數": None,
        "資料來源": "對方網站同步",
        "維修進度備註": "",
        "圖片連結清單": [[] for _ in range(len(result))],
    }
    for column, default in defaults.items():
        if column not in result.columns:
            result[column] = default
    result["申請日期_dt"] = pd.to_datetime(result["申請日期"], errors="coerce")
    result["實際完工日期_dt"] = pd.to_datetime(result["實際完工日期"], errors="coerce")
    result["完工狀態"] = result["實際完工日期_dt"].notna().map({True: "已完工", False: "尚未完工"})
    result["逾期天數_num"] = pd.to_numeric(result["逾期天數"], errors="coerce")
    result["維修天數_num"] = pd.to_numeric(result["維修天數"], errors="coerce")
    result["風險"] = "正常"
    result.loc[result["精確進度狀態"].isin(PENDING_STATUSES), "風險"] = "待處理"
    result.loc[result["逾期天數_num"].gt(0).fillna(False), "風險"] = "已逾期"
    result.loc[result["精確進度狀態"].eq("主管已駁回"), "風險"] = "已駁回"
    result["顯示日期"] = result["申請日期_dt"].dt.strftime("%Y/%m/%d").fillna("未填日期")
    return result


def fmt_number(value) -> str:
    if pd.isna(value):
        return "—"
    try:
        return f"{float(value):.1f}" if float(value) % 1 else f"{int(value)}"
    except Exception:
        return str(value)


def render_case_card(row: pd.Series) -> None:
    status = str(row.get("精確進度狀態", "未判定"))
    risk = str(row.get("風險", "正常"))
    case_id = str(row.get("報修單號", "未編號"))
    device = str(row.get("設備名稱", "未填設備"))
    title = f"{case_id}｜{device}｜{status}"
    with st.expander(title, expanded=False):
        top1, top2, top3, top4 = st.columns(4)
        top1.metric("申請日期", str(row.get("申請日期", "未填")))
        top2.metric("實際完工日", str(row.get("實際完工日期", "尚未完工")))
        top3.metric("維修天數", f"{fmt_number(row.get('維修天數'))} 天")
        top4.metric("逾期天數", f"{fmt_number(row.get('逾期天數'))} 天")
        st.caption(f"流程狀態：{status}　｜　完工狀態：{row.get('完工狀態', '尚未完工')}　｜　風險：{risk}　｜　資料來源：{row.get('資料來源', '對方網站同步')}")
        left, right = st.columns([1, 1])
        with left:
            st.markdown(f"**設備名稱**：{html.escape(device)}")
            st.markdown(f"**報修人**：{html.escape(str(row.get('報修人', '未提供')))}")
            st.markdown(f"**承辦人**：{html.escape(str(row.get('承辦人', '未指派')))}")
            st.markdown(f"**預計完成日**：{html.escape(str(row.get('預計完成日', '未填')))}")
        with right:
            st.markdown(f"**故障狀況**：{html.escape(str(row.get('故障狀況', '未填')))}")
            st.markdown(f"**目前狀態**：{html.escape(str(row.get('目前狀態', '未填')))}")
        with st.expander("查看維修備註", expanded=False):
            st.text(str(row.get("維修進度備註", "無備註")))
        links = row.get("圖片連結清單", [])
        valid_links = []
        if isinstance(links, list):
            for item in links:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    label, url = str(item[0]), str(item[1])
                    if safe_url(url) and (label, url) not in valid_links:
                        valid_links.append((label, url))
        if valid_links:
            st.markdown("**附件**")
            link_cols = st.columns(min(3, len(valid_links)))
            for index, (label, url) in enumerate(valid_links):
                with link_cols[index % len(link_cols)]:
                    st.link_button(f"查看{label}", url, use_container_width=True)


if check_password():
    st.title("田中工廠設備報修管理")
    st.caption("86筆案件｜55筆對方網站同步＋31筆本地永久歷史｜以實際完工日分析")

    with st.sidebar:
        st.header("控制面板")
        if st.button("🔄 重新抓取對方資料", use_container_width=True):
            st.rerun()
        st.caption("每次載入都直接抓取對方網頁最新資料；首次或重新整理可能需要10～60秒。")

    try:
        with st.spinner("正在同步資料並整理儀表板，請稍候..."):
            df = prepare_data(load_dashboard_data())
    except Exception as exc:
        st.error(f"資料同步失敗：{exc}")
        st.stop()

    # ---- 篩選區 ----
    with st.sidebar:
        st.header("篩選條件")
        date_basis = st.radio("月份依據", ["實際完工月份", "申請月份"], index=0)
        month_values = sorted(df[date_basis].dropna().astype(str).unique().tolist())
        selected_months = st.multiselect("月份", month_values, default=month_values)
        completion_states = ["尚未完工", "已完工"]
        selected_completion_states = st.multiselect("完工狀態", completion_states, default=completion_states)
        statuses = sorted(df["精確進度狀態"].dropna().astype(str).unique().tolist())
        selected_statuses = st.multiselect("流程狀態", statuses, default=statuses)
        assignees = sorted(df["承辦人"].dropna().astype(str).unique().tolist())
        selected_assignees = st.multiselect("承辦人", assignees, default=assignees)
        risk_values = ["正常", "待處理", "已逾期", "已駁回"]
        selected_risks = st.multiselect("風險分類", risk_values, default=risk_values)
        keyword = st.text_input("搜尋案件", placeholder="單號、設備、故障狀況、報修人")

    filtered = df[
        df[date_basis].astype(str).isin(selected_months)
        & df["完工狀態"].astype(str).isin(selected_completion_states)
        & df["精確進度狀態"].astype(str).isin(selected_statuses)
        & df["承辦人"].astype(str).isin(selected_assignees)
        & df["風險"].astype(str).isin(selected_risks)
    ].copy()
    if keyword.strip():
        search_columns = ["報修單號", "設備名稱", "故障狀況", "報修人", "承辦人", "維修進度備註"]
        mask = filtered[search_columns].fillna("").astype(str).agg(" ".join, axis=1).str.contains(keyword.strip(), case=False, na=False)
        filtered = filtered[mask]

    # ---- KPI ----
    total = len(filtered)
    completed = int((filtered["完工狀態"] == "已完工").sum())
    pending = int((filtered["完工狀態"] == "尚未完工").sum())
    overdue = int(filtered["逾期天數_num"].gt(0).fillna(False).sum())
    avg_days = filtered["維修天數_num"].dropna().mean()
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("目前案件", f"{total} 件")
    k2.metric("尚未完工", f"{pending} 件")
    k3.metric("已有實際完工日", f"{completed} 件")
    k4.metric("逾期案件", f"{overdue} 件", delta="需優先關注" if overdue else "目前無逾期", delta_color="inverse")
    k5.metric("平均維修天數", f"{fmt_number(avg_days)} 天")
    st.caption(f"目前篩選：{total} 件；月份分析依據為「{date_basis}」。")

    # ---- 主管先看區 ----
    st.subheader("一、先看需要處理的案件")
    risk_df = filtered[filtered["風險"].isin(["已逾期", "待處理", "已駁回"])].copy()
    if risk_df.empty:
        st.success("目前篩選範圍內沒有逾期或待處理案件。")
    else:
        risk_view = risk_df[["報修單號", "設備名稱", "精確進度狀態", "風險", "承辦人", "申請日期", "預計完成日", "實際完工日期", "逾期天數"]].copy()
        risk_view["逾期天數"] = risk_view["逾期天數"].map(fmt_number)
        st.dataframe(risk_view, hide_index=True, use_container_width=True)

    # ---- 趨勢與分布 ----
    st.subheader("二、整體趨勢與分布")
    c1, c2 = st.columns(2)
    with c1:
        status_counts = filtered["精確進度狀態"].value_counts().rename_axis("狀態").reset_index(name="件數")
        fig = px.pie(status_counts, names="狀態", values="件數", hole=0.5, color="狀態", color_discrete_map=STATUS_COLORS)
        fig.update_layout(title="案件狀態分布", margin=dict(t=55, l=10, r=10, b=10), legend_title="")
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        month_order = [f"{m:02d}月" for m in range(1, 13)]
        application = filtered["申請月份"].value_counts().reindex(month_order, fill_value=0)
        completed_month = filtered["實際完工月份"].value_counts().reindex(month_order, fill_value=0)
        trend = pd.DataFrame({"月份": month_order, "申請件數": application.values, "完工件數": completed_month.values})
        fig = go.Figure()
        fig.add_bar(x=trend["月份"], y=trend["申請件數"], name="申請件數", marker_color="#93C5FD")
        fig.add_bar(x=trend["月份"], y=trend["完工件數"], name="實際完工件數", marker_color="#16A34A")
        fig.update_layout(title="申請與實際完工月份比較", barmode="group", height=380, margin=dict(t=55, l=10, r=10, b=10), legend_title="")
        st.plotly_chart(fig, use_container_width=True)

    c3, c4 = st.columns(2)
    with c3:
        assignee = filtered["承辦人"].value_counts().sort_values().reset_index()
        assignee.columns = ["承辦人", "案件數"]
        fig = px.bar(assignee, x="案件數", y="承辦人", orientation="h", text_auto=True, title="承辦案件量")
        fig.update_layout(height=360, margin=dict(t=55, l=10, r=10, b=10), showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
    with c4:
        days = filtered[filtered["維修天數_num"].notna()][["承辦人", "維修天數_num"]].copy()
        if days.empty:
            st.info("目前沒有足夠的完工日期可計算維修天數。")
        else:
            days = days.groupby("承辦人", as_index=False)["維修天數_num"].median().sort_values("維修天數_num")
            days.columns = ["承辦人", "中位維修天數"]
            fig = px.bar(days, x="中位維修天數", y="承辦人", orientation="h", text_auto=True, title="各承辦人中位維修天數")
            fig.update_layout(height=360, margin=dict(t=55, l=10, r=10, b=10), showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

    # ---- 明細 ----
    st.subheader("三、案件明細")
    if filtered.empty:
        st.info("目前篩選條件沒有案件。")
    else:
        st.caption("案件預設收合；點開案件即可查看完整備註與報修圖／完工圖。")
        for _, row in filtered.sort_values(["風險", "申請日期_dt"], ascending=[True, False]).iterrows():
            render_case_card(row)

    with st.expander("資料品質與欄位說明"):
        st.write(f"目前資料共 {len(df)} 筆，其中對方網站同步 {int((df['資料來源'] == '對方網站同步').sum())} 筆，本地永久歷史 {int((df['資料來源'] == '本地永久歷史').sum())} 筆。")
        st.write("月份篩選預設使用實際完工月份；未完工案件會歸入「未完工」。完工狀態依是否存在實際完工日期判定，維修天數為實際完工日減申請日，逾期天數為實際完工日減預計完成日。")
