import streamlit as st
import pandas as pd
import sqlite3
import time
import re
import os
from datetime import datetime, timezone, timedelta
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.common.by import By
from apscheduler.schedulers.background import BackgroundScheduler

# ==========================================
# ⚙️ 設定
# ==========================================
MASTER_KEY = "Hashidai00" 
MASTER_PW  = "Hashidai042210" 
DB_NAME = "x_monitor_vps.db"
WAIT_TIME_DETAILS = 15 

# ==========================================
# 🗄️ データベース・共通関数
# ==========================================
def get_jst_now():
    return datetime.now(timezone.utc) + timedelta(hours=9)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, is_approved INTEGER)")
    conn.execute("""CREATE TABLE IF NOT EXISTS tweets 
                 (tweet_id TEXT, username TEXT, content TEXT, views TEXT, likes TEXT, 
                  bookmarks TEXT, reposts TEXT, replies TEXT, updated_at TEXT, 
                  post_time TEXT, user_owner TEXT, PRIMARY KEY(tweet_id, user_owner))""")
    conn.execute("CREATE TABLE IF NOT EXISTS watch_urls (url TEXT, user_owner TEXT, PRIMARY KEY(url, user_owner))")
    cursor = conn.execute("PRAGMA table_info(tweets)")
    if "replies" not in [row[1] for row in cursor.fetchall()]:
        conn.execute("ALTER TABLE tweets ADD COLUMN replies TEXT DEFAULT '0'")
    conn.execute("INSERT OR IGNORE INTO users VALUES (?, ?, 1)", (MASTER_KEY, MASTER_PW))
    conn.commit(); conn.close()

def get_detailed_elapsed(iso_str):
    try:
        post_dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        diff = datetime.now(timezone.utc) - post_dt
        sec = int(diff.total_seconds())
        if sec < 60: return "0m"
        mins = sec // 60
        if mins < 60: return f"{mins}m"
        hrs = mins // 60
        if hrs < 24: return f"{hrs}h {mins % 60}m"
        return f"{hrs // 24}d {hrs % 24}h"
    except: return "-"

def scrape_single_tweet(target_url, driver, owner):
    try:
        driver.get(target_url)
        time.sleep(WAIT_TIME_DETAILS)
        parts = target_url.split('/')
        username, tid = parts[3], parts[5].split('?')[0]
        content = driver.find_element(By.XPATH, '//article[@data-testid="tweet"]//div[@data-testid="tweetText"]').text[:100]
        post_time_str = driver.find_element(By.XPATH, '//article[@data-testid="tweet"]//time').get_attribute("datetime")
        res = {"views": "0", "likes": "0", "bookmarks": "0", "reposts": "0", "replies": "0"}
        article = driver.find_element(By.XPATH, '//article[@data-testid="tweet"]')
        elements = article.find_elements(By.XPATH, ".//button | .//a | .//span")
        for el in elements:
            raw = el.get_attribute("aria-label") or el.text
            if not raw: continue
            m = re.search(r'([\d,.]+[KMB万億]?)', raw)
            if not m: continue
            v, low = m.group(1).replace(',', ''), raw.lower()
            if "いいね" in low or "like" in low: res["likes"] = v
            elif "リポスト" in low or "retweet" in low: res["reposts"] = v
            elif "ブックマーク" in low or "bookmark" in low: res["bookmarks"] = v
            elif "返信" in low or "reply" in low: res["replies"] = v
            elif "表示" in low or "view" in low: res["views"] = v
        now = get_jst_now().strftime("%m/%d %H:%M")
        conn = sqlite3.connect(DB_NAME)
        conn.execute("INSERT OR REPLACE INTO tweets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (tid, username, content, res["views"], res["likes"], res["bookmarks"], res["reposts"], res["replies"], now, post_time_str, owner))
        conn.commit(); conn.close(); return True
    except: return False

def scrape_all_with_multi_accounts(user_owner, progress_bar=None, status_text=None):
    conn = sqlite3.connect(DB_NAME)
    urls = pd.read_sql_query("SELECT url FROM watch_urls WHERE user_owner=?", conn, params=(user_owner,))['url'].tolist()
    conn.close()
    if not urls: return
    opts = Options()
    opts.add_argument("--headless")
    try:
        service = Service(GeckoDriverManager().install())
        driver = webdriver.Firefox(service=service, options=opts)
        for i, url in enumerate(urls[:15]):
            if status_text: status_text.text(f"更新中... ({i+1}/{len(urls[:15])})")
            scrape_single_tweet(url, driver, user_owner)
            if progress_bar: progress_bar.progress((i+1)/len(urls[:15]))
            time.sleep(5)
    finally:
        try: driver.quit()
        except: pass

def global_update_job():
    conn = sqlite3.connect(DB_NAME)
    users = pd.read_sql_query("SELECT username FROM users WHERE is_approved=1", conn)
    conn.close()
    for u in users['username']:
        if u != MASTER_KEY: scrape_all_with_multi_accounts(u)

if 'scheduler_started' not in st.session_state:
    scheduler = BackgroundScheduler()
    scheduler.add_job(global_update_job, 'interval', minutes=30, id='global_x_job')
    scheduler.start()
    st.session_state['scheduler_started'] = True

# ==========================================
# 🎨 UI
# ==========================================
st.set_page_config(page_title="X-Monitor", layout="wide")
init_db()

st.markdown("""
    <style>
    .link-box { display: flex; flex-direction: column; gap: 0px; margin-top: 35px; }
    .custom-link {
        display: flex; align-items: center; justify-content: center;
        height: 35px; text-decoration: none; background-color: #f0f2f6;
        color: black; border-radius: 4px; border: 1px solid #dcdfe6; font-size: 14px; box-sizing: border-box;
    }
    .custom-link:hover { background-color: #e0e2e6; }
    </style>
""", unsafe_allow_html=True)

if 'auth_user' not in st.session_state:
    st.session_state['auth_user'] = None

if st.session_state['auth_user'] is None:
    t1, t2 = st.tabs(["🔒 ログイン", "📝 新規登録申請"])
    with t1:
        u = st.text_input("ユーザー名"); p = st.text_input("パスワード", type="password")
        if st.button("ログイン"):
            conn = sqlite3.connect(DB_NAME); res = conn.execute("SELECT password, is_approved FROM users WHERE username=?", (u,)).fetchone(); conn.close()
            if res and p == res[0]:
                if int(res[1]) == 1: st.session_state['auth_user'] = u; st.rerun()
                else: st.error("管理者の承認待ちです")
            else: st.error("不一致")
    with t2:
        reg_u = st.text_input("希望ID"); reg_p = st.text_input("希望PASS", type="password")
        if st.button("申請する"):
            if reg_u and reg_p:
                conn = sqlite3.connect(DB_NAME)
                try: conn.execute("INSERT INTO users VALUES (?, ?, 0)", (reg_u, reg_p)); conn.commit(); st.success("申請完了")
                except: st.error("使用不可")
                conn.close()
else:
    user = st.session_state['auth_user']
    if st.sidebar.button("ログアウト"): st.session_state['auth_user'] = None; st.rerun()

    if user == MASTER_KEY:
        st.title("👑 管理者メニュー")
        
        # ⚠️ 危険な操作（DB全削除）
        with st.expander("⚠️ 危険な操作"):
            if st.button("💣 データベースを完全に初期化する"):
                if os.path.exists(DB_NAME):
                    os.remove(DB_NAME)
                    st.success("初期化完了。再読込してください。")
                    st.session_state['auth_user'] = None
                    time.sleep(2); st.rerun()
        st.write("---")

        # ✨ 承認待ちリスト
        conn = sqlite3.connect(DB_NAME)
        unapproved = pd.read_sql_query("SELECT username FROM users WHERE is_approved=0", conn)
        if not unapproved.empty:
            st.subheader("📝 承認待ちユーザー")
            for target in unapproved["username"]:
                c1, c2 = st.columns([3, 1])
                c1.write(f"申請中: **{target}**")
                if c2.button("承認", key=f"app_{target}"):
                    conn.execute("UPDATE users SET is_approved=1 WHERE username=?", (target,))
                    conn.commit(); st.rerun()
        conn.close()

        # ✨ ユーザー情報の更新・削除
        st.subheader("👥 ユーザー管理（編集・削除）")
        conn = sqlite3.connect(DB_NAME)
        all_users = pd.read_sql_query("SELECT * FROM users", conn)
        all_users["削除"] = False
        conn.close()

        # data_editorで編集可能にする
        edited_users = st.data_editor(
            all_users, 
            hide_index=True, 
            column_config={"削除": st.column_config.CheckboxColumn("削除選択", default=False)},
            use_container_width=True
        )

        if st.button("💾 変更を保存 / ユーザーを削除"):
            conn = sqlite3.connect(DB_NAME)
            for _, r in edited_users.iterrows():
                if r["削除"]:
                    # ユーザー本体、監視URL、ツイートデータをすべて消去
                    conn.execute("DELETE FROM users WHERE username=?", (r["username"],))
                    conn.execute("DELETE FROM watch_urls WHERE user_owner=?", (r["username"],))
                    conn.execute("DELETE FROM tweets WHERE user_owner=?", (r["username"],))
                else:
                    # パスワードや承認フラグを更新
                    conn.execute("UPDATE users SET password=?, is_approved=? WHERE username=?", 
                                 (r["password"], int(r["is_approved"]), r["username"]))
            conn.commit(); conn.close()
            st.success("ユーザー情報を更新しました"); time.sleep(1); st.rerun()

    else:
        # 一般ユーザー画面（メトリクス、自動更新時間、HTMLズレなしリンク等）
        st.title(f"📊 監視中 ({user})")
        conn = sqlite3.connect(DB_NAME)
        last_upd_row = conn.execute("SELECT updated_at FROM tweets WHERE user_owner=? ORDER BY updated_at DESC LIMIT 1", (user,)).fetchone()
        current_count = conn.execute("SELECT COUNT(*) FROM watch_urls WHERE user_owner=?", (user,)).fetchone()[0]
        conn.close()
        
        next_upd = "-"
        if last_upd_row:
            try:
                l_time = datetime.strptime(last_upd_row[0], "%m/%d %H:%M")
                n_time = l_time + timedelta(minutes=30)
                next_upd = n_time.strftime("%H:%M")
            except: pass

        c1, c2, c3 = st.columns(3)
        c1.metric("最終更新", last_upd_row[0].split(' ')[1] if last_upd_row else "-")
        c2.metric("次回更新予定", next_upd)
        c3.metric("登録件数", f"{current_count}/15")

        with st.sidebar:
            new_url_side = st.text_input("URL追加")
            if st.button("追加", type="primary"):
                if "status" in new_url_side:
                    conn = sqlite3.connect(DB_NAME); conn.execute("INSERT OR IGNORE INTO watch_urls VALUES (?,?)", (new_url_side.split('?')[0], user)); conn.commit(); conn.close()
                    p_bar = st.progress(0); p_status = st.empty(); scrape_all_with_multi_accounts(user, p_bar, p_status); st.rerun()
            if st.button("🚀 手動更新"):
                p_bar = st.progress(0); p_status = st.empty(); scrape_all_with_multi_accounts(user, p_bar, p_status); st.rerun()
            st.write("---")
            if st.button("🗑️ 履歴全削除"):
                conn = sqlite3.connect(DB_NAME)
                conn.execute("DELETE FROM watch_urls WHERE user_owner=?", (user,))
                conn.execute("DELETE FROM tweets WHERE user_owner=?", (user,))
                conn.commit(); conn.close(); st.rerun()

        conn = sqlite3.connect(DB_NAME)
        df = pd.read_sql_query("""
            SELECT t.* FROM tweets t 
            INNER JOIN watch_urls w ON t.tweet_id = SUBSTR(w.url, INSTR(w.url, '/status/') + 8)
            WHERE t.user_owner=? AND w.user_owner=? ORDER BY t.updated_at DESC
        """, conn, params=(user, user))
        conn.close()
        
        if not df.empty:
            df["No"] = range(1, len(df) + 1); df["経過"] = df["post_time"].apply(get_detailed_elapsed); df["選択"] = False
            col_btn, col_main = st.columns([0.4, 4.6]) 
            with col_btn:
                links_html = '<div class="link-box">'
                for _, row in df.iterrows():
                    links_html += f'<a href="https://twitter.com/i/web/status/{row["tweet_id"]}" target="_blank" class="custom-link">🔗</a>'
                links_html += '</div>'
                st.markdown(links_html, unsafe_allow_html=True)
            with col_main:
                cols = ["選択", "No", "tweet_id", "内容", "経過", "views", "likes", "bookmarks", "reposts", "replies"]
                edit_df = st.data_editor(df[cols], column_config={
                        "選択": st.column_config.CheckboxColumn("", width="small"),
                        "views": "インプ", "likes": "いいね", "bookmarks": "ブクマ", "reposts": "リポスト", "replies": "リプ"
                    }, hide_index=True, width='stretch')
            if st.button("🗑️ 選択削除"):
                sel = edit_df[edit_df["選択"]]
                if not sel.empty:
                    conn = sqlite3.connect(DB_NAME)
                    for _, r in sel.iterrows():
                        tid = str(r["tweet_id"])
                        conn.execute("DELETE FROM watch_urls WHERE url LIKE ? AND user_owner = ?", (f"%{tid}%", user))
                        conn.execute("DELETE FROM tweets WHERE tweet_id = ? AND user_owner = ?", (tid, user))
                    conn.commit(); conn.close(); st.rerun()



