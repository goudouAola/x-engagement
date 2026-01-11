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
    conn.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, is_approved INTEGER, max_urls INTEGER DEFAULT 15)")
    conn.execute("""CREATE TABLE IF NOT EXISTS tweets 
                 (tweet_id TEXT, username TEXT, content TEXT, views TEXT, likes TEXT, 
                  bookmarks TEXT, reposts TEXT, replies TEXT, updated_at TEXT, 
                  post_time TEXT, user_owner TEXT, PRIMARY KEY(tweet_id, user_owner))""")
    conn.execute("CREATE TABLE IF NOT EXISTS watch_urls (url TEXT, user_owner TEXT, PRIMARY KEY(url, user_owner))")
    cursor = conn.execute("PRAGMA table_info(users)")
    if "max_urls" not in [row[1] for row in cursor.fetchall()]:
        conn.execute("ALTER TABLE users ADD COLUMN max_urls INTEGER DEFAULT 15")
    cursor = conn.execute("PRAGMA table_info(tweets)")
    if "replies" not in [row[1] for row in cursor.fetchall()]:
        conn.execute("ALTER TABLE tweets ADD COLUMN replies TEXT DEFAULT '0'")
    conn.execute("INSERT OR IGNORE INTO users (username, password, is_approved, max_urls) VALUES (?, ?, 1, 999)", (MASTER_KEY, MASTER_PW))
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
        tid = target_url.split('/')[-1].split('?')[0]
        username = target_url.split('/')[3]
        now = get_jst_now().strftime("%Y/%m/%d %H:%M")
        driver.get(target_url)
        time.sleep(WAIT_TIME_DETAILS)
        try:
            content_el = driver.find_element(By.XPATH, '//article[@data-testid="tweet"]//div[@data-testid="tweetText"]')
            content = content_el.text[:100]
        except: content = "【取得失敗】(制限の可能性)"
        try:
            post_time_str = driver.find_element(By.XPATH, '//article[@data-testid="tweet"]//time').get_attribute("datetime")
        except:
            post_time_str = datetime.now(timezone.utc).isoformat()
        res = {"views": "0", "likes": "0", "bookmarks": "0", "reposts": "0", "replies": "0"}
        try:
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
        except: pass
        conn = sqlite3.connect(DB_NAME)
        conn.execute("INSERT OR REPLACE INTO tweets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (tid, username, content, res["views"], res["likes"], res["bookmarks"], res["reposts"], res["replies"], now, post_time_str, owner))
        conn.commit(); conn.close(); return True
    except: return False

def scrape_all_with_multi_accounts(user_owner, progress_bar=None, status_text=None):
    conn = sqlite3.connect(DB_NAME)
    urls = pd.read_sql_query("SELECT url FROM watch_urls WHERE user_owner=?", conn, params=(user_owner,))['url'].tolist()
    max_urls_val = conn.execute("SELECT max_urls FROM users WHERE username=?", (user_owner,)).fetchone()[0]
    conn.close()
    if not urls: return
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.set_preference("intl.accept_languages", "ja-JP")
    try:
        service = Service()
        driver = webdriver.Firefox(service=service, options=opts)
        target_urls = urls[:max_urls_val]
        for i, url in enumerate(target_urls):
            if status_text: status_text.text(f"更新中... ({i+1}/{len(target_urls)})")
            scrape_single_tweet(url, driver, user_owner)
            if progress_bar: progress_bar.progress((i+1)/len(target_urls))
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
                else: st.error("承認待ち")
            else: st.error("不一致")
    with t2:
        reg_u = st.text_input("希望ID"); reg_p = st.text_input("希望PASS", type="password")
        if st.button("申請"):
            if reg_u and reg_p:
                conn = sqlite3.connect(DB_NAME)
                try: conn.execute("INSERT INTO users (username, password, is_approved, max_urls) VALUES (?, ?, 0, 15)", (reg_u, reg_p)); conn.commit(); st.success("完了")
                except: st.error("不可")
                conn.close()
else:
    user = st.session_state['auth_user']
    if st.sidebar.button("ログアウト"): st.session_state['auth_user'] = None; st.rerun()

    if user == MASTER_KEY:
        st.title("👑 管理者メニュー")
        with st.expander("⚠️ DB操作"):
            if st.button("💣 データベース完全初期化"):
                if os.path.exists(DB_NAME): os.remove(DB_NAME)
                st.session_state['auth_user'] = None; st.rerun()
        conn = sqlite3.connect(DB_NAME); unapproved = pd.read_sql_query("SELECT username FROM users WHERE is_approved=0", conn); conn.close()
        if not unapproved.empty:
            for target in unapproved["username"]:
                if st.button(f"承認: {target}"):
                    conn = sqlite3.connect(DB_NAME); conn.execute("UPDATE users SET is_approved=1 WHERE username=?", (target,)); conn.commit(); conn.close(); st.rerun()
        st.subheader("ユーザー管理")
        conn = sqlite3.connect(DB_NAME); all_users = pd.read_sql_query("SELECT * FROM users", conn); all_users["削除"] = False; conn.close()
        # 💡 width='stretch' を適用
        edited = st.data_editor(all_users, hide_index=True, width='stretch', column_config={"削除": st.column_config.CheckboxColumn("削除")})
        if st.button("💾 ユーザー情報保存"):
            conn = sqlite3.connect(DB_NAME)
            for _, r in edited.iterrows():
                if r["削除"]: conn.execute("DELETE FROM users WHERE username=?", (r["username"],))
                else: conn.execute("UPDATE users SET password=?, is_approved=?, max_urls=? WHERE username=?", (r["password"], int(r["is_approved"]), int(r["max_urls"]), r["username"]))
            conn.commit(); conn.close(); st.rerun()
    else:
        st.title(f"📊 {user}")
        conn = sqlite3.connect(DB_NAME)
        last_upd_row = conn.execute("SELECT updated_at FROM tweets WHERE user_owner=? ORDER BY updated_at DESC LIMIT 1", (user,)).fetchone()
        current_count = conn.execute("SELECT COUNT(*) FROM watch_urls WHERE user_owner=?", (user,)).fetchone()[0]
        max_urls_user = conn.execute("SELECT max_urls FROM users WHERE username=?", (user,)).fetchone()[0]
        conn.close()
        
        next_upd = "-"
        if last_upd_row:
            try:
                # ログの警告対策：年を補完して解析
                l_time = datetime.strptime(f"{datetime.now().year}/{last_upd_row[0]}", "%Y/%m/%d %H:%M")
                next_upd = (l_time + timedelta(minutes=30)).strftime("%H:%M")
            except: pass

        c1, c2, c3 = st.columns(3)
        c1.metric("最終更新", last_upd_row[0].split(' ')[1] if last_upd_row else "-")
        c2.metric("次回予定", next_upd)
        c3.metric("状況", f"{current_count}/{max_urls_user}")

        with st.sidebar:
            st.header("🔗 一括URL追加")
            multi_urls = st.text_area("改行区切りで入力", height=150)
            if st.button("一括追加", type="primary"):
                url_list = [u.strip().split('?')[0] for u in multi_urls.split('\n') if "status" in u]
                if url_list:
                    conn = sqlite3.connect(DB_NAME)
                    for clean_url in url_list:
                        temp_count = conn.execute("SELECT COUNT(*) FROM watch_urls WHERE user_owner=?", (user,)).fetchone()[0]
                        if temp_count < max_urls_user: conn.execute("INSERT OR IGNORE INTO watch_urls VALUES (?,?)", (clean_url, user))
                    conn.commit(); conn.close()
                    scrape_all_with_multi_accounts(user); st.rerun()
            if st.button("🚀 手動更新"): scrape_all_with_multi_accounts(user); st.rerun()
            if st.button("🗑️ 履歴全削除"):
                conn = sqlite3.connect(DB_NAME); conn.execute("DELETE FROM watch_urls WHERE user_owner=?", (user,)); conn.execute("DELETE FROM tweets WHERE user_owner=?", (user,)); conn.commit(); conn.close(); st.rerun()

        # 🚀 カードリスト形式表示（KeyErrorを完全排除）
        conn = sqlite3.connect(DB_NAME)
        df = pd.read_sql_query("""
            SELECT t.* FROM tweets t 
            INNER JOIN watch_urls w ON t.tweet_id = SUBSTR(w.url, INSTR(w.url, '/status/') + 8)
            WHERE t.user_owner=? AND w.user_owner=? ORDER BY t.updated_at DESC
        """, conn, params=(user, user))
        conn.close()
        
        if not df.empty:
            df["経過"] = df["post_time"].apply(get_detailed_elapsed)
            st.write("---")
            
            # 💡 削除リストを初期化
            selected_ids = []
            
            for i, row in df.iterrows():
                with st.container(border=True):
                    col_btn, col_info = st.columns([1, 2])
                    with col_btn:
                        # 💡 width='stretch' を適用
                        st.link_button("🔗 リンクを開く", f"https://twitter.com/i/web/status/{row['tweet_id']}", width='stretch')
                    with col_info:
                        st.markdown(f"**{row['username']}** | {row['updated_at']} ({row['経過']})")
                    st.caption(row['content'])
                    m1, m2, m3, m4, m5 = st.columns(5)
                    m1.metric("👁️", row['views'])
                    m2.metric("❤️", row['likes'])
                    m3.metric("🔖", row['bookmarks'])
                    m4.metric("🔁", row['reposts'])
                    m5.metric("💬", row['replies'])
                    
                    if st.checkbox("削除選択", key=f"chk_{row['tweet_id']}"):
                        selected_ids.append(row['tweet_id'])

            if selected_ids:
                if st.button(f"🗑️ 選択した {len(selected_ids)} 件を削除"):
                    conn = sqlite3.connect(DB_NAME)
                    for tid in selected_ids:
                        conn.execute("DELETE FROM watch_urls WHERE url LIKE ? AND user_owner = ?", (f"%{tid}%", user))
                        conn.execute("DELETE FROM tweets WHERE tweet_id = ? AND user_owner = ?", (tid, user))
                    conn.commit(); conn.close(); st.rerun()
