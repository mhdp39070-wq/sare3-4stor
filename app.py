import os
import json
import uuid
import time
import threading
import urllib.parse
import random
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import wraps
import requests
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, request, jsonify, render_template_string, session, redirect, url_for, g
import pg8000.dbapi

# ================= الإعدادات =================
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "sare3_store_super_secret_key_2026")

MHD_API_TOKEN = os.environ.get("MHD_API_TOKEN", "T7um19tGzZVl2sdz09Z8WnlojsWn8TLDNwFrxT1qcvTBJgk6wtuxI6v9miom")
API_BASE_URL = "https://mhd-game.com/api"
MHD_PRODUCTS_URL = f"{API_BASE_URL}/client/api/products"

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "sare3admin@gmail.com")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "m7md_570")

SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "sare3admin@gmail.com")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "ools coaj pggr gnwi")
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 465))

# إعدادات قاعدة بيانات Supabase
DB_USER = os.environ.get("DB_USER", "postgres.mqmxgnghuapisgpgtrla")
DB_PASS = os.environ.get("DB_PASS", "mlpoknbji0$570")
DB_HOST = os.environ.get("DB_HOST", "aws-1-eu-west-1.pooler.supabase.com")
DB_PORT = int(os.environ.get("DB_PORT", 6543))
DB_NAME = os.environ.get("DB_NAME", "postgres")

http_session = requests.Session()


# ================= قاعدة البيانات السحابية (Supabase) المسرّعة =================
def create_raw_connection():
    return pg8000.dbapi.connect(
        user=DB_USER,
        password=DB_PASS,
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME
    )

def get_db():
    try:
        if 'db' not in g:
            g.db = create_raw_connection()
        return g.db
    except RuntimeError:
        return create_raw_connection()

@app.teardown_appcontext
def close_db_connection(exception):
    db = g.pop('db', None)
    if db is not None:
        try:
            db.close()
        except Exception:
            pass

class DictRow(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)

class DictCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, query, params=None):
        if params is not None:
            return self._cursor.execute(query, tuple(params))
        return self._cursor.execute(query)

    def fetchone(self):
        row = self._cursor.fetchone()
        if not row:
            return None
        cols = [c[0] for c in self._cursor.description]
        return DictRow(dict(zip(cols, row)))

    def fetchall(self):
        rows = self._cursor.fetchall()
        if not rows:
            return []
        cols = [c[0] for c in self._cursor.description]
        return [DictRow(dict(zip(cols, r))) for r in rows]

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def close(self):
        self._cursor.close()

def get_cursor(conn):
    return DictCursor(conn.cursor())


def init_db():
    try:
        conn = get_db()
        c = get_cursor(conn)

        c.execute("""CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE,
            password TEXT,
            balance DOUBLE PRECISION DEFAULT 0.0,
            is_admin INT DEFAULT 0,
            is_banned INT DEFAULT 0,
            vip_level TEXT DEFAULT 'auto'
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS email_verifications (
            email TEXT PRIMARY KEY,
            code TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS categories (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE,
            image_url TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS subcategories (
            id SERIAL PRIMARY KEY,
            name TEXT,
            cat_id INT,
            image_url TEXT,
            UNIQUE(name, cat_id)
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            mhd_id INT,
            sub_id INT,
            name TEXT,
            price DOUBLE PRECISION,
            product_type TEXT DEFAULT 'digital',
            image_url TEXT,
            available INT DEFAULT 1,
            requires_player_id INT DEFAULT 1,
            description TEXT,
            api_data TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            order_uuid TEXT UNIQUE,
            user_id INT,
            product_name TEXT,
            price DOUBLE PRECISION,
            status TEXT,
            replay_api TEXT,
            qty DOUBLE PRECISION DEFAULT 1,
            player_id TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS payment_methods (
            code TEXT PRIMARY KEY,
            name TEXT,
            description TEXT,
            wallet_address TEXT,
            active INT DEFAULT 1
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS deposits (
            id SERIAL PRIMARY KEY,
            user_id INT,
            method TEXT,
            trans_id TEXT,
            amount_usd DOUBLE PRECISION,
            raw_amount DOUBLE PRECISION,
            currency TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW()
        )""")

        default_settings = [
            ('store_status', 'open'),
            ('store_margin_percent', '0'),
            ('exchange_rate', '15000'),
            ('support_telegram', 'SARE3_STOR_Support'),
            ('support_whatsapp', '0997062693'),
            ('banner_title', 'يا أهلاً وسهلاً'),
            ('banner_desc', 'نورت موقعنا يا صديقي | شحن فوري ومباشر 24/7')
        ]
        for k, v in default_settings:
            c.execute("""INSERT INTO settings(key, value) VALUES(%s, %s)
                         ON CONFLICT (key) DO NOTHING""", (k, v))

        admin_hash = generate_password_hash(ADMIN_PASS)
        c.execute("SELECT id FROM users WHERE username = %s", (ADMIN_EMAIL.lower(),))
        row = c.fetchone()
        if not row:
            c.execute("""INSERT INTO users(username, password, balance, is_admin, vip_level) 
                         VALUES(%s, %s, 100000.0, 1, 'VIPmax')""", 
                      (ADMIN_EMAIL.lower(), admin_hash))
        else:
            c.execute("""UPDATE users SET password = %s, is_admin = 1, vip_level = 'VIPmax' 
                         WHERE username = %s""", (admin_hash, ADMIN_EMAIL.lower()))

        c.execute("SELECT COUNT(*) as count FROM payment_methods")
        if c.fetchone()['count'] == 0:
            default_pays = [
                ('binance', 'Binance Pay (دولار)', 'يرجى التحويل المباشر عبر ميزة Binance Pay برقم الحساب التالي:', '1192954957', 1),
                ('syriatel', 'سيرياتيل كاش (ليرة سورية)', 'يرجى التحويل إلى رقم سيرياتيل كاش المرفق مع إدخال رقم المعاملة:', '67997320', 1),
                ('bep20', 'USDT BEP20 (دولار)', 'إرسال عملة USDT عبر شبكة BSC (BEP20) إلى العنوان التالي:', '0xe8688d65f474253e290c1b7491ee2b0799784ad0', 1)
            ]
            for p in default_pays:
                c.execute("""INSERT INTO payment_methods(code, name, description, wallet_address, active) 
                             VALUES(%s, %s, %s, %s, %s)
                             ON CONFLICT (code) DO NOTHING""", p)

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ خطأ أثناء تهيئة قاعدة البيانات: {e}")


# ================= دوال مساعدة =================
def send_otp_email(recipient_email, otp_code):
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"سريع ستور <{SMTP_EMAIL}>"
        msg["To"] = recipient_email
        msg["Subject"] = "تأكيد حسابك في متجر سريع"

        text_content = f"مرحباً بك،\nرمز تأكيد بريدك الإلكتروني هو: {otp_code}\nصالح للاستخدام لمرة واحدة.\nسريع ستور"
        html_content = f"""
        <!DOCTYPE html>
        <html lang="ar" dir="rtl">
        <body style="font-family: Arial, sans-serif; background-color: #ffffff; color: #1e293b; padding: 20px;">
            <div style="max-width: 480px; margin: 0 auto; border: 1px solid #cbd5e1; border-radius: 8px; padding: 24px;">
                <h3 style="margin-top: 0; color: #0f172a;">مرحباً بك في سريع ستور</h3>
                <p style="font-size: 14px; color: #475569;">رمز التحقق الخاص بك هو:</p>
                <div style="background-color: #f1f5f9; border-radius: 6px; padding: 16px; text-align: center; margin: 20px 0;">
                    <span style="font-size: 26px; font-weight: bold; letter-spacing: 4px; color: #0f172a;">{otp_code}</span>
                </div>
            </div>
        </body>
        </html>
        """
        msg.attach(MIMEText(text_content, "plain", "utf-8"))
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"❌ خطأ إرسال الإيميل: {e}")
        return False


def get_setting(key, default="", conn=None):
    try:
        if conn is None:
            conn = get_db()
        c = get_cursor(conn)
        c.execute("SELECT value FROM settings WHERE key=%s", (key,))
        row = c.fetchone()
        return row["value"] if row else default
    except Exception:
        return default


def get_exchange_rate(conn=None):
    try:
        val = float(get_setting("exchange_rate", "15000", conn=conn))
        return val if val > 0 else 15000.0
    except Exception:
        return 15000.0


def get_margin_percent(conn=None):
    try:
        return float(get_setting("store_margin_percent", "0", conn=conn))
    except Exception:
        return 0.0


def apply_margin(base_price, conn=None):
    margin = get_margin_percent(conn=conn)
    return float(base_price or 0) * (1 + margin / 100.0)


def get_user_vip_info(user_id, conn=None):
    if not user_id:
        return {"level": "VIP1", "tag": "v1", "discount": 0.0, "spent": 0.0}
    try:
        if conn is None:
            conn = get_db()
        c = get_cursor(conn)
        c.execute("SELECT vip_level FROM users WHERE id=%s", (user_id,))
        row = c.fetchone()
        manual_vip = row["vip_level"] if row and row["vip_level"] else "auto"

        c.execute("SELECT SUM(price) as total FROM orders WHERE user_id=%s AND status IN ('accept', 'مكتمل')", (user_id,))
        res = c.fetchone()["total"]
        total_spent = float(res or 0.0)

        if manual_vip != "auto":
            if manual_vip == "VIPmax":
                return {"level": "VIPmax", "tag": "vmax", "discount": 0.01, "spent": total_spent}
            elif manual_vip == "VIP3":
                return {"level": "VIP3", "tag": "v3", "discount": 0.0, "spent": total_spent}
            elif manual_vip == "VIP2":
                return {"level": "VIP2", "tag": "v2", "discount": 0.0, "spent": total_spent}
            return {"level": "VIP1", "tag": "v1", "discount": 0.0, "spent": total_spent}

        if total_spent > 500:
            return {"level": "VIPmax", "tag": "vmax", "discount": 0.01, "spent": total_spent}
        elif total_spent > 400:
            return {"level": "VIP3", "tag": "v3", "discount": 0.0, "spent": total_spent}
        elif total_spent > 200:
            return {"level": "VIP2", "tag": "v2", "discount": 0.0, "spent": total_spent}
        return {"level": "VIP1", "tag": "v1", "discount": 0.0, "spent": total_spent}
    except Exception:
        return {"level": "VIP1", "tag": "v1", "discount": 0.0, "spent": 0.0}


def fetch_api_product(mhd_id):
    try:
        r = http_session.get(MHD_PRODUCTS_URL, headers={"api-token": MHD_API_TOKEN, "Accept": "application/json"}, timeout=15)
        if r.status_code == 200:
            payload = r.json()
            items = payload if isinstance(payload, list) else payload.get("data", [])
            for item in items:
                if str(item.get("id") or item.get("product_id")) == str(mhd_id):
                    return item
    except Exception as e:
        print(f"❌ خطأ جلب المنتج من API: {e}")
    return None


def replay_extract(info):
    if not info:
        return ""
    if isinstance(info, list):
        info = info[0] if len(info) > 0 else {}
    if not isinstance(info, dict):
        return str(info).strip()

    for k in ("account_data", "accountData", "account", "replay_api", "replay", "reply", "code", "notes", "note", "response"):
        val = info.get(k)
        if val and str(val).strip().lower() not in {"none", "null"}:
            if isinstance(val, (dict, list)):
                return json.dumps(val, ensure_ascii=False)
            return str(val).strip()

    return ""


def check_if_requires_id(product_name, category_name=""):
    text = f"{product_name} {category_name}".lower()
    digital_keywords = ["كود", "أكواد", "اكواد", "بطاقة", "بطاقات", "كرت", "كروت", "حساب", "حسابات", "قسيمة", "code", "card", "gift", "voucher", "account", "outlook", "gmail"]
    for kw in digital_keywords:
        if kw in text:
            return 0
    return 1


def login_required(f):
    @wraps(f)
    def dec(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"status": "error", "message": "يجب تسجيل الدخول أولاً"}), 401
        return f(*args, **kwargs)
    return dec


def admin_required(f):
    @wraps(f)
    def dec(*args, **kwargs):
        if "user_id" not in session or not session.get("is_admin"):
            return jsonify({"status": "error", "message": "غير مصرح لك"}), 403
        return f(*args, **kwargs)
    return dec


# ================= تتبع الطلبات الخلفي =================
def background_order_tracker():
    while True:
        try:
            time.sleep(25)
            conn = create_raw_connection()
            c = get_cursor(conn)
            c.execute("""SELECT id, order_uuid, user_id, price, status, 
                                EXTRACT(EPOCH FROM (NOW() - created_at)) as age_sec 
                         FROM orders 
                         WHERE status NOT IN ('accept', 'reject', 'مكتمل', 'مرفوض')""")
            pending = c.fetchall()

            for ord_row in pending:
                oid = ord_row["id"]
                ouuid = ord_row["order_uuid"]
                uid = ord_row["user_id"]
                amt = ord_row["price"]
                age = ord_row["age_sec"] or 0

                if age > 172800:
                    c.execute("UPDATE orders SET status='reject', replay_api='تم الإلغاء تلقائياً لتجاوز 48 ساعة' WHERE id=%s", (oid,))
                    c.execute("UPDATE users SET balance = balance + %s WHERE id=%s", (amt, uid))
                    conn.commit()
                    continue

                url = f"{API_BASE_URL}/client/api/check?orders=[{urllib.parse.quote(str(ouuid))}]&uuid=1"
                try:
                    r = http_session.get(url, headers={"api-token": MHD_API_TOKEN, "Accept": "application/json"}, timeout=15)
                    if r.status_code == 200:
                        payload = r.json()
                        data_block = payload.get("data", [{}])[0] if isinstance(payload.get("data"), list) and payload.get("data") else payload
                        st = str(data_block.get("status") or data_block.get("order_status") or "").lower()
                        rep = replay_extract(data_block)

                        if any(x in st for x in ("accept", "complete", "success", "مكتمل")):
                            c.execute("UPDATE orders SET status='accept', replay_api=%s WHERE id=%s", (rep, oid))
                            conn.commit()
                        elif any(x in st for x in ("reject", "refuse", "fail", "مرفوض")):
                            c.execute("UPDATE orders SET status='reject', replay_api=%s WHERE id=%s", (rep, oid))
                            c.execute("UPDATE users SET balance = balance + %s WHERE id=%s", (amt, uid))
                            conn.commit()
                        elif rep:
                            c.execute("UPDATE orders SET replay_api=%s WHERE id=%s", (rep, oid))
                            conn.commit()
                except Exception:
                    pass
            conn.close()
        except Exception:
            pass


# ================= الواجهة والتنسيقات =================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>SARE3 STOR | المتجر المباشر</title>
    <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800;900&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root {
            --bg-page: #f8fafc;
            --card-bg: #ffffff;
            --text-dark: #0f172a;
            --text-muted: #64748b;
            --neon-green: #00ff66;
            --neon-green-dark: #00cc55;
            --neon-glow: rgba(0, 255, 102, 0.28);
            --border-light: #e2e8f0;
            --accent-red: #ef4444;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Cairo', sans-serif; -webkit-tap-highlight-color: transparent; }
        body { background-color: var(--bg-page); color: var(--text-dark); min-height: 100vh; padding-bottom: 90px; overflow-x: hidden; }

        .top-navbar {
            background: #ffffff; border-bottom: 1px solid var(--border-light); position: sticky; top: 0; z-index: 100;
            padding: 0.65rem 0.85rem; display: flex; justify-content: space-between; align-items: center;
            box-shadow: 0 4px 15px rgba(0,0,0,0.03);
        }
        .nav-right-box { display: flex; align-items: center; gap: 0.5rem; flex-shrink: 0; }
        .menu-burger-btn {
            background: none; border: none; font-size: 1.35rem; color: var(--text-dark);
            cursor: pointer; display: flex; align-items: center; justify-content: center;
            padding: 0.2rem;
        }
        .brand-title { font-size: 1.15rem; font-weight: 900; color: var(--text-dark); text-decoration: none; white-space: nowrap; }
        .brand-title span { color: var(--neon-green-dark); }
        .top-actions { display: flex; align-items: center; gap: 0.4rem; flex-shrink: 0; }

        .wallet-pill {
            background: #f1f5f9; border: 1px solid var(--border-light); border-radius: 50px;
            padding: 0.25rem 0.4rem 0.25rem 0.65rem; display: flex; align-items: center; gap: 0.35rem;
            font-weight: 800; font-size: 0.85rem; color: var(--text-dark); white-space: nowrap;
        }
        .add-balance-btn {
            background: var(--neon-green-dark); color: #fff; border: none; width: 22px; height: 22px;
            border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 0.95rem;
            cursor: pointer; font-weight: bold; transition: all 0.2s;
        }
        .add-balance-btn:hover { background: var(--neon-green); transform: scale(1.1); color: #000; }

        .container { max-width: 900px; margin: 0 auto; padding: 1rem; }

        .banners-carousel-wrapper {
            position: relative;
            width: 100%;
            border-radius: 24px;
            overflow: hidden;
            margin-bottom: 1.2rem;
            box-shadow: 0 16px 36px rgba(15, 23, 42, 0.16);
            background: #0f172a;
        }
        .banners-slides-container {
            display: flex;
            transition: transform 0.65s cubic-bezier(0.25, 1, 0.5, 1);
            width: 100%;
        }
        .banner-slide-item {
            min-width: 100%;
            display: block;
            text-decoration: none;
            box-sizing: border-box;
            border-radius: 24px;
            padding: 1.35rem 1.4rem;
            color: #ffffff;
            position: relative;
            overflow: hidden;
            min-height: 112px;
        }

        .banner-slide-item::before {
            content: '';
            position: absolute;
            top: -60%;
            left: -60%;
            width: 220%;
            height: 220%;
            background: linear-gradient(65deg, transparent 35%, rgba(255, 255, 255, 0.12) 50%, transparent 65%);
            transform: rotate(25deg);
            pointer-events: none;
            animation: lightShimmer 6s infinite ease-in-out;
        }
        @keyframes lightShimmer {
            0% { transform: translateX(-100%) rotate(25deg); }
            50%, 100% { transform: translateX(100%) rotate(25deg); }
        }

        .slide-telegram {
            background: radial-gradient(circle at 100% 0%, #0ea5e9 0%, #0284c7 45%, #034b75 100%);
            border: 1px solid rgba(14, 165, 233, 0.45);
        }

        .slide-welcome {
            background: radial-gradient(circle at 0% 100%, #15803d 0%, #0f172a 50%, #020617 100%);
            border: 1px solid rgba(0, 255, 102, 0.35);
        }

        .slide-content-box {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            position: relative;
            z-index: 2;
        }
        .slide-right-side {
            display: flex;
            align-items: center;
            gap: 0.95rem;
        }

        .slide-icon-circle {
            width: 54px;
            height: 54px;
            border-radius: 18px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.75rem;
            flex-shrink: 0;
            transition: all 0.3s ease;
        }
        .slide-telegram .slide-icon-circle {
            background: #ffffff;
            color: #0284c7;
            box-shadow: 0 8px 20px rgba(0, 0, 0, 0.25), 0 0 16px rgba(255, 255, 255, 0.4);
        }
        .slide-welcome .slide-icon-circle {
            background: linear-gradient(135deg, rgba(0, 255, 102, 0.25), rgba(0, 204, 85, 0.05));
            color: var(--neon-green);
            border: 1.5px solid var(--neon-green);
            box-shadow: 0 8px 20px rgba(0, 255, 102, 0.25), inset 0 0 12px rgba(0, 255, 102, 0.2);
        }

        .slide-text h3 {
            font-size: 0.88rem;
            font-weight: 800;
            margin: 0;
            color: #f1f5f9;
            line-height: 1.25;
            letter-spacing: -0.2px;
            text-shadow: 0 1px 3px rgba(0,0,0,0.4);
        }
        .slide-text h2 {
            font-size: 1.45rem;
            font-weight: 900;
            margin: 0.15rem 0 0 0;
            line-height: 1.2;
            letter-spacing: 0.4px;
        }
        .slide-telegram .slide-text h2 {
            color: #fde047;
            text-shadow: 0 2px 10px rgba(253, 224, 71, 0.4);
        }
        .slide-welcome .slide-text h2 {
            color: #ffffff;
        }
        .slide-welcome .slide-text h2 span {
            color: var(--neon-green);
            text-shadow: 0 0 14px rgba(0, 255, 102, 0.55);
        }

        .slide-btn-badge {
            font-weight: 900;
            font-size: 0.82rem;
            padding: 0.5rem 1rem;
            border-radius: 50px;
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            white-space: nowrap;
            transition: all 0.25s ease;
        }
        .slide-telegram .slide-btn-badge {
            background: #ffffff;
            color: #0369a1;
            box-shadow: 0 6px 16px rgba(0, 0, 0, 0.2);
        }
        .slide-welcome .slide-btn-badge {
            background: linear-gradient(135deg, var(--neon-green), var(--neon-green-dark));
            color: #042f2e;
            box-shadow: 0 6px 18px var(--neon-glow);
        }
        .banner-slide-item:hover .slide-btn-badge {
            transform: scale(1.05);
        }

        .carousel-indicators {
            position: absolute;
            bottom: 8px;
            left: 50%;
            transform: translateX(-50%);
            display: flex;
            align-items: center;
            gap: 6px;
            z-index: 5;
        }
        .indicator-dot {
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.35);
            cursor: pointer;
            transition: all 0.35s cubic-bezier(0.34, 1.56, 0.64, 1);
        }
        .indicator-dot.active {
            width: 24px;
            border-radius: 12px;
            background: #ffffff;
            box-shadow: 0 0 10px rgba(255, 255, 255, 0.8);
        }

        .marquee-seamless-container {
            background: #ffffff;
            border: 1px solid var(--border-light);
            border-radius: 50px;
            padding: 0.6rem 0;
            margin-bottom: 1.5rem;
            box-shadow: 0 3px 12px rgba(0, 0, 0, 0.03);
            overflow: hidden;
            display: flex;
            position: relative;
            width: 100%;
        }
        .marquee-seamless-track {
            display: flex;
            width: max-content;
            animation: seamlessMove 20s linear infinite;
        }
        .marquee-seamless-container:hover .marquee-seamless-track {
            animation-play-state: paused;
        }
        .marquee-seamless-block {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0 2rem;
            white-space: nowrap;
            font-size: 0.9rem;
            font-weight: 800;
            color: #0f172a;
        }
        @keyframes seamlessMove {
            0% { transform: translateX(0); }
            100% { transform: translateX(50%); }
        }

        .section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.2rem; }
        .section-title { font-size: 1.2rem; font-weight: 800; border-right: 4px solid var(--neon-green-dark); padding-right: 0.6rem; }

        .category-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.85rem; margin-bottom: 1.5rem; }
        .category-card {
            background: #ffffff; border: 1px solid var(--border-light); border-radius: 18px; overflow: hidden;
            display: flex; flex-direction: column; cursor: pointer; box-shadow: 0 4px 12px rgba(0,0,0,0.03);
            transition: all 0.25s ease;
        }
        .category-card:hover { border-color: var(--neon-green-dark); box-shadow: 0 8px 20px var(--neon-glow); }
        .category-img { width: 100%; height: 95px; object-fit: cover; background: #e2e8f0; }
        .category-name { padding: 0.6rem 0.2rem; text-align: center; font-size: 0.82rem; font-weight: 800; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

        .products-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.9rem; }
        .product-card {
            background: #ffffff; border: 1px solid var(--border-light); border-radius: 20px; padding: 1rem;
            display: flex; flex-direction: column; justify-content: space-between; box-shadow: 0 4px 14px rgba(0,0,0,0.03);
            transition: all 0.25s ease;
        }
        .product-card:hover { border-color: var(--neon-green); transform: translateY(-2px); box-shadow: 0 8px 20px var(--neon-glow); }
        .product-img { width: 100%; height: 90px; object-fit: cover; border-radius: 12px; margin-bottom: 0.5rem; background: #f1f5f9; }
        .product-title { font-size: 0.95rem; font-weight: 800; color: var(--text-dark); margin-top: 0.2rem; }
        .product-price { font-size: 1.2rem; font-weight: 900; color: var(--neon-green-dark); margin: 0.5rem 0; }

        .bottom-nav {
            position: fixed; bottom: 0; left: 0; right: 0; background: #ffffff; border-top: 1px solid var(--border-light);
            display: flex; justify-content: space-around; padding: 0.7rem 0; z-index: 100;
            box-shadow: 0 -4px 15px rgba(0,0,0,0.04);
        }
        .nav-tab { display: flex; flex-direction: column; align-items: center; gap: 0.2rem; font-size: 0.75rem; font-weight: 700; color: var(--text-muted); text-decoration: none; cursor: pointer; width: 25%; }
        .nav-tab.active { color: var(--neon-green-dark); }

        .receipt-card {
            background: #ffffff; border-radius: 18px; padding: 1.2rem; margin-bottom: 1rem;
            border: 1px solid var(--border-light); border-right: 4px solid var(--neon-green-dark);
            box-shadow: 0 4px 12px rgba(0,0,0,0.03);
        }
        .receipt-row { display: flex; justify-content: space-between; align-items: center; padding: 0.6rem 0; border-bottom: 1px dashed var(--border-light); font-size: 0.88rem; }
        .receipt-row:last-child { border-bottom: none; }
        .receipt-label { color: var(--text-muted); font-weight: 600; }
        .receipt-value { font-weight: 800; color: var(--text-dark); }

        .btn {
            background: var(--text-dark); color: #fff; border: none; padding: 0.55rem 0.9rem; border-radius: 14px;
            font-weight: 800; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; gap: 0.4rem;
            transition: all 0.2s ease; font-size: 0.85rem;
        }
        .btn:active { transform: scale(0.96); }
        .btn-green { background: var(--neon-green-dark); color: #fff; box-shadow: 0 4px 12px var(--neon-glow); }
        .btn-green:hover { background: var(--neon-green); color: #000; }
        .btn-danger { background: #fee2e2; color: #ef4444; }
        .btn-warning { background: #fef3c7; color: #d97706; }
        .btn-warning:hover { background: #fde68a; }
        .btn-blue { background: #e0f2fe; color: #0284c7; }

        .modal-overlay {
            position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.65); backdrop-filter: blur(6px);
            display: none; justify-content: center; align-items: center; z-index: 1000; padding: 1rem;
        }
        .modal {
            background: #ffffff; border-radius: 24px; width: 100%; max-width: 480px; padding: 1.6rem;
            max-height: 90vh; overflow-y: auto; box-shadow: 0 20px 40px rgba(0,0,0,0.2);
        }

        .form-group { margin-bottom: 1.1rem; }
        .form-group label { display: block; margin-bottom: 0.4rem; font-size: 0.85rem; font-weight: 700; color: var(--text-dark); }
        .form-input {
            width: 100%; background: #f8fafc; border: 1px solid var(--border-light); border-radius: 14px;
            padding: 0.8rem 1rem; outline: none; font-size: 0.95rem; font-weight: 600;
        }
        .form-input:focus { border-color: var(--neon-green-dark); background: #ffffff; }

        .drawer-overlay {
            position: fixed; top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0, 0, 0, 0.5); backdrop-filter: blur(4px);
            z-index: 1200; display: none; opacity: 0; transition: opacity 0.3s ease;
        }
        .drawer-overlay.active { display: block; opacity: 1; }

        .drawer-panel {
            position: fixed; top: 0; right: -320px; width: 300px; max-width: 85%; height: 100%;
            background: #ffffff; z-index: 1300; transition: right 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            overflow-y: auto; display: flex; flex-direction: column; padding: 1.2rem 1rem;
            box-shadow: -5px 0 25px rgba(0,0,0,0.15); border-left: 3px solid var(--neon-green-dark);
        }
        .drawer-panel.active { right: 0; }

        .drawer-user-card {
            background: #fff; border: 1px solid #dcfce7; border-radius: 20px; padding: 1.2rem 1rem;
            text-align: center; margin-bottom: 0.8rem; box-shadow: 0 4px 15px rgba(0, 204, 0, 0.06);
        }
        .drawer-username { font-weight: 900; font-size: 1rem; color: #0f172a; }
        .drawer-email { font-size: 0.78rem; color: #64748b; margin-bottom: 0.8rem; }
        .drawer-stat-pill {
            background: #ffffff; border: 1px solid #dcfce7; border-radius: 14px;
            padding: 0.7rem 1rem; margin-bottom: 0.6rem; display: flex; justify-content: space-between;
            align-items: center; font-size: 0.85rem; font-weight: 800; color: #0f172a;
        }
        .drawer-stat-pill .val-green { color: var(--neon-green-dark); direction: ltr; font-weight: 900; }
        .drawer-section-title { font-size: 0.8rem; font-weight: 800; color: #94a3b8; margin: 1rem 0.5rem 0.4rem; }
        .drawer-menu-list { list-style: none; display: flex; flex-direction: column; gap: 0.2rem; }
        .drawer-menu-link {
            display: flex; align-items: center; gap: 0.85rem; padding: 0.65rem 0.8rem;
            color: #1e293b; text-decoration: none; font-size: 0.9rem; font-weight: 700;
            border-radius: 12px; cursor: pointer;
        }
        .drawer-menu-link:hover { background: #f0fdf4; color: var(--neon-green-dark); }

        .vip-badge {
            display: inline-block; background: #ecfdf5; color: var(--neon-green-dark); border: 1px solid #a7f3d0;
            border-radius: 50px; padding: 0.2rem 0.7rem; font-size: 0.8rem; font-weight: 900; margin-bottom: 0.4rem;
        }

        .admin-dashboard-wrapper { display: flex; flex-direction: column; gap: 1rem; width: 100%; }
        .admin-sidebar {
            width: 100%; background: #ffffff; border: 1px solid var(--border-light);
            border-radius: 18px; padding: 0.5rem; display: flex; flex-direction: row;
            gap: 0.5rem; overflow-x: auto; white-space: nowrap; scrollbar-width: none;
        }
        .admin-sidebar::-webkit-scrollbar { display: none; }
        .admin-sidebar-btn {
            background: #f8fafc; border: 1px solid var(--border-light); padding: 0.55rem 0.9rem;
            border-radius: 12px; color: #334155; font-size: 0.82rem; font-weight: 800;
            display: inline-flex; align-items: center; gap: 0.4rem; cursor: pointer; flex-shrink: 0;
        }
        .admin-sidebar-btn.active { background: #fee2e2; color: #ef4444; border-color: #fca5a5; }

        .admin-main-content { width: 100%; }
        .admin-stats-grid-row1 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.65rem; margin-bottom: 0.65rem; }
        @media (min-width: 650px) { .admin-stats-grid-row1 { grid-template-columns: repeat(4, 1fr); } }

        .admin-stats-grid-row2 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.65rem; margin-bottom: 1.2rem; }
        @media (max-width: 500px) { .admin-stats-grid-row2 { grid-template-columns: 1fr; } }

        .adm-stat-box {
            background: #ffffff; border: 1px solid var(--border-light); border-radius: 16px;
            padding: 0.8rem 0.5rem; text-align: center;
        }
        .adm-stat-title { font-size: 0.75rem; font-weight: 800; color: var(--text-muted); margin-bottom: 0.25rem; }
        .adm-stat-value { font-size: 1.25rem; font-weight: 900; color: var(--text-dark); }
        .adm-stat-val-green { color: var(--neon-green-dark); }

        .admin-action-cards-grid { display: grid; grid-template-columns: 1fr; gap: 0.85rem; margin-bottom: 1.2rem; }
        @media (min-width: 750px) { .admin-action-cards-grid { grid-template-columns: repeat(3, 1fr); } }

        .adm-action-card {
            background: #ffffff; border: 1px solid var(--border-light); border-radius: 18px;
            padding: 1rem; display: flex; flex-direction: column; justify-content: space-between;
        }
        .adm-card-header {
            font-size: 0.9rem; font-weight: 800; border-right: 3px solid #ef4444;
            padding-right: 0.5rem; margin-bottom: 0.8rem; color: #0f172a;
        }
    </style>
</head>
<body>

    <div id="drawer-overlay" class="drawer-overlay" onclick="toggleDrawer()"></div>
    <div id="drawer-panel" class="drawer-panel">
        {% if session.get('user_id') %}
            <div class="drawer-user-card">
                <div>
                    <span class="vip-badge"><i class="fa-solid fa-crown"></i> {{ vip_info.level }}</span>
                    {% if vip_info.discount > 0 %}
                    <span class="vip-badge" style="background:#fef08a; color:#854d0e; border-color:#fde047;">خصم 1% مفعل</span>
                    {% endif %}
                </div>
                <div class="drawer-username">{{ session.get('username') }}</div>
                <div class="drawer-email">{{ session.get('username') }}</div>
                <a href="/logout" class="btn" style="background:#fee2e2; color:#ef4444; width:100%;">
                    <i class="fa-solid fa-right-from-bracket"></i> تسجيل خروج
                </a>
            </div>
        {% else %}
            <div class="drawer-user-card">
                <button class="btn btn-green" style="width: 100%; margin-bottom: 0.4rem;" onclick="toggleDrawer(); openAuthModal()">تسجيل الدخول / حساب جديد</button>
            </div>
        {% endif %}

        <div class="drawer-stat-pill">
            <span style="color: #64748b;">سعر الصرف</span>
            <span class="val-green">1 USD = <span id="drawer-exchange-rate">{{ "%.0f"|format(exchange_rate) }}</span> SYP</span>
        </div>

        <div class="drawer-section-title">رئيسي</div>
        <ul class="drawer-menu-list">
            <li><a class="drawer-menu-link" onclick="toggleDrawer(); switchSection('store')"><i class="fa-solid fa-house" style="color:var(--neon-green-dark)"></i> <span>الرئيسية</span></a></li>
            <li><a class="drawer-menu-link" onclick="toggleDrawer(); switchSection('orders')"><i class="fa-solid fa-bag-shopping" style="color:var(--neon-green-dark)"></i> <span>طلباتي</span></a></li>
            <li><a class="drawer-menu-link" onclick="toggleDrawer(); switchSection('deposit')"><i class="fa-solid fa-wallet" style="color:var(--neon-green-dark)"></i> <span>المحفظة / إيداع</span></a></li>
        </ul>

        <div class="drawer-section-title">معلومات & دعم</div>
        <ul class="drawer-menu-list">
            <li><a class="drawer-menu-link" href="https://t.me/{{ support_telegram }}" target="_blank"><i class="fa-brands fa-telegram" style="color:#0284c7"></i> <span>الدعم (تيليجرام)</span></a></li>
            <li><a class="drawer-menu-link" href="https://wa.me/{{ support_whatsapp }}" target="_blank"><i class="fa-brands fa-whatsapp" style="color:#16a34a"></i> <span>الدعم (واتساب)</span></a></li>
        </ul>
    </div>

    <header class="top-navbar">
        <div class="nav-right-box">
            <button class="menu-burger-btn" onclick="toggleDrawer()" title="القائمة">
                <i class="fa-solid fa-bars"></i>
            </button>
            <a href="#" class="brand-title" onclick="switchSection('store')">
                <i class="fa-solid fa-bolt" style="color: var(--neon-green-dark);"></i>
                <span>SARE3 STOR</span>
            </a>
        </div>
        <div class="top-actions">
            {% if session.get('user_id') %}
                <div class="wallet-pill">
                    <span>$<span id="user-balance">{{ "%.2f"|format(user.balance if user else 0.0) }}</span></span>
                    <button class="add-balance-btn" onclick="switchSection('deposit')" title="إضافة رصيد">+</button>
                </div>
                {% if session.get('is_admin') %}
                    <button class="btn btn-green" style="padding: 0.28rem 0.6rem; font-size: 0.78rem;" onclick="switchSection('admin')">
                        <i class="fa-solid fa-gauge-high"></i> الإدارة
                    </button>
                {% endif %}
            {% else %}
                <button class="btn btn-green" style="padding: 0.3rem 0.8rem; font-size: 0.85rem;" onclick="openAuthModal()">دخول / تسجيل</button>
            {% endif %}
        </div>
    </header>

    <div class="container">

        <main id="sec-store">
            <div class="banners-carousel-wrapper">
                <div class="banners-slides-container" id="carousel-track">
                    <a href="https://t.me/SARE3_STOR" target="_blank" class="banner-slide-item slide-telegram">
                        <div class="slide-content-box">
                            <div class="slide-right-side">
                                <div class="slide-icon-circle">
                                    <i class="fa-brands fa-telegram"></i>
                                </div>
                                <div class="slide-text">
                                    <h3>اضغط هنا للانضمام إلى قناة</h3>
                                    <h2>SARE3 STOR</h2>
                                </div>
                            </div>
                            <div>
                                <span class="slide-btn-badge"><i class="fa-solid fa-paper-plane"></i> انضمام</span>
                            </div>
                        </div>
                    </a>

                    <div class="banner-slide-item slide-welcome">
                        <div class="slide-content-box">
                            <div class="slide-right-side">
                                <div class="slide-icon-circle">
                                    <i class="fa-solid fa-bolt"></i>
                                </div>
                                <div class="slide-text">
                                    <h3>أهلاً وسهلاً بكم في موقع</h3>
                                    <h2><span>SARE3 STOR</span></h2>
                                </div>
                            </div>
                            <div>
                                <span class="slide-btn-badge"><i class="fa-solid fa-bolt"></i> شحن فوري 24/7</span>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="carousel-indicators">
                    <div class="indicator-dot active" onclick="goToSlide(0)"></div>
                    <div class="indicator-dot" onclick="goToSlide(1)"></div>
                </div>
            </div>

            <div class="marquee-seamless-container">
                <div class="marquee-seamless-track">
                    <div class="marquee-seamless-block">
                        <span style="color:#eab308; font-size:1.05rem;">⭐</span> 
                        <span style="color:var(--neon-green-dark); font-weight:900;">سريع ستور:</span> 
                        <span style="font-weight:800; color:#0f172a;">سرعة ← امان ← مصداقية ← اداء مميز و قوي🔥!</span>
                        <span style="color:#64748b; font-weight:700;">• شحن فوري ومباشر 24/7 • أفضل الأسعار والخدمات الرقمية • دعم متواصل</span>
                    </div>
                    <div class="marquee-seamless-block">
                        <span style="color:#eab308; font-size:1.05rem;">⭐</span> 
                        <span style="color:var(--neon-green-dark); font-weight:900;">سريع ستور:</span> 
                        <span style="font-weight:800; color:#0f172a;">سرعة ← امان ← مصداقية ← اداء مميز و قوي🔥!</span>
                        <span style="color:#64748b; font-weight:700;">• شحن فوري ومباشر 24/7 • أفضل الأسعار والخدمات الرقمية • دعم متواصل</span>
                    </div>
                </div>
            </div>

            <div id="cats-view">
                <div class="section-header">
                    <span class="section-title">جميع التصنيفات</span>
                </div>
                <div id="categories-container" class="category-grid"></div>
            </div>

            <div id="subs-view" style="display: none;">
                <div class="section-header">
                    <button class="btn" style="padding: 0.35rem 0.8rem; font-size: 0.8rem;" onclick="backToCategories()">
                        <i class="fa-solid fa-arrow-right"></i> رجوع للأقسام
                    </button>
                    <span id="current-cat-name" class="section-title">الألعاب</span>
                </div>
                <div id="subs-container" class="category-grid"></div>
            </div>

            <div id="prods-view" style="display: none;">
                <div class="section-header">
                    <button class="btn" style="padding: 0.35rem 0.8rem; font-size: 0.8rem;" onclick="backToSubcategories()">
                        <i class="fa-solid fa-arrow-right"></i> رجوع للألعاب
                    </button>
                    <span id="current-sub-name" class="section-title">المنتجات</span>
                </div>
                <div id="products-container" class="products-grid"></div>
            </div>
        </main>

        <section id="sec-orders" style="display: none;">
            <div class="section-header">
                <span class="section-title">سجل طلباتي</span>
            </div>
            <div id="orders-container"></div>
        </section>

        <section id="sec-deposit" style="display: none;">
            <div class="section-header">
                <span class="section-title">شحن الرصيد</span>
            </div>
            <div class="receipt-card">
                <form onsubmit="submitDeposit(event)">
                    <div class="form-group">
                        <label>اختر وسيلة الدفع:</label>
                        <select id="dep-method-sel" class="form-input" onchange="renderPaymentDetails()"></select>
                    </div>

                    <div id="dep-details-box" style="margin-bottom: 1.2rem;">
                        <p id="dep-method-desc" style="font-size: 0.85rem; color: var(--text-muted);"></p>
                        <div style="background: #f1f5f9; border: 1px dashed var(--border-light); border-radius: 14px; padding: 0.8rem; display: flex; justify-content: space-between; align-items: center; margin-top: 0.4rem;">
                            <span id="dep-method-addr" style="font-weight: 800; direction: ltr; font-size: 0.95rem;"></span>
                            <button type="button" class="btn btn-green" style="padding: 0.25rem 0.7rem; font-size: 0.75rem;" onclick="copyAddr()">نسخ</button>
                        </div>
                    </div>

                    <div class="form-group">
                        <label>عملة الدفع المحولة:</label>
                        <select id="dep-currency-sel" class="form-input" onchange="recalcDepositUsd()">
                            <option value="USD">دولار أمريكي ($)</option>
                            <option value="SYP">ليرة سورية (ل.س)</option>
                        </select>
                    </div>

                    <div class="form-group">
                        <label id="dep-amount-label">المبلغ المحول:</label>
                        <input type="number" step="any" id="dep-amount" class="form-input" placeholder="أدخل المبلغ" oninput="recalcDepositUsd()" required>
                    </div>

                    <div style="background: #ecfdf5; border: 1px solid #a7f3d0; padding: 0.9rem; border-radius: 14px; margin-bottom: 1.2rem;">
                        <span style="font-size: 0.9rem; color: var(--neon-green-dark); font-weight: 800;">
                            💵 الرصيد الذي سيُضاف لمحفظتك: $<span id="calculated-usd-display">0.00</span>
                        </span>
                        <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 0.2rem;">
                            سعر الصرف المعتمد: 1$ = <span id="exchange-rate-display">15000</span> ل.س
                        </div>
                    </div>

                    <div class="form-group">
                        <label>رقم العملية / رقم المحول منه (Transaction ID):</label>
                        <input type="text" id="dep-trans" class="form-input" placeholder="أدخل رقم الإشعار أو المعاملة" required>
                    </div>

                    <button type="submit" class="btn btn-green" style="width: 100%;">إرسال طلب الشحن للتأكيد</button>
                </form>
            </div>
        </section>

        {% if session.get('is_admin') %}
        <section id="sec-admin" style="display: none;">
            <div class="admin-dashboard-wrapper">
                <aside class="admin-sidebar">
                    <button class="admin-sidebar-btn active" id="adm-nav-main" onclick="switchAdminSubTab('main')">
                        <i class="fa-solid fa-house"></i> الرئيسية
                    </button>
                    <button class="admin-sidebar-btn" id="adm-nav-products" onclick="switchAdminSubTab('products')">
                        <i class="fa-solid fa-boxes-stacked"></i> المنتجات
                    </button>
                    <button class="admin-sidebar-btn" id="adm-nav-orders" onclick="switchAdminSubTab('orders')">
                        <i class="fa-solid fa-cart-shopping"></i> الطلبات
                    </button>
                    <button class="admin-sidebar-btn" id="adm-nav-deposits" onclick="switchAdminSubTab('deposits')">
                        <i class="fa-solid fa-money-bill-transfer"></i> الإيداعات
                    </button>
                    <button class="admin-sidebar-btn" id="adm-nav-users" onclick="switchAdminSubTab('users')">
                        <i class="fa-solid fa-users"></i> المشتركون
                    </button>
                    <button class="admin-sidebar-btn" id="adm-nav-settings" onclick="switchAdminSubTab('settings')">
                        <i class="fa-solid fa-gear"></i> الإعدادات والدعم
                    </button>
                </aside>

                <div class="admin-main-content">
                    <div id="adm-subtab-main">
                        <div class="admin-stats-grid-row1">
                            <div class="adm-stat-box">
                                <div class="adm-stat-title"><i class="fa-solid fa-users"></i> إجمالي المستخدمين</div>
                                <div class="adm-stat-value" id="stat-total-users">0</div>
                            </div>
                            <div class="adm-stat-box">
                                <div class="adm-stat-title"><i class="fa-solid fa-cart-shopping"></i> الطلبات</div>
                                <div class="adm-stat-value" id="stat-total-orders">0</div>
                            </div>
                            <div class="adm-stat-box">
                                <div class="adm-stat-title"><i class="fa-solid fa-wallet"></i> الإيداعات</div>
                                <div class="adm-stat-value" id="stat-total-deposits">0</div>
                            </div>
                            <div class="adm-stat-box">
                                <div class="adm-stat-title"><i class="fa-solid fa-sack-dollar"></i> إجمالي العمليات</div>
                                <div class="adm-stat-value adm-stat-val-green">$<span id="stat-total-spent">0.00</span></div>
                            </div>
                        </div>

                        <div class="admin-stats-grid-row2">
                            <div class="adm-stat-box">
                                <div class="adm-stat-title"><i class="fa-solid fa-calendar-day"></i> ربح اليوم</div>
                                <div class="adm-stat-value adm-stat-val-green">$<span id="stat-profit-today">0.00</span></div>
                            </div>
                            <div class="adm-stat-box">
                                <div class="adm-stat-title"><i class="fa-solid fa-calendar-week"></i> ربح الشهر</div>
                                <div class="adm-stat-value adm-stat-val-green">$<span id="stat-profit-month">0.00</span></div>
                            </div>
                            <div class="adm-stat-box">
                                <div class="adm-stat-title"><i class="fa-solid fa-chart-line"></i> إجمالي الإيراد</div>
                                <div class="adm-stat-value adm-stat-val-green">$<span id="stat-profit-total">0.00</span></div>
                            </div>
                        </div>

                        <div class="admin-action-cards-grid">
                            <div class="adm-action-card">
                                <div>
                                    <div class="adm-card-header">
                                        <span><i class="fa-solid fa-panorama"></i> إدارة البانرات (Hero)</span>
                                    </div>
                                    <div class="form-group">
                                        <label style="font-size:0.8rem;">عنوان البانر الرئيسي:</label>
                                        <input type="text" id="adm-banner-title-input" class="form-input" style="padding:0.5rem; font-size:0.85rem;">
                                    </div>
                                    <div class="form-group">
                                        <label style="font-size:0.8rem;">الوصف الإعلاني:</label>
                                        <input type="text" id="adm-banner-desc-input" class="form-input" style="padding:0.5rem; font-size:0.85rem;">
                                    </div>
                                </div>
                                <button class="btn btn-green" style="width:100%;" onclick="saveBannerSettings()">
                                    <i class="fa-solid fa-cloud-arrow-up"></i> حفظ وتحديث البانر
                                </button>
                            </div>

                            <div class="adm-action-card">
                                <div>
                                    <div class="adm-card-header">
                                        <span><i class="fa-solid fa-percent"></i> هوامش الربح وسعر الصرف</span>
                                    </div>
                                    <div class="form-group">
                                        <label style="font-size:0.8rem;">نسبة الربح العامة (%):</label>
                                        <input type="number" step="any" id="dash-adm-margin-input" class="form-input" style="padding:0.5rem; font-size:0.85rem;">
                                    </div>
                                    <div class="form-group">
                                        <label style="font-size:0.8rem;">سعر الصرف (1$ = ل.س):</label>
                                        <input type="number" step="any" id="dash-adm-rate-input" class="form-input" style="padding:0.5rem; font-size:0.85rem;">
                                    </div>
                                </div>
                                <button class="btn btn-green" style="width:100%;" onclick="saveStoreSettingsFromDash()">
                                    <i class="fa-solid fa-floppy-disk"></i> حفظ وتطبيق الهوامش
                                </button>
                            </div>

                            <div class="adm-action-card">
                                <div>
                                    <div class="adm-card-header">
                                        <span><i class="fa-solid fa-crown"></i> ترقية رتبة ومستوى العميل (VIP)</span>
                                    </div>
                                    <div class="form-group">
                                        <label style="font-size:0.8rem;">إيميل أو معرف العميل:</label>
                                        <input type="text" id="dash-user-ident" class="form-input" style="padding:0.5rem; font-size:0.85rem;" placeholder="user@gmail.com">
                                    </div>
                                    <div class="form-group">
                                        <label style="font-size:0.8rem;">رتبة الـ VIP المطلوبة:</label>
                                        <select id="dash-user-vip-select" class="form-input" style="padding:0.5rem; font-size:0.85rem;">
                                            <option value="auto">تلقائي (حسب صرف العميل)</option>
                                            <option value="VIP1">VIP 1 (رتبة أساسية)</option>
                                            <option value="VIP2">VIP 2 (فضي)</option>
                                            <option value="VIP3">VIP 3 (ذهبي)</option>
                                            <option value="VIPmax">VIPmax 👑 (خصم 1% دائم)</option>
                                        </select>
                                    </div>
                                    <div class="form-group">
                                        <label style="font-size:0.8rem;">صلاحية الإشراف (Admin):</label>
                                        <select id="dash-user-role-select" class="form-input" style="padding:0.5rem; font-size:0.85rem;">
                                            <option value="0">مستخدم عادي</option>
                                            <option value="1">مشرف (Admin)</option>
                                        </select>
                                    </div>
                                </div>
                                <button class="btn btn-green" style="width:100%;" onclick="saveUserLevelFromDash()">
                                    <i class="fa-solid fa-arrow-up-right-dots"></i> ترقية رتبة العميل فوراً
                                </button>
                            </div>
                        </div>

                        <div class="receipt-card">
                            <h4 style="margin-bottom:0.8rem;"><i class="fa-solid fa-clock"></i> إيداعات بانتظار التأكيد</h4>
                            <div id="adm-deposits-list"></div>
                        </div>
                    </div>

                    <div id="adm-subtab-products" style="display:none;">
                        <div style="display:flex; gap:0.4rem; margin-bottom:1rem; flex-wrap:wrap;">
                            <button class="btn btn-green" onclick="openModal('modal-add-cat')">+ إضافة قسم</button>
                            <button class="btn btn-green" onclick="openModal('modal-add-sub')">+ إضافة لعبة</button>
                            <button class="btn btn-green" onclick="openModal('modal-add-prod')">+ إضافة منتج</button>
                            <button class="btn btn-danger" onclick="openModal('modal-del-cat')">حذف قسم</button>
                            <button class="btn btn-danger" onclick="openModal('modal-del-sub')">حذف لعبة</button>
                            <button class="btn btn-danger" onclick="openModal('modal-del-prod')">حذف منتج</button>
                        </div>
                        <div id="adm-products-manage-list"></div>
                    </div>

                    <div id="adm-subtab-orders" style="display:none;">
                        <div class="receipt-card">
                            <h4 style="margin-bottom:0.8rem;">سجل الطلبات بالنظام</h4>
                            <div id="adm-all-orders-list"></div>
                        </div>
                    </div>

                    <div id="adm-subtab-deposits" style="display:none;">
                        <div style="display:flex; gap:0.5rem; margin-bottom:1rem; flex-wrap:wrap;">
                            <button class="btn btn-green" onclick="openModal('modal-add-pay')">+ إضافة وسيلة دفع</button>
                            <button class="btn btn-danger" onclick="openModal('modal-manage-pays')">🗑️ إدارة وحذف وسائل الدفع</button>
                        </div>
                        <div class="receipt-card">
                            <h4 style="margin-bottom:0.8rem;">جميع عمليات الشحن المعلقة</h4>
                            <div id="adm-deposits-full-list"></div>
                        </div>
                    </div>

                    <div id="adm-subtab-users" style="display:none;">
                        <div style="display:flex; gap:0.5rem; margin-bottom:1rem; flex-wrap:wrap;">
                            <button class="btn btn-green" onclick="openModal('modal-add-user-balance')">+ إضافة رصيد لعميل</button>
                            <button class="btn btn-danger" onclick="openModal('modal-deduct-user-balance')">- خصم رصيد عميل</button>
                        </div>
                        <div class="receipt-card">
                            <h4 style="margin-bottom:0.8rem;">قائمة المشتركين ورتبهم</h4>
                            <div id="adm-all-users-table"></div>
                        </div>
                    </div>

                    <div id="adm-subtab-settings" style="display:none;">
                        <div class="receipt-card">
                            <h4 style="margin-bottom:1rem;">حسابات الدعم الفني</h4>
                            <form onsubmit="handleSaveSupport(event)">
                                <div class="form-group">
                                    <label>يوزر تيليجرام للدعم:</label>
                                    <input type="text" id="supp-tg-input" class="form-input" required>
                                </div>
                                <div class="form-group">
                                    <label>رقم واتساب للدعم:</label>
                                    <input type="text" id="supp-wa-input" class="form-input" required>
                                </div>
                                <button type="submit" class="btn btn-green">حفظ الإعدادات</button>
                            </form>
                        </div>
                    </div>
                </div>
            </div>
        </section>
        {% endif %}

    </div>

    <nav class="bottom-nav">
        <a class="nav-tab active" id="tab-btn-store" onclick="switchSection('store')">
            <i class="fa-solid fa-house"></i>
            <span>الرئيسية</span>
        </a>
        <a class="nav-tab" id="tab-btn-deposit" onclick="switchSection('deposit')">
            <i class="fa-solid fa-credit-card"></i>
            <span>إيداع</span>
        </a>
        <a class="nav-tab" id="tab-btn-cats" onclick="switchSection('store')">
            <i class="fa-solid fa-gamepad"></i>
            <span>الأقسام</span>
        </a>
        {% if session.get('user_id') %}
        <a class="nav-tab" id="tab-btn-orders" onclick="switchSection('orders')">
            <i class="fa-solid fa-clock-rotate-left"></i>
            <span>طلباتي</span>
        </a>
        {% endif %}
    </nav>

    <!-- نافذة تسجيل الدخول -->
    <div id="modal-auth" class="modal-overlay">
        <div class="modal">
            <h3 id="auth-title" style="margin-bottom: 0.6rem;">تسجيل الدخول / إنشاء حساب</h3>
            <p style="font-size:0.8rem; color:var(--text-muted); margin-bottom:1rem;">يتم إرسال رمز أمان لبريدك للتأكد من هويتك</p>

            <div id="auth-step-email">
                <div class="form-group">
                    <label>البريد الإلكتروني:</label>
                    <input type="email" id="auth-email-val" class="form-input" placeholder="name@gmail.com" required>
                </div>
                <button type="button" class="btn btn-green" style="width: 100%;" id="btn-send-code" onclick="triggerSendCode()">
                    إرسال رمز التحقق
                </button>
            </div>

            <div id="auth-step-code" style="display: none; margin-top: 1rem;">
                <div class="form-group" id="code-input-group">
                    <label>رمز التحقق (تم إرساله للبريد):</label>
                    <input type="text" id="auth-code-val" class="form-input" placeholder="أدخل الرمز المكون من 6 أرقام">
                    <p style="font-size: 0.72rem; color: var(--text-muted); margin-top: 0.35rem;">
                        ⚠️ إذا لم تجد الرمز، يرجى تفقد مجلد الرسائل غير المرغوب فيها (Spam).
                    </p>
                </div>
                <div class="form-group">
                    <label>كلمة المرور:</label>
                    <input type="password" id="auth-pass-val" class="form-input" placeholder="كلمة المرور" required>
                </div>
                <button type="button" class="btn btn-green" style="width: 100%;" id="btn-verify-login" onclick="triggerVerifyAndLogin()">
                    تأكيد والدخول
                </button>
                <button type="button" class="btn" style="width: 100%; margin-top: 0.4rem; font-size: 0.75rem;" onclick="resetAuthSteps()">
                    تغيير البريد الإلكتروني
                </button>
            </div>

            <button type="button" class="btn" style="width: 100%; margin-top: 0.5rem;" onclick="closeModal('modal-auth')">إلغاء</button>
        </div>
    </div>

    <!-- نافذة الشراء للمستخدم -->
    <div id="modal-buy" class="modal-overlay">
        <div class="modal">
            <h3 id="buy-prod-name">تفاصيل الشراء</h3>
            <div id="buy-prod-price-unit" style="font-size: 0.95rem; font-weight: 800; color: var(--neon-green-dark); margin: 0.3rem 0;"></div>
            
            <div id="buy-prod-desc-box" style="display:none; background: #f8fafc; border: 1px dashed var(--border-light); padding: 0.7rem; border-radius: 12px; margin-bottom: 0.8rem; font-size: 0.82rem; color: var(--text-muted); line-height: 1.4;">
                <b style="color:var(--text-dark); display:block; margin-bottom:0.2rem;"><i class="fa-solid fa-circle-info"></i> وصف المنتج:</b>
                <span id="buy-prod-desc-text"></span>
            </div>

            {% if vip_info.discount > 0 %}
            <div style="background:#ecfdf5; color:var(--neon-green-dark); border:1px solid #a7f3d0; padding:0.4rem 0.8rem; border-radius:12px; font-weight:800; font-size:0.82rem; margin-bottom:0.8rem;">
                🎉 تم تطبيق خصم VIPmax بنسبة 1% تلقائياً!
            </div>
            {% endif %}

            <form onsubmit="executePurchase(event)">
                <input type="hidden" id="buy-prod-id">
                <input type="hidden" id="buy-base-price">
                <input type="hidden" id="buy-requires-id">
                
                <div class="form-group">
                    <label>الكمية المطلوبة:</label>
                    <input type="number" step="any" min="0.01" id="buy-qty" class="form-input" value="1" oninput="recalcBuyTotal()" required>
                </div>

                <div class="form-group" id="buy-player-id-group">
                    <label id="buy-player-id-label">المعرف / Player ID / رقم الهاتف:</label>
                    <input type="text" id="buy-player-id" class="form-input" placeholder="أدخل الآيدي المطلوب للشحن">
                </div>

                <div id="buy-digital-notice" style="display:none; background:#eff6ff; border:1px solid #bfdbfe; color:#1e40af; padding:0.65rem 0.8rem; border-radius:12px; font-size:0.82rem; font-weight:700; margin-bottom:1rem;">
                    ⚡ هذا منتج رقمي/كود مباشر: سيصلك الكود مباشرة في "طلباتي" فور تأكيد الشراء.
                </div>

                <div style="background: #f1f5f9; padding: 0.9rem; border-radius: 14px; margin-bottom: 1.2rem; font-weight: 800;">
                    الإجمالي النهائي: <span id="buy-total-display" style="color:var(--neon-green-dark); font-size: 1.2rem;">$0.00</span>
                </div>

                <button type="submit" class="btn btn-green" style="width: 100%;" id="buy-btn-submit">تأكيد الخصم والشراء</button>
                <button type="button" class="btn" style="width: 100%; margin-top: 0.5rem;" onclick="closeModal('modal-buy')">إلغاء</button>
            </form>
        </div>
    </div>

    <!-- نافذة تعديل / إضافة وصف المنتج -->
    <div id="modal-edit-desc" class="modal-overlay">
        <div class="modal">
            <h3 id="edit-desc-title">تعديل وصف المنتج</h3>
            <form onsubmit="saveProductDescription(event)">
                <input type="hidden" id="edit-desc-prod-id">
                <div class="form-group">
                    <label>وصف / تفاصيل المنتج:</label>
                    <textarea id="edit-desc-content" class="form-input" rows="4" placeholder="اكتب تعليمات أو وصف المنتج هنا..."></textarea>
                </div>
                <div style="display:flex; gap:0.5rem;">
                    <button type="submit" class="btn btn-green" style="flex:1;">حفظ الوصف</button>
                    <button type="button" class="btn btn-danger" style="flex:1;" onclick="clearProductDescription()">حذف الوصف</button>
                </div>
                <button type="button" class="btn" style="width: 100%; margin-top: 0.5rem;" onclick="closeModal('modal-edit-desc')">إلغاء</button>
            </form>
        </div>
    </div>

    <div id="modal-add-cat" class="modal-overlay">
        <div class="modal">
            <h3>+ إضافة قسم جديد</h3>
            <form onsubmit="addCategoryManual(event)">
                <div class="form-group"><label>اسم القسم:</label><input type="text" id="cat-name-input" class="form-input" required></div>
                <div class="form-group"><label>رابط صورة القسم:</label><input type="url" id="cat-img-input" class="form-input" placeholder="https://..." required></div>
                <button type="submit" class="btn btn-green" style="width: 100%;">حفظ القسم</button>
                <button type="button" class="btn" style="width: 100%; margin-top: 0.5rem;" onclick="closeModal('modal-add-cat')">إلغاء</button>
            </form>
        </div>
    </div>

    <div id="modal-add-sub" class="modal-overlay">
        <div class="modal">
            <h3>+ إضافة لعبة لقسم</h3>
            <form onsubmit="addSubcategoryManual(event)">
                <div class="form-group"><label>اختر القسم:</label><select id="sub-cat-select" class="form-input"></select></div>
                <div class="form-group"><label>اسم اللعبة:</label><input type="text" id="sub-name-input" class="form-input" required></div>
                <div class="form-group"><label>رابط الصورة:</label><input type="url" id="sub-img-input" class="form-input" placeholder="https://..." required></div>
                <button type="submit" class="btn btn-green" style="width: 100%;">حفظ اللعبة</button>
                <button type="button" class="btn" style="width: 100%; margin-top: 0.5rem;" onclick="closeModal('modal-add-sub')">إلغاء</button>
            </form>
        </div>
    </div>

    <div id="modal-add-prod" class="modal-overlay">
        <div class="modal">
            <h3>+ إضافة منتج للعبة</h3>
            <form onsubmit="addProductManual(event)">
                <div class="form-group"><label>اختر اللعبة:</label><select id="prod-sub-select" class="form-input"></select></div>
                <div class="form-group"><label>ID المنتج من الموقع الأصلي (mhd_id):</label><input type="number" id="prod-mhd-input" class="form-input" required></div>
                <div class="form-group"><label>اسم المنتج (اختياري):</label><input type="text" id="prod-name-input" class="form-input"></div>
                <div class="form-group"><label>رابط الصورة:</label><input type="url" id="prod-img-input" class="form-input"></div>
                <div class="form-group">
                    <label>نوع الطلب:</label>
                    <select id="prod-requires-id-select" class="form-input">
                        <option value="auto">كشف تلقائي (حسب اسم ونوع المنتج)</option>
                        <option value="0">كود رقمي مباشر (لا يتطلب آيدي - تسليم كود)</option>
                        <option value="1">شحن مباشر (يتطلب إدخال آيدي اللاعب)</option>
                    </select>
                </div>
                <div class="form-group"><label>الوصف:</label><textarea id="prod-desc-input" class="form-input"></textarea></div>
                <button type="submit" class="btn btn-green" style="width: 100%;">إضافة المنتج</button>
                <button type="button" class="btn" style="width: 100%; margin-top: 0.5rem;" onclick="closeModal('modal-add-prod')">إلغاء</button>
            </form>
        </div>
    </div>

    <div id="modal-del-cat" class="modal-overlay">
        <div class="modal">
            <h3>🗑️ حذف قسم</h3>
            <div class="form-group"><label>اختر القسم:</label><select id="del-cat-select" class="form-input"></select></div>
            <button class="btn btn-danger" style="width: 100%;" onclick="executeDeleteCategory()">حذف القسم بالكامل</button>
            <button class="btn" style="width: 100%; margin-top: 0.5rem;" onclick="closeModal('modal-del-cat')">إلغاء</button>
        </div>
    </div>

    <div id="modal-del-sub" class="modal-overlay">
        <div class="modal">
            <h3>🗑️ حذف لعبة</h3>
            <div class="form-group"><label>اختر اللعبة:</label><select id="del-sub-select" class="form-input"></select></div>
            <button class="btn btn-danger" style="width: 100%;" onclick="executeDeleteSubcategory()">حذف اللعبة ومنتجاتها</button>
            <button class="btn" style="width: 100%; margin-top: 0.5rem;" onclick="closeModal('modal-del-sub')">إلغاء</button>
        </div>
    </div>

    <div id="modal-del-prod" class="modal-overlay">
        <div class="modal">
            <h3>🗑️ حذف منتج</h3>
            <div class="form-group"><label>اختر المنتج:</label><select id="del-prod-select" class="form-input"></select></div>
            <button class="btn btn-danger" style="width: 100%;" onclick="executeDeleteProductDirect()">حذف المنتج</button>
            <button class="btn" style="width: 100%; margin-top: 0.5rem;" onclick="closeModal('modal-del-prod')">إلغاء</button>
        </div>
    </div>

    <div id="modal-add-user-balance" class="modal-overlay">
        <div class="modal">
            <h3>إضافة رصيد لعميل</h3>
            <form onsubmit="handleAddBalance(event)">
                <div class="form-group"><label>معرف / إيميل العميل:</label><input type="text" id="add-bal-username" class="form-input" required></div>
                <div class="form-group"><label>المبلغ ($):</label><input type="number" step="any" min="0.01" id="add-bal-amount" class="form-input" required></div>
                <button type="submit" class="btn btn-green" style="width: 100%;">إضافة الرصيد</button>
                <button type="button" class="btn" style="width: 100%; margin-top: 0.5rem;" onclick="closeModal('modal-add-user-balance')">إلغاء</button>
            </form>
        </div>
    </div>

    <div id="modal-deduct-user-balance" class="modal-overlay">
        <div class="modal">
            <h3>خصم رصيد من عميل</h3>
            <form onsubmit="handleDeductBalance(event)">
                <div class="form-group"><label>معرف / إيميل العميل:</label><input type="text" id="deduct-bal-username" class="form-input" required></div>
                <div class="form-group"><label>المبلغ المراد خصمه ($):</label><input type="number" step="any" min="0.01" id="deduct-bal-amount" class="form-input" required></div>
                <button type="submit" class="btn btn-danger" style="width: 100%;">خصم الرصيد</button>
                <button type="button" class="btn" style="width: 100%; margin-top: 0.5rem;" onclick="closeModal('modal-deduct-user-balance')">إلغاء</button>
            </form>
        </div>
    </div>

    <div id="modal-manual-charge" class="modal-overlay">
        <div class="modal">
            <h3>تحديد مبلغ يدوي للشحن</h3>
            <input type="hidden" id="manual-charge-dep-id">
            <div class="form-group">
                <label>أدخل المبلغ بالدولار ($):</label>
                <input type="number" step="any" min="0.01" id="manual-charge-amount" class="form-input" required>
            </div>
            <button class="btn btn-green" style="width: 100%;" onclick="executeManualCharge()">شحن المبلغ للعميل</button>
            <button class="btn" style="width: 100%; margin-top: 0.5rem;" onclick="closeModal('modal-manual-charge')">إلغاء</button>
        </div>
    </div>

    <div id="modal-add-pay" class="modal-overlay">
        <div class="modal">
            <h3>إضافة وسيلة دفع</h3>
            <form onsubmit="addPaymentManual(event)">
                <div class="form-group"><label>الرمز (code):</label><input type="text" id="pay-code" class="form-input" placeholder="sham_cash" required></div>
                <div class="form-group"><label>الاسم:</label><input type="text" id="pay-name" class="form-input" placeholder="شام كاش" required></div>
                <div class="form-group"><label>التعليمات:</label><textarea id="pay-desc" class="form-input"></textarea></div>
                <div class="form-group"><label>العنوان / الرقم المحول له:</label><input type="text" id="pay-wallet" class="form-input" required></div>
                <button type="submit" class="btn btn-green" style="width: 100%;">حفظ وسيلة الدفع</button>
                <button type="button" class="btn" style="width: 100%; margin-top: 0.5rem;" onclick="closeModal('modal-add-pay')">إلغاء</button>
            </form>
        </div>
    </div>

    <div id="modal-manage-pays" class="modal-overlay">
        <div class="modal">
            <h3 style="margin-bottom:0.8rem;">إدارة وحذف وسائل الدفع</h3>
            <div id="pays-manage-container" style="display:flex; flex-direction:column; gap:0.6rem; max-height:350px; overflow-y:auto; padding:0.2rem;"></div>
            <button class="btn" style="width: 100%; margin-top: 1rem;" onclick="closeModal('modal-manage-pays')">إغلاق</button>
        </div>
    </div>

    <script>
        let currentExchangeRate = parseFloat("{{ exchange_rate }}") || 15000.0;
        let userVipDiscount = parseFloat("{{ vip_info.discount }}") || 0.0;
        let categoriesData = [];
        let paymentMethods = [];
        let currentLoadedProducts = [];
        let adminProductsList = [];

        // منطق تبديل البانرات
        let currentSlide = 0;
        const totalSlides = 2;
        let slideTimer = null;

        function updateSlidePosition() {
            const track = document.getElementById('carousel-track');
            if (track) {
                track.style.transform = `translateX(${currentSlide * 100}%)`;
            }
            document.querySelectorAll('.indicator-dot').forEach((dot, index) => {
                dot.classList.toggle('active', index === currentSlide);
            });
        }

        function nextSlide() {
            currentSlide = (currentSlide + 1) % totalSlides;
            updateSlidePosition();
        }

        function goToSlide(index) {
            currentSlide = index;
            updateSlidePosition();
            restartSlideTimer();
        }

        function restartSlideTimer() {
            if (slideTimer) clearInterval(slideTimer);
            slideTimer = setInterval(nextSlide, 4500);
        }

        function toggleDrawer() {
            document.getElementById('drawer-overlay').classList.toggle('active');
            document.getElementById('drawer-panel').classList.toggle('active');
        }

        function switchSection(sec) {
            ['store', 'orders', 'deposit', 'admin'].forEach(s => {
                const el = document.getElementById(`sec-${s}`);
                if (el) el.style.display = (s === sec) ? 'block' : 'none';
            });
            document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
            const tabBtn = document.getElementById(`tab-btn-${sec}`);
            if (tabBtn) tabBtn.classList.add('active');

            if (sec === 'orders') loadUserOrders();
            if (sec === 'deposit') loadPaymentMethods();
            if (sec === 'admin') loadAdminOverview();
        }

        function switchAdminSubTab(sub) {
            ['main', 'products', 'orders', 'deposits', 'users', 'settings'].forEach(s => {
                const view = document.getElementById(`adm-subtab-${s}`);
                const nav = document.getElementById(`adm-nav-${s}`);
                if (view) view.style.display = (s === sub) ? 'block' : 'none';
                if (nav) nav.classList.toggle('active', s === sub);
            });
        }

        function openModal(id) { 
            if (id === 'modal-manage-pays') {
                if (paymentMethods && paymentMethods.length > 0) {
                    renderManagePaymentsListHtml(paymentMethods);
                } else {
                    document.getElementById('pays-manage-container').innerHTML = '<div style="text-align:center; padding:1.5rem; color:#64748b;"><i class="fa-solid fa-spinner fa-spin"></i> جاري التحميل...</div>';
                }
                renderManagePaymentsList();
            }
            document.getElementById(id).style.display = 'flex'; 
        }
        function closeModal(id) { document.getElementById(id).style.display = 'none'; }

        function openAuthModal() {
            resetAuthSteps();
            openModal('modal-auth');
        }

        function resetAuthSteps() {
            document.getElementById('auth-step-email').style.display = 'block';
            document.getElementById('auth-step-code').style.display = 'none';
            document.getElementById('auth-code-val').value = '';
            document.getElementById('auth-pass-val').value = '';
        }

        async function triggerSendCode() {
            const email = document.getElementById('auth-email-val').value.trim();
            if (!email || !email.includes('@')) {
                return alert('يرجى كتابة بريد إلكتروني صحيح');
            }

            if (email.toLowerCase() === '{{ admin_email|lower }}') {
                document.getElementById('auth-step-email').style.display = 'none';
                document.getElementById('auth-step-code').style.display = 'block';
                document.getElementById('code-input-group').style.display = 'none';
                return;
            } else {
                document.getElementById('code-input-group').style.display = 'block';
            }

            const btn = document.getElementById('btn-send-code');
            btn.disabled = true;
            btn.innerText = 'جاري إرسال الرمز إلى بريدك...';

            try {
                const res = await fetch('/api/auth/send_code', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ email })
                });
                const d = await res.json();
                alert(d.message);

                if (d.status === 'ok') {
                    document.getElementById('auth-step-email').style.display = 'none';
                    document.getElementById('auth-step-code').style.display = 'block';
                }
            } catch (e) {
                alert('حدث خطأ في الاتصال بالخادم');
            } finally {
                btn.disabled = false;
                btn.innerText = 'إرسال رمز التحقق';
            }
        }

        async function triggerVerifyAndLogin() {
            const email = document.getElementById('auth-email-val').value.trim();
            const code = document.getElementById('auth-code-val').value.trim();
            const password = document.getElementById('auth-pass-val').value.trim();

            if (!password) return alert('يرجى إدخال كلمة المرور');

            const btn = document.getElementById('btn-verify-login');
            btn.disabled = true;

            try {
                const res = await fetch('/api/auth/verify_login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ email, code, password })
                });
                const d = await res.json();

                if (d.status === 'ok') {
                    location.reload();
                } else {
                    alert(d.message);
                }
            } catch (e) {
                alert('حدث خطأ أثناء التأكيد');
            } finally {
                btn.disabled = false;
            }
        }

        async function loadCategories() {
            try {
                const res = await fetch('/api/categories');
                categoriesData = await res.json();
                const container = document.getElementById('categories-container');
                container.innerHTML = '';
                if (!categoriesData.length) {
                    container.innerHTML = '<p style="grid-column: 1/-1; text-align:center; color:var(--text-muted); padding:1rem;">لا توجد تصنيفات حالياً.</p>';
                    return;
                }
                categoriesData.forEach(cat => {
                    const card = document.createElement('div');
                    card.className = 'category-card';
                    card.onclick = () => showCategoryGames(cat.id, cat.name);
                    card.innerHTML = `
                        <img src="${cat.image_url || 'https://via.placeholder.com/150'}" class="category-img" alt="${cat.name}">
                        <div class="category-name">${cat.name}</div>
                    `;
                    container.appendChild(card);
                });
            } catch (e) {
                console.error("خطأ تحميل الأقسام:", e);
            }
        }

        async function showCategoryGames(catId, catName) {
            const container = document.getElementById('subs-container');
            container.innerHTML = '<div style="grid-column:1/-1; text-align:center; padding:1.5rem; color:#64748b;"><i class="fa-solid fa-spinner fa-spin"></i> جاري التحميل...</div>';
            document.getElementById('cats-view').style.display = 'none';
            document.getElementById('subs-view').style.display = 'block';
            document.getElementById('prods-view').style.display = 'none';
            document.getElementById('current-cat-name').innerText = catName;

            const res = await fetch(`/api/category/${catId}/subcategories`);
            const subs = await res.json();
            container.innerHTML = '';
            subs.forEach(s => {
                const card = document.createElement('div');
                card.className = 'category-card';
                card.onclick = () => showGameProducts(s.id, s.name);
                card.innerHTML = `
                    <img src="${s.image_url || 'https://via.placeholder.com/150'}" class="category-img" alt="${s.name}">
                    <div class="category-name">${s.name}</div>
                `;
                container.appendChild(card);
            });
        }

        function backToCategories() {
            document.getElementById('cats-view').style.display = 'block';
            document.getElementById('subs-view').style.display = 'none';
            document.getElementById('prods-view').style.display = 'none';
        }

        async function showGameProducts(subId, subName) {
            const container = document.getElementById('products-container');
            container.innerHTML = '<div style="grid-column:1/-1; text-align:center; padding:1.5rem; color:#64748b;"><i class="fa-solid fa-spinner fa-spin"></i> جاري تحميل المنتجات...</div>';
            document.getElementById('subs-view').style.display = 'none';
            document.getElementById('prods-view').style.display = 'block';
            document.getElementById('current-sub-name').innerText = subName;

            const res = await fetch(`/api/subcategory/${subId}/products`);
            currentLoadedProducts = await res.json();
            container.innerHTML = '';
            currentLoadedProducts.forEach((p, idx) => {
                const imgTag = p.image_url ? `<img src="${p.image_url}" class="product-img" alt="${p.name}">` : '';
                container.innerHTML += `
                    <div class="product-card">
                        <div>
                            ${imgTag}
                            <div class="product-title">${p.name}</div>
                        </div>
                        <div>
                            <div class="product-price">$${parseFloat(p.price).toFixed(4)}</div>
                            <button class="btn btn-green" style="width:100%;" onclick="prepareBuyByIndex(${idx})">شراء</button>
                        </div>
                    </div>
                `;
            });
        }

        function backToSubcategories() {
            document.getElementById('subs-view').style.display = 'block';
            document.getElementById('prods-view').style.display = 'none';
        }

        function prepareBuyByIndex(index) {
            {% if not session.get('user_id') %}
            return openAuthModal();
            {% endif %}
            const p = currentLoadedProducts[index];
            document.getElementById('buy-prod-id').value = p.id;
            document.getElementById('buy-base-price').value = p.price;
            document.getElementById('buy-prod-name').innerText = p.name;
            document.getElementById('buy-prod-price-unit').innerText = `سعر الوحدة: $${parseFloat(p.price).toFixed(4)}`;
            
            const reqId = (p.requires_player_id === undefined || p.requires_player_id === null) ? 1 : parseInt(p.requires_player_id);
            document.getElementById('buy-requires-id').value = reqId;

            const playerIdGroup = document.getElementById('buy-player-id-group');
            const digitalNotice = document.getElementById('buy-digital-notice');
            const playerIdInput = document.getElementById('buy-player-id');

            if (reqId === 0) {
                playerIdGroup.style.display = 'none';
                digitalNotice.style.display = 'block';
                playerIdInput.required = false;
                playerIdInput.value = '0';
            } else {
                playerIdGroup.style.display = 'block';
                digitalNotice.style.display = 'none';
                playerIdInput.required = true;
                playerIdInput.value = '';
            }

            const descBox = document.getElementById('buy-prod-desc-box');
            const descText = document.getElementById('buy-prod-desc-text');
            if (p.description && p.description.trim() !== '') {
                descText.innerText = p.description;
                descBox.style.display = 'block';
            } else {
                descBox.style.display = 'none';
            }

            document.getElementById('buy-qty').value = 1;
            recalcBuyTotal();
            openModal('modal-buy');
        }

        function recalcBuyTotal() {
            const unit = parseFloat(document.getElementById('buy-base-price').value || 0);
            const qty = parseFloat(document.getElementById('buy-qty').value || 1);
            let total = unit * (qty > 0 ? qty : 1);
            if (userVipDiscount > 0) {
                total = total * (1.0 - userVipDiscount);
            }
            document.getElementById('buy-total-display').innerText = `$${total.toFixed(4)}`;
        }

        async function executePurchase(e) {
            e.preventDefault();
            const reqId = parseInt(document.getElementById('buy-requires-id').value || 1);
            let pId = document.getElementById('buy-player-id').value.trim();
            if (reqId === 0) {
                pId = '0';
            } else if (!pId) {
                return alert('يرجى إدخال الآيدي المطلوب للشحن');
            }

            const btn = document.getElementById('buy-btn-submit');
            btn.disabled = true;
            try {
                const res = await fetch('/api/order/create', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        product_id: document.getElementById('buy-prod-id').value,
                        qty: parseFloat(document.getElementById('buy-qty').value || 1),
                        player_id: pId
                    })
                });
                const d = await res.json();
                if (d.status === 'ok') {
                    alert('✅ تم إرسال طلب الشحن بنجاح وهو قيد التنفيذ!');
                    closeModal('modal-buy');
                    location.reload();
                } else {
                    alert(`❌ ${d.message}`);
                }
            } catch (err) {
                alert('تعذر استكمال الطلب.');
            } finally {
                btn.disabled = false;
            }
        }

        async function loadUserOrders() {
            const container = document.getElementById('orders-container');
            container.innerHTML = '<div style="text-align:center; padding:2rem 0; color:#64748b;"><i class="fa-solid fa-spinner fa-spin"></i> جاري تحميل الطلبات...</div>';
            const res = await fetch('/api/user/orders');
            const data = await res.json();
            container.innerHTML = '';
            if (!data.length) {
                container.innerHTML = '<p style="text-align:center; color:var(--text-muted); padding:2rem 0;">لا توجد أي طلبات سابقة.</p>';
                return;
            }
            data.forEach((o) => {
                let st = 'قيد الانتظار ⏳';
                if (['accept', 'complete', 'success', 'مكتمل'].includes(o.status)) st = 'مكتمل ✅';
                else if (['reject', 'refuse', 'fail', 'مرفوض'].includes(o.status)) st = 'مرفوض ❌';

                let cleanReplay = o.replay_api || '';
                try {
                    const parsed = JSON.parse(cleanReplay);
                    if (Array.isArray(parsed)) {
                        cleanReplay = parsed.join('\\n');
                    } else if (typeof parsed === 'string') {
                        cleanReplay = parsed;
                    }
                } catch(e) {}

                const replayHtml = o.replay_api ? `
                    <div style="background:#f0fdf4; border:1px solid #86efac; border-radius:12px; padding:0.75rem; margin-top:0.6rem;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.35rem;">
                            <span style="font-size:0.8rem; font-weight:800; color:#15803d;"><i class="fa-solid fa-box-open"></i> بيانات الحساب / الكود:</span>
                            <button type="button" class="btn btn-green copy-order-btn" style="padding:0.2rem 0.55rem; font-size:0.7rem;" data-clipboard-text="${encodeURIComponent(cleanReplay)}">نسخ البيانات</button>
                        </div>
                        <div style="font-weight:900; font-size:0.92rem; color:#0f172a; word-break:break-all; direction:ltr; text-align:right; white-space:pre-line;">${cleanReplay}</div>
                    </div>
                ` : '';

                const showPlayerId = (o.player_id && o.player_id !== '0') ? o.player_id : 'كود رقمي مباشر';

                container.innerHTML += `
                    <div class="receipt-card">
                        <div class="receipt-row"><span class="receipt-label">المنتج:</span><span class="receipt-value">${o.product_name}</span></div>
                        <div class="receipt-row"><span class="receipt-label">الآيدي/البيانات:</span><span class="receipt-value">${showPlayerId}</span></div>
                        <div class="receipt-row">
                            <span class="receipt-label">Order UUID:</span>
                            <span class="receipt-value" style="font-size:0.72rem; direction:ltr; font-family:monospace; user-select:all;">${o.order_uuid}</span>
                        </div>
                        <div class="receipt-row"><span class="receipt-label">الحالة:</span><span class="receipt-value" style="color:var(--neon-green-dark);">${st}</span></div>
                        <div class="receipt-row"><span class="receipt-label">المبلغ:</span><span class="receipt-value" style="color:var(--neon-green-dark); font-weight:900;">$${parseFloat(o.price).toFixed(4)}</span></div>
                        ${replayHtml}
                    </div>
                `;
            });

            document.querySelectorAll('.copy-order-btn').forEach(btn => {
                btn.onclick = function() {
                    const txt = decodeURIComponent(this.getAttribute('data-clipboard-text') || '');
                    safeCopyToClipboard(txt);
                };
            });
        }

        function safeCopyToClipboard(text) {
            if (navigator.clipboard && window.isSecureContext) {
                navigator.clipboard.writeText(text).then(() => {
                    alert('تم نسخ البيانات بنجاح!');
                }).catch(() => {
                    fallbackCopyExec(text);
                });
            } else {
                fallbackCopyExec(text);
            }
        }

        function fallbackCopyExec(text) {
            const ta = document.createElement("textarea");
            ta.value = text;
            ta.style.position = "fixed";
            ta.style.left = "-9999px";
            ta.style.top = "-9999px";
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            try {
                document.execCommand('copy');
                alert('تم نسخ البيانات بنجاح!');
            } catch (err) {
                alert('يرجى تحديد النص ونسخه يدوياً');
            }
            document.body.removeChild(ta);
        }

        async function loadPaymentMethods() {
            if (paymentMethods && paymentMethods.length > 0) {
                renderPaymentSelector();
            }
            const res = await fetch('/api/payment_methods');
            const data = await res.json();
            paymentMethods = data.methods || [];
            currentExchangeRate = data.exchange_rate || 15000;
            document.getElementById('exchange-rate-display').innerText = currentExchangeRate;
            renderPaymentSelector();
        }

        function renderPaymentSelector() {
            const sel = document.getElementById('dep-method-sel');
            const currentSelected = sel.value;
            sel.innerHTML = '';
            paymentMethods.forEach(m => sel.innerHTML += `<option value="${m.code}">${m.name}</option>`);
            if (currentSelected) sel.value = currentSelected;
            renderPaymentDetails();
            recalcDepositUsd();
        }

        function renderPaymentDetails() {
            const code = document.getElementById('dep-method-sel').value;
            const m = paymentMethods.find(x => x.code === code);
            if (m) {
                document.getElementById('dep-method-desc').innerText = m.description || '';
                document.getElementById('dep-method-addr').innerText = m.wallet_address || '';
            }
        }

        function recalcDepositUsd() {
            const curr = document.getElementById('dep-currency-sel').value;
            const amount = parseFloat(document.getElementById('dep-amount').value || 0);
            const rate = currentExchangeRate > 0 ? currentExchangeRate : 15000;
            const finalUsd = curr === 'USD' ? amount : (amount / rate);
            document.getElementById('calculated-usd-display').innerText = finalUsd.toFixed(2);
        }

        function copyAddr() {
            const addr = document.getElementById('dep-method-addr').innerText;
            safeCopyToClipboard(addr);
        }

        async function submitDeposit(e) {
            e.preventDefault();
            const curr = document.getElementById('dep-currency-sel').value;
            const amount = parseFloat(document.getElementById('dep-amount').value || 0);
            const res = await fetch('/api/deposit/submit', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    method: document.getElementById('dep-method-sel').value,
                    currency: curr,
                    raw_amount: amount,
                    trans_id: document.getElementById('dep-trans').value
                })
            });
            const d = await res.json();
            if (d.status === 'ok') {
                alert('✅ تم إرسال طلب الشحن بنجاح!');
                switchSection('store');
            } else {
                alert(d.message);
            }
        }

        function renderManagePaymentsListHtml(list) {
            const container = document.getElementById('pays-manage-container');
            container.innerHTML = '';
            if (!list || !list.length) {
                container.innerHTML = '<p style="text-align:center; color:var(--text-muted); padding:1rem 0;">لا توجد أي وسائل دفع مسجلة.</p>';
                return;
            }
            list.forEach(pm => {
                container.innerHTML += `
                    <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:14px; padding:0.8rem; display:flex; justify-content:space-between; align-items:center;">
                        <div>
                            <div style="font-weight:800; font-size:0.9rem; color:#0f172a;">${pm.name}</div>
                            <div style="font-size:0.75rem; color:#64748b; direction:ltr; text-align:right;">${pm.wallet_address}</div>
                        </div>
                        <button class="btn btn-danger" style="padding:0.3rem 0.7rem; font-size:0.8rem;" onclick="deletePaymentMethod('${pm.code}')">
                            <i class="fa-solid fa-trash-can"></i> حذف
                        </button>
                    </div>
                `;
            });
        }

        async function renderManagePaymentsList() {
            const res = await fetch('/api/payment_methods');
            const data = await res.json();
            paymentMethods = data.methods || [];
            renderManagePaymentsListHtml(paymentMethods);
        }

        async function deletePaymentMethod(code) {
            if (confirm('هل أنت متأكد من حذف وسيلة الدفع هذه؟')) {
                const res = await fetch('/api/admin/delete_payment', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ code })
                });
                const d = await res.json();
                if (d.status === 'ok') {
                    renderManagePaymentsList();
                    loadPaymentMethods();
                } else {
                    alert('تعذر الحذف');
                }
            }
        }

        function openEditDescriptionModal(prodId) {
            const p = adminProductsList.find(x => x.id === prodId);
            if (!p) return;
            document.getElementById('edit-desc-prod-id').value = prodId;
            document.getElementById('edit-desc-title').innerText = `وصف: ${p.name}`;
            document.getElementById('edit-desc-content').value = p.description || '';
            openModal('modal-edit-desc');
        }

        async function saveProductDescription(e) {
            e.preventDefault();
            const prodId = document.getElementById('edit-desc-prod-id').value;
            const description = document.getElementById('edit-desc-content').value.trim();

            const res = await fetch('/api/admin/product/update_description', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ id: prodId, description })
            });
            const d = await res.json();
            if (d.status === 'ok') {
                alert('✅ تم حفظ الوصف بنجاح');
                closeModal('modal-edit-desc');
                loadAdminOverview();
            } else {
                alert(d.message);
            }
        }

        async function clearProductDescription(prodIdParam) {
            const prodId = prodIdParam || document.getElementById('edit-desc-prod-id').value;
            if (confirm('هل تريد حذف وصف هذا المنتج؟')) {
                const res = await fetch('/api/admin/product/delete_description', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ id: prodId })
                });
                const d = await res.json();
                if (d.status === 'ok') {
                    alert('✅ تم حذف الوصف');
                    closeModal('modal-edit-desc');
                    loadAdminOverview();
                } else {
                    alert(d.message);
                }
            }
        }

        async function toggleProductRequiresId(prodId) {
            const res = await fetch('/api/admin/product/toggle_requires_id', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ id: prodId })
            });
            const d = await res.json();
            if (d.status === 'ok') {
                loadAdminOverview();
            } else {
                alert(d.message);
            }
        }

        async function loadAdminOverview() {
            try {
                const res = await fetch('/api/admin/overview');
                const d = await res.json();

                const st = d.stats || {};
                document.getElementById('stat-total-users').innerText = st.users_count || 0;
                document.getElementById('stat-total-orders').innerText = st.orders_count || 0;
                document.getElementById('stat-total-deposits').innerText = st.deposits_count || 0;
                document.getElementById('stat-total-spent').innerText = parseFloat(st.total_spent || 0).toFixed(2);

                document.getElementById('stat-profit-today').innerText = parseFloat(st.profit_today || 0).toFixed(2);
                document.getElementById('stat-profit-month').innerText = parseFloat(st.profit_month || 0).toFixed(2);
                document.getElementById('stat-profit-total').innerText = parseFloat(st.profit_total || 0).toFixed(2);

                document.getElementById('dash-adm-margin-input').value = d.margin || 0;
                document.getElementById('dash-adm-rate-input').value = d.rate || 15000;
                document.getElementById('adm-banner-title-input').value = d.banner_title || '';
                document.getElementById('adm-banner-desc-input').value = d.banner_desc || '';
                document.getElementById('supp-tg-input').value = d.support_telegram || '';
                document.getElementById('supp-wa-input').value = d.support_whatsapp || '';

                const depList = document.getElementById('adm-deposits-list');
                const depFullList = document.getElementById('adm-deposits-full-list');
                depList.innerHTML = '';
                if (depFullList) depFullList.innerHTML = '';

                if (!d.pending_deposits || !d.pending_deposits.length) {
                    depList.innerHTML = '<p style="color:var(--text-muted); font-size:0.85rem;">لا توجد إيداعات معلقة حالياً.</p>';
                    if (depFullList) depFullList.innerHTML = '<p style="color:var(--text-muted); font-size:0.85rem;">لا توجد إيداعات معلقة حالياً.</p>';
                } else {
                    d.pending_deposits.forEach(dep => {
                        const cardHtml = `
                            <div class="receipt-card" style="padding:0.8rem; margin-bottom:0.6rem;">
                                <div class="receipt-row"><b>العميل:</b> <span>${dep.username}</span></div>
                                <div class="receipt-row"><b>المبلغ:</b> <span>${dep.raw_amount} ${dep.currency} ($${parseFloat(dep.amount_usd).toFixed(2)})</span></div>
                                <div class="receipt-row"><b>المعاملة:</b> <span>${dep.trans_id}</span></div>
                                <div style="display:flex; gap:0.4rem; margin-top:0.6rem;">
                                    <button class="btn btn-green" style="flex:1;" onclick="verifyDepositDirect(${dep.id}, ${dep.amount_usd})">✅ قبول</button>
                                    <button class="btn" style="flex:1;" onclick="openManualChargeModal(${dep.id})">✏️ مبلغ يدوي</button>
                                    <button class="btn btn-danger" style="flex:1;" onclick="rejectDeposit(${dep.id})">❌ رفض</button>
                                </div>
                            </div>
                        `;
                        depList.innerHTML += cardHtml;
                        if (depFullList) depFullList.innerHTML += cardHtml;
                    });
                }

                adminProductsList = d.products || [];
                const prodList = document.getElementById('adm-products-manage-list');
                prodList.innerHTML = '';
                adminProductsList.forEach(p => {
                    const descInfo = p.description ? `<div style="font-size:0.75rem; color:#475569; margin-top:0.25rem;"><i class="fa-solid fa-align-right"></i> ${p.description}</div>` : `<div style="font-size:0.75rem; color:#94a3b8; margin-top:0.25rem;">(لا يوجد وصف مضاف)</div>`;
                    const isIdRequired = (p.requires_player_id === undefined || p.requires_player_id === null || p.requires_player_id === 1);
                    const typeBadge = isIdRequired ? 
                        `<span style="background:#ecfdf5; color:#15803d; border:1px solid #86efac; border-radius:8px; padding:0.15rem 0.5rem; font-size:0.72rem; font-weight:800;">🎯 يتطلب آيدي</span>` : 
                        `<span style="background:#eff6ff; color:#1d4ed8; border:1px solid #bfdbfe; border-radius:8px; padding:0.15rem 0.5rem; font-size:0.72rem; font-weight:800;">⚡ كود مباشر بدون آيدي</span>`;

                    prodList.innerHTML += `
                        <div class="receipt-card" style="padding:0.8rem; margin-bottom:0.5rem; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem;">
                            <div style="flex:1; min-width:180px;">
                                <div><b>${p.name}</b> ${typeBadge}</div>
                                <div style="color:var(--neon-green-dark); font-weight:800; font-size:0.85rem; margin-top:0.2rem;">$${parseFloat(p.price).toFixed(4)}</div>
                                ${descInfo}
                            </div>
                            <div style="display:flex; gap:0.35rem; align-items:center; flex-wrap:wrap;">
                                <button class="btn btn-blue" style="padding:0.3rem 0.6rem; font-size:0.75rem;" onclick="toggleProductRequiresId(${p.id})">
                                    <i class="fa-solid fa-arrows-rotate"></i> ${isIdRequired ? 'جعله كود مباشر' : 'جعله يتطلب آيدي'}
                                </button>
                                <button class="btn btn-green" style="padding:0.3rem 0.6rem; font-size:0.75rem;" onclick="openEditDescriptionModal(${p.id})">
                                    <i class="fa-solid fa-pen"></i> ${p.description ? 'تعديل الوصف' : '+ إضافة وصف'}
                                </button>
                                ${p.description ? `<button class="btn btn-warning" style="padding:0.3rem 0.6rem; font-size:0.75rem;" onclick="clearProductDescription(${p.id})"><i class="fa-solid fa-eraser"></i> حذف الوصف</button>` : ''}
                                <button class="btn btn-danger" style="padding:0.3rem 0.6rem; font-size:0.75rem;" onclick="deleteProduct(${p.id})">حذف</button>
                            </div>
                        </div>
                    `;
                });

                const usersTable = document.getElementById('adm-all-users-table');
                if (usersTable) {
                    usersTable.innerHTML = '';
                    (d.all_users || []).forEach(u => {
                        const vipBadge = u.vip_level && u.vip_level !== 'auto' ? `<span class="vip-badge" style="margin:0 4px;">${u.vip_level}</span>` : '<span style="color:#64748b; font-size:0.75rem;">(تلقائي)</span>';
                        usersTable.innerHTML += `
                            <div class="receipt-row">
                                <div>
                                    <b>${u.username}</b> 
                                    ${u.is_admin ? '<span style="color:#ef4444; font-weight:bold;">[أدمن]</span>' : ''}
                                    ${vipBadge}
                                </div>
                                <span>الرصيد: <b style="color:var(--neon-green-dark);">$${parseFloat(u.balance).toFixed(2)}</b></span>
                            </div>
                        `;
                    });
                }

                const catSel = document.getElementById('sub-cat-select');
                const delCatSel = document.getElementById('del-cat-select');
                catSel.innerHTML = ''; delCatSel.innerHTML = '';
                categoriesData.forEach(c => {
                    catSel.innerHTML += `<option value="${c.id}">${c.name}</option>`;
                    delCatSel.innerHTML += `<option value="${c.id}">${c.name}</option>`;
                });

                const subRes = await fetch('/api/all_subcategories');
                const subsList = await subRes.json();
                const prodSubSel = document.getElementById('prod-sub-select');
                const delSubSel = document.getElementById('del-sub-select');
                prodSubSel.innerHTML = ''; delSubSel.innerHTML = '';
                subsList.forEach(s => {
                    prodSubSel.innerHTML += `<option value="${s.id}">${s.cat_name} -> ${s.name}</option>`;
                    delSubSel.innerHTML += `<option value="${s.id}">${s.cat_name} -> ${s.name}</option>`;
                });

                const delProdSel = document.getElementById('del-prod-select');
                delProdSel.innerHTML = '';
                adminProductsList.forEach(p => {
                    delProdSel.innerHTML += `<option value="${p.id}">${p.name} ($${p.price})</option>`;
                });

            } catch (err) {
                console.error("خطأ في تحديث لوحة التحكم:", err);
            }
        }

        async function saveBannerSettings() {
            const title = document.getElementById('adm-banner-title-input').value;
            const desc = document.getElementById('adm-banner-desc-input').value;
            await fetch('/api/admin/save_banner', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ title, desc })
            });
            alert('✅ تم تحديث الإعدادات بنجاح');
        }

        async function saveStoreSettingsFromDash() {
            const margin = document.getElementById('dash-adm-margin-input').value;
            const rate = document.getElementById('dash-adm-rate-input').value;
            const res = await fetch('/api/admin/save_settings', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ margin, rate })
            });
            const d = await res.json();
            if (d.status === 'ok') {
                currentExchangeRate = parseFloat(rate);
                document.getElementById('exchange-rate-display').innerText = currentExchangeRate;
                const drw = document.getElementById('drawer-exchange-rate');
                if (drw) drw.innerText = Math.round(currentExchangeRate);
                alert('✅ تم تحديث الهوامش وسعر الصرف بنجاح');
                loadAdminOverview();
            }
        }

        async function saveUserLevelFromDash() {
            const username = document.getElementById('dash-user-ident').value.trim();
            const is_admin = document.getElementById('dash-user-role-select').value;
            const vip_level = document.getElementById('dash-user-vip-select').value;

            if (!username) return alert('يرجى إدخال اسم المستخدم أو البريد');

            const res = await fetch('/api/admin/set_admin_role', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ username, is_admin, vip_level })
            });
            const d = await res.json();
            alert(d.message);
            if (d.status === 'ok') {
                document.getElementById('dash-user-ident').value = '';
                loadAdminOverview();
            }
        }

        async function handleAddBalance(e) {
            e.preventDefault();
            const res = await fetch('/api/admin/adjust_balance', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    username: document.getElementById('add-bal-username').value,
                    amount: parseFloat(document.getElementById('add-bal-amount').value),
                    type: 'add'
                })
            });
            const d = await res.json();
            alert(d.message);
            if (d.status === 'ok') closeModal('modal-add-user-balance');
        }

        async function handleDeductBalance(e) {
            e.preventDefault();
            const res = await fetch('/api/admin/adjust_balance', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    username: document.getElementById('deduct-bal-username').value,
                    amount: parseFloat(document.getElementById('deduct-bal-amount').value),
                    type: 'deduct'
                })
            });
            const d = await res.json();
            alert(d.message);
            if (d.status === 'ok') closeModal('modal-deduct-user-balance');
        }

        async function handleSaveSupport(e) {
            e.preventDefault();
            await fetch('/api/admin/save_support', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    telegram: document.getElementById('supp-tg-input').value,
                    whatsapp: document.getElementById('supp-wa-input').value
                })
            });
            alert('✅ تم تحديث بيانات الدعم بنجاح');
        }

        async function verifyDepositDirect(id, amount) {
            await fetch('/api/admin/verify_deposit', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ deposit_id: id, action: 'accept', amount: amount })
            });
            loadAdminOverview();
        }

        function openManualChargeModal(id) {
            document.getElementById('manual-charge-dep-id').value = id;
            openModal('modal-manual-charge');
        }

        async function executeManualCharge() {
            const id = document.getElementById('manual-charge-dep-id').value;
            const amt = parseFloat(document.getElementById('manual-charge-amount').value);
            await fetch('/api/admin/verify_deposit', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ deposit_id: id, action: 'accept', amount: amt })
            });
            closeModal('modal-manual-charge');
            loadAdminOverview();
        }

        async function rejectDeposit(id) {
            await fetch('/api/admin/verify_deposit', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ deposit_id: id, action: 'reject' })
            });
            loadAdminOverview();
        }

        async function addCategoryManual(e) {
            e.preventDefault();
            await fetch('/api/admin/add_category', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    name: document.getElementById('cat-name-input').value,
                    image_url: document.getElementById('cat-img-input').value
                })
            });
            closeModal('modal-add-cat');
            loadCategories();
            loadAdminOverview();
        }

        async function executeDeleteCategory() {
            const catId = document.getElementById('del-cat-select').value;
            if (confirm('تأكيد حذف القسم بالكامل؟')) {
                await fetch('/api/admin/delete_category', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ id: catId })
                });
                closeModal('modal-del-cat');
                loadCategories();
                loadAdminOverview();
            }
        }

        async function addSubcategoryManual(e) {
            e.preventDefault();
            await fetch('/api/admin/add_subcategory', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    cat_id: document.getElementById('sub-cat-select').value,
                    name: document.getElementById('sub-name-input').value,
                    image_url: document.getElementById('sub-img-input').value
                })
            });
            closeModal('modal-add-sub');
            loadAdminOverview();
        }

        async function executeDeleteSubcategory() {
            const subId = document.getElementById('del-sub-select').value;
            if (confirm('تأكيد حذف اللعبة؟')) {
                await fetch('/api/admin/delete_subcategory', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ id: subId })
                });
                closeModal('modal-del-sub');
                loadAdminOverview();
            }
        }

        async function addProductManual(e) {
            e.preventDefault();
            const res = await fetch('/api/admin/add_product', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    sub_id: document.getElementById('prod-sub-select').value,
                    name: document.getElementById('prod-name-input').value,
                    image_url: document.getElementById('prod-img-input').value,
                    mhd_id: document.getElementById('prod-mhd-input').value,
                    requires_player_id: document.getElementById('prod-requires-id-select').value,
                    description: document.getElementById('prod-desc-input').value
                })
            });
            const d = await res.json();
            if (d.status === 'ok') {
                closeModal('modal-add-prod');
                alert('✅ تمت إضافة المنتج');
                loadAdminOverview();
            } else {
                alert(d.message);
            }
        }

        async function executeDeleteProductDirect() {
            const pid = document.getElementById('del-prod-select').value;
            await fetch('/api/admin/delete_product', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ id: pid })
            });
            closeModal('modal-del-prod');
            loadAdminOverview();
        }

        async function deleteProduct(id) {
            if (confirm('تأكيد حذف المنتج؟')) {
                await fetch('/api/admin/delete_product', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ id })
                });
                loadAdminOverview();
            }
        }

        async function addPaymentManual(e) {
            e.preventDefault();
            await fetch('/api/admin/add_payment', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    code: document.getElementById('pay-code').value,
                    name: document.getElementById('pay-name').value,
                    description: document.getElementById('pay-desc').value,
                    wallet_address: document.getElementById('pay-wallet').value
                })
            });
            closeModal('modal-add-pay');
            loadPaymentMethods();
            loadAdminOverview();
            alert('✅ تمت إضافة وسيلة الدفع بنجاح');
        }

        window.addEventListener('DOMContentLoaded', () => {
            loadCategories();
            restartSlideTimer();
        });
    </script>
</body>
</html>
"""


# ================= مسارات الـ Backend و API =================
@app.route("/")
def index():
    user = None
    vip_info = {"level": "VIP1", "tag": "v1", "discount": 0.0, "spent": 0.0}
    conn = get_db()
    c = get_cursor(conn)
    if "user_id" in session:
        c.execute("SELECT * FROM users WHERE id=%s", (session["user_id"],))
        user = c.fetchone()
        vip_info = get_user_vip_info(session["user_id"], conn=conn)

    c.execute("SELECT key, value FROM settings")
    settings = {r["key"]: r["value"] for r in c.fetchall()}

    return render_template_string(
        HTML_TEMPLATE,
        user=user,
        vip_info=vip_info,
        admin_email=ADMIN_EMAIL,
        exchange_rate=float(settings.get("exchange_rate", 15000)),
        support_telegram=settings.get("support_telegram", "SARE3_STOR_Support"),
        support_whatsapp=settings.get("support_whatsapp", "0997062693"),
        banner_title=settings.get("banner_title", "يا أهلاً وسهلاً"),
        banner_desc=settings.get("banner_desc", "نورت موقعنا يا صديقي | شحن فوري ومباشر 24/7")
    )


@app.route("/api/auth/send_code", methods=["POST"])
def api_auth_send_code():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()

    if not email or "@" not in email or "." not in email:
        return jsonify({"status": "error", "message": "يرجى كتابة بريد إلكتروني صحيح"}), 400

    otp = str(random.randint(100000, 999999))
    sent = send_otp_email(email, otp)
    if not sent:
        return jsonify({"status": "error", "message": "تعذر إرسال الرمز، تأكد من صحة البريد"}), 500

    conn = get_db()
    c = get_cursor(conn)
    c.execute("""INSERT INTO email_verifications(email, code) VALUES(%s, %s)
                 ON CONFLICT (email) DO UPDATE SET code = EXCLUDED.code, created_at = NOW()""", (email, otp))
    conn.commit()

    return jsonify({"status": "ok", "message": "تم إرسال رمز التحقق إلى بريدك بنجاح"})


@app.route("/api/auth/verify_login", methods=["POST"])
def api_auth_verify_login():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    code = data.get("code", "").strip()
    password = data.get("password", "").strip()

    if not email or not password:
        return jsonify({"status": "error", "message": "جميع الحقول مطلوبة"}), 400

    conn = get_db()
    c = get_cursor(conn)

    is_master_admin = (email == ADMIN_EMAIL.lower() and password == ADMIN_PASS)

    if not is_master_admin:
        c.execute("SELECT code FROM email_verifications WHERE email=%s", (email,))
        row = c.fetchone()
        if not row or row["code"] != code:
            return jsonify({"status": "error", "message": "رمز التحقق غير صحيح أو منتهي الصلاحية"}), 400

        c.execute("DELETE FROM email_verifications WHERE email=%s", (email,))

    c.execute("SELECT * FROM users WHERE username=%s", (email,))
    user = c.fetchone()

    if not user:
        is_admin = 1 if is_master_admin else 0
        vip_lvl = "VIPmax" if is_master_admin else "auto"
        bal = 100000.0 if is_master_admin else 0.0
        pwd_hash = generate_password_hash(password)

        c.execute("""INSERT INTO users(username, password, balance, is_admin, vip_level) 
                     VALUES(%s, %s, %s, %s, %s) RETURNING id""", (email, pwd_hash, bal, is_admin, vip_lvl))
        user_id = c.fetchone()["id"]
        conn.commit()
    else:
        if user["is_banned"]:
            return jsonify({"status": "error", "message": "تم حظر هذا الحساب، يرجى التواصل مع الإدارة"}), 403

        stored_hash = user["password"]
        valid_password = False
        try:
            valid_password = check_password_hash(stored_hash, password)
        except Exception:
            if stored_hash == password:
                valid_password = True
                new_hash = generate_password_hash(password)
                c.execute("UPDATE users SET password=%s WHERE id=%s", (new_hash, user["id"]))
                conn.commit()

        if not is_master_admin and not valid_password:
            return jsonify({"status": "error", "message": "كلمة المرور غير صحيحة"}), 400

        if is_master_admin:
            c.execute("UPDATE users SET is_admin=1, vip_level='VIPmax' WHERE id=%s", (user["id"],))
            conn.commit()

        user_id = user["id"]
        is_admin = 1 if is_master_admin else bool(user["is_admin"])

    conn.commit()

    session["user_id"] = user_id
    session["username"] = email
    session["is_admin"] = is_admin

    return jsonify({"status": "ok", "message": "تم تسجيل الدخول بنجاح"})


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/api/categories")
def api_categories():
    conn = get_db()
    c = get_cursor(conn)
    c.execute("SELECT * FROM categories ORDER BY id ASC")
    rows = [dict(r) for r in c.fetchall()]
    return jsonify(rows)


@app.route("/api/category/<int:cat_id>/subcategories")
def api_subcategories(cat_id):
    conn = get_db()
    c = get_cursor(conn)
    c.execute("SELECT * FROM subcategories WHERE cat_id=%s ORDER BY id ASC", (cat_id,))
    rows = [dict(r) for r in c.fetchall()]
    return jsonify(rows)


@app.route("/api/subcategory/<int:sub_id>/products")
def api_sub_products(sub_id):
    conn = get_db()
    c = get_cursor(conn)
    c.execute("SELECT * FROM products WHERE sub_id=%s ORDER BY id DESC", (sub_id,))
    rows = [dict(r) for r in c.fetchall()]
    return jsonify(rows)


@app.route("/api/all_subcategories")
def api_all_subs():
    conn = get_db()
    c = get_cursor(conn)
    c.execute("""SELECT s.id, s.name, c.name as cat_name 
                 FROM subcategories s 
                 JOIN categories c ON s.cat_id = c.id 
                 ORDER BY s.id ASC""")
    rows = [dict(r) for r in c.fetchall()]
    return jsonify(rows)


@app.route("/api/payment_methods")
def api_payments():
    conn = get_db()
    c = get_cursor(conn)
    c.execute("SELECT * FROM payment_methods WHERE active=1")
    rows = [dict(r) for r in c.fetchall()]
    return jsonify({
        "methods": rows,
        "exchange_rate": get_exchange_rate(conn=conn)
    })


@app.route("/api/deposit/submit", methods=["POST"])
@login_required
def deposit_submit():
    data = request.get_json() or {}
    method = data.get("method")
    currency = data.get("currency", "USD")
    trans_id = str(data.get("trans_id", "")).strip()

    if not trans_id:
        return jsonify({"status": "error", "message": "رقم المعاملة مطلوب"}), 400

    try:
        raw_amount = float(data.get("raw_amount", 0))
        if raw_amount <= 0: raise ValueError
    except Exception:
        return jsonify({"status": "error", "message": "المبلغ غير صالح"}), 400

    conn = get_db()
    rate = get_exchange_rate(conn=conn)
    amount_usd = raw_amount if currency == "USD" else (raw_amount / rate)

    c = get_cursor(conn)
    c.execute("""INSERT INTO deposits(user_id, method, trans_id, amount_usd, raw_amount, currency) 
                 VALUES(%s, %s, %s, %s, %s, %s)""",
              (session["user_id"], method, trans_id, amount_usd, raw_amount, currency))
    conn.commit()
    return jsonify({"status": "ok"})


@app.route("/api/order/create", methods=["POST"])
@login_required
def create_order():
    data = request.get_json() or {}
    product_id = data.get("product_id")
    
    try:
        qty = float(data.get("qty", 1) or 1)
        if qty <= 0: raise ValueError
    except Exception:
        return jsonify({"status": "error", "message": "الكمية غير صالحة"}), 400

    conn = get_db()
    c = get_cursor(conn)
    
    c.execute("SELECT is_banned, balance FROM users WHERE id=%s", (session["user_id"],))
    u_chk = c.fetchone()
    if u_chk and u_chk["is_banned"]:
        return jsonify({"status": "error", "message": "حسابك محظور من الشراء"}), 403

    c.execute("SELECT * FROM products WHERE id=%s", (product_id,))
    prod = c.fetchone()
    if not prod:
        return jsonify({"status": "error", "message": "المنتج غير موجود"}), 404

    req_id = prod["requires_player_id"]
    req_id = 1 if req_id is None else int(req_id)

    raw_player_id = str(data.get("player_id", "")).strip()
    if req_id == 0:
        player_id = "0"
    else:
        if not raw_player_id:
            return jsonify({"status": "error", "message": "معرف اللاعب أو الرقم مطلوب لهذا المنتج"}), 400
        player_id = raw_player_id

    unit_price = float(prod["price"])
    vip = get_user_vip_info(session["user_id"], conn=conn)
    discount = vip["discount"]
    total_price = unit_price * qty * (1.0 - discount)

    c.execute("UPDATE users SET balance = balance - %s WHERE id = %s AND balance >= %s", 
              (total_price, session["user_id"], total_price))
    if c.rowcount == 0:
        return jsonify({"status": "error", "message": f"رصيدك غير كافٍ. المطلوب: ${total_price:.4f}"}), 400

    conn.commit()

    order_uuid = str(uuid.uuid4())
    mhd_id = prod["mhd_id"]

    if mhd_id:
        params = {"qty": qty, "playerId": player_id, "order_uuid": order_uuid}
        url = f"{API_BASE_URL}/client/api/newOrder/{mhd_id}/params?{urllib.parse.urlencode(params)}"
        headers = {"api-token": MHD_API_TOKEN, "Accept": "application/json"}
        try:
            r = http_session.get(url, headers=headers, timeout=25)
            res = r.json()
            res_data = res.get("data") if isinstance(res.get("data"), dict) else {}
            st = str(res_data.get("status") or res.get("status", "wait")).lower()
            rep = replay_extract(res_data or res)

            if r.status_code == 200 and st in {"ok", "wait", "success", "accept"}:
                c.execute("""INSERT INTO orders(order_uuid, user_id, product_name, price, status, replay_api, qty, player_id)
                             VALUES(%s, %s, %s, %s, %s, %s, %s, %s)""",
                          (order_uuid, session["user_id"], prod["name"], total_price, st, rep, qty, player_id))
            else:
                c.execute("UPDATE users SET balance = balance + %s WHERE id=%s", (total_price, session["user_id"]))
                conn.commit()
                return jsonify({"status": "error", "message": res.get("message") or "رفض المزود الطلب"}), 400
        except Exception:
            c.execute("UPDATE users SET balance = balance + %s WHERE id=%s", (total_price, session["user_id"]))
            conn.commit()
            return jsonify({"status": "error", "message": "تعذر الاتصال بالمزود، تم استرجاع الرصيد"}), 500
    else:
        c.execute("""INSERT INTO orders(order_uuid, user_id, product_name, price, status, qty, player_id)
                     VALUES(%s, %s, %s, %s, 'wait', %s, %s)""",
                  (order_uuid, session["user_id"], prod["name"], total_price, qty, player_id))

    conn.commit()
    return jsonify({"status": "ok"})


@app.route("/api/user/orders")
@login_required
def api_user_orders():
    conn = get_db()
    c = get_cursor(conn)
    c.execute("""SELECT id, order_uuid, product_name, price, status, replay_api, qty, player_id, created_at 
                 FROM orders WHERE user_id=%s ORDER BY id DESC""", (session["user_id"],))
    rows = [dict(r) for r in c.fetchall()]
    return jsonify(rows)


# ================= مسارات الإدارة =================
@app.route("/api/admin/overview")
@admin_required
def api_admin_overview():
    conn = get_db()
    c = get_cursor(conn)

    c.execute("""
        SELECT 
            (SELECT COUNT(*) FROM users) AS users_count,
            (SELECT COUNT(*) FROM orders) AS orders_count,
            (SELECT COUNT(*) FROM deposits) AS deposits_count,
            (SELECT COALESCE(SUM(price), 0.0) FROM orders WHERE status IN ('accept', 'مكتمل')) AS total_spent,
            (SELECT COALESCE(SUM(price), 0.0) FROM orders WHERE status IN ('accept', 'مكتمل') AND created_at::date = CURRENT_DATE) AS profit_today,
            (SELECT COALESCE(SUM(price), 0.0) FROM orders WHERE status IN ('accept', 'مكتمل') AND TO_CHAR(created_at, 'YYYY-MM') = TO_CHAR(NOW(), 'YYYY-MM')) AS profit_month
    """)
    stats_row = c.fetchone()
    stats = dict(stats_row) if stats_row else {
        "users_count": 0, "orders_count": 0, "deposits_count": 0,
        "total_spent": 0.0, "profit_today": 0.0, "profit_month": 0.0
    }
    stats["profit_total"] = stats.get("total_spent", 0.0)

    c.execute("""SELECT d.*, u.username FROM deposits d 
                 JOIN users u ON d.user_id = u.id 
                 WHERE d.status='pending' ORDER BY d.id DESC""")
    pending = [dict(r) for r in c.fetchall()]

    c.execute("SELECT * FROM products ORDER BY id DESC")
    prods = [dict(r) for r in c.fetchall()]

    c.execute("SELECT id, username, balance, is_admin, vip_level FROM users ORDER BY id DESC")
    all_users = [dict(r) for r in c.fetchall()]

    c.execute("SELECT * FROM payment_methods")
    all_pays = [dict(r) for r in c.fetchall()]

    c.execute("SELECT key, value FROM settings")
    settings = {r["key"]: r["value"] for r in c.fetchall()}

    return jsonify({
        "stats": stats,
        "pending_deposits": pending,
        "products": prods,
        "all_users": all_users,
        "payment_methods": all_pays,
        "margin": float(settings.get("store_margin_percent", 0)),
        "rate": float(settings.get("exchange_rate", 15000)),
        "banner_title": settings.get("banner_title", "يا أهلاً وسهلاً"),
        "banner_desc": settings.get("banner_desc", "نورت موقعنا يا صديقي | شحن فوري ومباشر 24/7"),
        "support_telegram": settings.get("support_telegram", "SARE3_STOR_Support"),
        "support_whatsapp": settings.get("support_whatsapp", "0997062693")
    })


@app.route("/api/admin/product/toggle_requires_id", methods=["POST"])
@admin_required
def api_toggle_requires_id():
    data = request.get_json() or {}
    prod_id = data.get("id")
    if not prod_id:
        return jsonify({"status": "error", "message": "معرف المنتج مطلوب"}), 400

    conn = get_db()
    c = get_cursor(conn)
    c.execute("SELECT requires_player_id FROM products WHERE id=%s", (prod_id,))
    row = c.fetchone()
    if not row:
        return jsonify({"status": "error", "message": "المنتج غير موجود"}), 404

    curr_val = 1 if row["requires_player_id"] is None else int(row["requires_player_id"])
    new_val = 0 if curr_val == 1 else 1

    c.execute("UPDATE products SET requires_player_id=%s WHERE id=%s", (new_val, prod_id))
    conn.commit()
    return jsonify({"status": "ok", "requires_player_id": new_val})


@app.route("/api/admin/product/update_description", methods=["POST"])
@admin_required
def api_update_product_description():
    data = request.get_json() or {}
    prod_id = data.get("id")
    desc = data.get("description", "").strip()

    if not prod_id:
        return jsonify({"status": "error", "message": "معرف المنتج مطلوب"}), 400

    conn = get_db()
    c = get_cursor(conn)
    c.execute("UPDATE products SET description=%s WHERE id=%s", (desc, prod_id))
    conn.commit()
    return jsonify({"status": "ok", "message": "تم تحديث وصف المنتج بنجاح"})


@app.route("/api/admin/product/delete_description", methods=["POST"])
@admin_required
def api_delete_product_description():
    data = request.get_json() or {}
    prod_id = data.get("id")

    if not prod_id:
        return jsonify({"status": "error", "message": "معرف المنتج مطلوب"}), 400

    conn = get_db()
    c = get_cursor(conn)
    c.execute("UPDATE products SET description='' WHERE id=%s", (prod_id,))
    conn.commit()
    return jsonify({"status": "ok", "message": "تم حذف الوصف بنجاح"})


@app.route("/api/admin/save_banner", methods=["POST"])
@admin_required
def api_save_banner():
    data = request.get_json() or {}
    title = data.get("title", "").strip()
    desc = data.get("desc", "").strip()
    conn = get_db()
    c = get_cursor(conn)
    c.execute("""INSERT INTO settings(key, value) VALUES('banner_title', %s)
                 ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", (title,))
    c.execute("""INSERT INTO settings(key, value) VALUES('banner_desc', %s)
                 ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", (desc,))
    conn.commit()
    return jsonify({"status": "ok"})


@app.route("/api/admin/set_admin_role", methods=["POST"])
@admin_required
def api_set_admin_role():
    data = request.get_json() or {}
    username = str(data.get("username", "")).strip().lower()
    is_admin = int(data.get("is_admin", 0))
    vip_level = str(data.get("vip_level", "auto")).strip()

    conn = get_db()
    c = get_cursor(conn)
    c.execute("SELECT id FROM users WHERE username=%s", (username,))
    u = c.fetchone()
    if not u:
        return jsonify({"status": "error", "message": "المستخدم غير موجود بالنظام"}), 404

    c.execute("UPDATE users SET is_admin=%s, vip_level=%s WHERE username=%s", (is_admin, vip_level, username))
    conn.commit()
    return jsonify({"status": "ok", "message": f"تمت ترقية الحساب ({username}) بنجاح"})


@app.route("/api/admin/adjust_balance", methods=["POST"])
@admin_required
def api_adjust_balance():
    data = request.get_json() or {}
    username = str(data.get("username", "")).strip().lower()
    
    try:
        amount = float(data.get("amount", 0))
        if amount <= 0: raise ValueError
    except Exception:
        return jsonify({"status": "error", "message": "المبلغ يجب أن يكون أكبر من 0"}), 400
        
    action_type = data.get("type", "add")

    conn = get_db()
    c = get_cursor(conn)
    c.execute("SELECT id, balance FROM users WHERE username=%s", (username,))
    u = c.fetchone()
    if not u:
        return jsonify({"status": "error", "message": "المستخدم غير موجود"}), 404

    if action_type == "add":
        c.execute("UPDATE users SET balance = balance + %s WHERE username=%s", (amount, username))
        msg = f"تمت إضافة ${amount} لرصيد العميل"
    else:
        c.execute("UPDATE users SET balance = GREATEST(0.0, balance - %s) WHERE username=%s", (amount, username))
        msg = f"تم خصم ${amount} من رصيد العميل"

    conn.commit()
    return jsonify({"status": "ok", "message": msg})


@app.route("/api/admin/save_support", methods=["POST"])
@admin_required
def api_save_support():
    data = request.get_json() or {}
    tg = str(data.get("telegram", "")).replace("@", "").strip()
    wa = str(data.get("whatsapp", "")).replace("+", "").strip()
    conn = get_db()
    c = get_cursor(conn)
    c.execute("""INSERT INTO settings(key, value) VALUES('support_telegram', %s)
                 ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", (tg,))
    c.execute("""INSERT INTO settings(key, value) VALUES('support_whatsapp', %s)
                 ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", (wa,))
    conn.commit()
    return jsonify({"status": "ok"})


@app.route("/api/admin/save_settings", methods=["POST"])
@admin_required
def api_save_settings():
    data = request.get_json() or {}
    margin = float(data.get("margin", 0))
    rate = float(data.get("rate", 15000))
    conn = get_db()
    c = get_cursor(conn)
    c.execute("""INSERT INTO settings(key, value) VALUES('store_margin_percent', %s)
                 ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", (str(margin),))
    c.execute("""INSERT INTO settings(key, value) VALUES('exchange_rate', %s)
                 ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", (str(rate),))

    c.execute("SELECT id, api_data FROM products")
    for p in c.fetchall():
        if p["api_data"]:
            try:
                base_p = float(json.loads(p["api_data"]).get("price", 0) or 0)
                if base_p > 0:
                    c.execute("UPDATE products SET price=%s WHERE id=%s", (base_p * (1 + margin / 100.0), p["id"]))
            except Exception:
                pass

    conn.commit()
    return jsonify({"status": "ok"})


@app.route("/api/admin/verify_deposit", methods=["POST"])
@admin_required
def api_verify_deposit():
    data = request.get_json() or {}
    dep_id = data.get("deposit_id")
    action = data.get("action")
    amount = float(data.get("amount", 0))
    conn = get_db()
    c = get_cursor(conn)
    c.execute("SELECT * FROM deposits WHERE id=%s", (dep_id,))
    dep = c.fetchone()
    if dep and dep["status"] == "pending":
        if action == "accept":
            final_amt = amount if amount > 0 else dep["amount_usd"]
            c.execute("UPDATE users SET balance = balance + %s WHERE id=%s", (final_amt, dep["user_id"]))
            c.execute("UPDATE deposits SET status='accepted', amount_usd=%s WHERE id=%s", (final_amt, dep_id))
        else:
            c.execute("UPDATE deposits SET status='rejected' WHERE id=%s", (dep_id,))
        conn.commit()
    return jsonify({"status": "ok"})


@app.route("/api/admin/add_category", methods=["POST"])
@admin_required
def api_add_category():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    img = data.get("image_url", "").strip()
    if not name:
        return jsonify({"status": "error", "message": "اسم القسم مطلوب"}), 400
    conn = get_db()
    c = get_cursor(conn)
    c.execute("""INSERT INTO categories(name, image_url) VALUES(%s, %s)
                 ON CONFLICT (name) DO NOTHING""", (name, img))
    conn.commit()
    return jsonify({"status": "ok"})


@app.route("/api/admin/delete_category", methods=["POST"])
@admin_required
def api_delete_category():
    cat_id = (request.get_json() or {}).get("id")
    conn = get_db()
    c = get_cursor(conn)
    c.execute("SELECT id FROM subcategories WHERE cat_id=%s", (cat_id,))
    for r in c.fetchall():
        c.execute("DELETE FROM products WHERE sub_id=%s", (r["id"],))
    c.execute("DELETE FROM subcategories WHERE cat_id=%s", (cat_id,))
    c.execute("DELETE FROM categories WHERE id=%s", (cat_id,))
    conn.commit()
    return jsonify({"status": "ok"})


@app.route("/api/admin/add_subcategory", methods=["POST"])
@admin_required
def api_add_subcategory():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    cat_id = data.get("cat_id")
    if not name or not cat_id:
        return jsonify({"status": "error", "message": "البيانات غير مكتملة"}), 400
    conn = get_db()
    c = get_cursor(conn)
    c.execute("""INSERT INTO subcategories(name, cat_id, image_url) VALUES(%s, %s, %s)
                 ON CONFLICT (name, cat_id) DO NOTHING""",
              (name, cat_id, data.get("image_url", "").strip()))
    conn.commit()
    return jsonify({"status": "ok"})


@app.route("/api/admin/delete_subcategory", methods=["POST"])
@admin_required
def api_delete_subcategory():
    sub_id = (request.get_json() or {}).get("id")
    conn = get_db()
    c = get_cursor(conn)
    c.execute("DELETE FROM products WHERE sub_id=%s", (sub_id,))
    c.execute("DELETE FROM subcategories WHERE id=%s", (sub_id,))
    conn.commit()
    return jsonify({"status": "ok"})


@app.route("/api/admin/add_product", methods=["POST"])
@admin_required
def api_add_product():
    data = request.get_json() or {}
    try:
        mhd_id = int(data.get("mhd_id"))
    except Exception:
        return jsonify({"status": "error", "message": "رقم mhd_id غير صحيح"}), 400

    api_p = fetch_api_product(mhd_id)
    if not api_p:
        return jsonify({"status": "error", "message": "رقم ID غير موجود بالموقع الأصلي"}), 404

    conn = get_db()
    base_price = float(api_p.get("price", 0) or 0)
    final_price = apply_margin(base_price, conn=conn)
    name = data.get("name", "").strip() or api_p.get("name", "منتج")
    cat_name = api_p.get("category_name", "")

    req_setting = data.get("requires_player_id", "auto")
    if req_setting == "0":
        requires_id = 0
    elif req_setting == "1":
        requires_id = 1
    else:
        requires_id = check_if_requires_id(name, cat_name)

    c = get_cursor(conn)
    c.execute("""INSERT INTO products(sub_id, name, price, mhd_id, image_url, description, available, requires_player_id, api_data)
                 VALUES(%s, %s, %s, %s, %s, %s, 1, %s, %s)""",
              (data.get("sub_id"), name, final_price, mhd_id, data.get("image_url", "").strip(), data.get("description", "").strip(), requires_id, json.dumps(api_p)))
    conn.commit()
    return jsonify({"status": "ok"})


@app.route("/api/admin/delete_product", methods=["POST"])
@admin_required
def api_delete_product():
    pid = (request.get_json() or {}).get("id")
    conn = get_db()
    c = get_cursor(conn)
    c.execute("DELETE FROM products WHERE id=%s", (pid,))
    conn.commit()
    return jsonify({"status": "ok"})


@app.route("/api/admin/add_payment", methods=["POST"])
@admin_required
def api_add_payment():
    data = request.get_json() or {}
    code = data.get("code", "").strip().lower()
    name = data.get("name", "").strip()
    desc = data.get("description", "").strip()
    wallet = data.get("wallet_address", "").strip()
    if not code or not name:
        return jsonify({"status": "error", "message": "كود واسم الوسيلة مطلوبان"}), 400
    conn = get_db()
    c = get_cursor(conn)
    c.execute("""INSERT INTO payment_methods(code, name, description, wallet_address, active) 
                 VALUES(%s, %s, %s, %s, 1)
                 ON CONFLICT (code) DO UPDATE SET 
                 name = EXCLUDED.name, description = EXCLUDED.description, wallet_address = EXCLUDED.wallet_address, active = 1""",
              (code, name, desc, wallet))
    conn.commit()
    return jsonify({"status": "ok"})


@app.route("/api/admin/delete_payment", methods=["POST"])
@admin_required
def api_delete_payment():
    code = (request.get_json() or {}).get("code")
    conn = get_db()
    c = get_cursor(conn)
    c.execute("DELETE FROM payment_methods WHERE code=%s", (code,))
    conn.commit()
    return jsonify({"status": "ok"})


# ================= التهيئة وتشغيل المهام الخلفية =================
# تشغيل التهيئة والثريد ليعمل مع خوادم الإنتاج (مثل Gunicorn) ومع التشغيل المباشر
init_db()

_tracker_started = False
if not _tracker_started:
    tracker_thread = threading.Thread(target=background_order_tracker, daemon=True)
    tracker_thread.start()
    _tracker_started = True

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 متجر SARE3 STOR يعمل على المنفذ {port}")
    app.run(host="0.0.0.0", port=port)
