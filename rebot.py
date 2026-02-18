#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import telebot
import json
import os
import logging
import time
import re
import threading
import sys
import traceback
import requests
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, request
from logging.handlers import RotatingFileHandler

# ==================== الإعدادات الأساسية ====================

# إنشاء المجلدات المطلوبة
os.makedirs("users", exist_ok=True)
os.makedirs("logs", exist_ok=True)
os.makedirs("data", exist_ok=True)

# ملف الإعدادات العامة
CONFIG_FILE = "config.json"
BOT_TOKEN = "8255355231:AAFtUegdyNKFvFPEys4Lnqlzl5V2UO6vM88"

# إنشاء البوت
bot = telebot.TeleBot(BOT_TOKEN)

# حالة التعديل للمستخدمين
user_edit_state = {}

# ملف لتخزين حالات الأزرار
BUTTON_STATES_FILE = "data/button_states.json"

# ملف لتخزين إحصائيات الأرقام
NUMBERS_STATS_FILE = "data/numbers_stats.json"

# ملف لتخزين الأرقام المجربة (الفلتر)
TESTED_NUMBERS_FILE = "data/tested_numbers.json"

# ملف لتخزين حالة البوت وإشعارات التوقف
BOT_STATUS_FILE = "data/bot_status.json"

# ==================== إعدادات Flask و Webhook ====================
app = Flask(__name__)

# مسار Webhook
WEBHOOK_URL_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL_BASE = os.environ.get('RENDER_EXTERNAL_URL', '')

if WEBHOOK_URL_BASE:
    WEBHOOK_URL = f"{WEBHOOK_URL_BASE}{WEBHOOK_URL_PATH}"
else:
    WEBHOOK_URL = None
    logging.warning("⚠️ لم يتم تعيين RENDER_EXTERNAL_URL، سيتم استخدام polling بدلاً من webhook")

# ==================== إعدادات التسجيل المتقدم ====================

log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log_file = 'logs/bot.log'

# Rotating file handler (يحتفظ بآخر 5 ملفات، كل ملف 5MB)
handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
handler.setFormatter(log_formatter)

# إضافة للتسجيل في الكونسول أيضاً
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)

# إعداد الـ root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(handler)
root_logger.addHandler(console_handler)

# ==================== دوال تتبع حالة البوت وإرسال الإشعارات ====================

def load_bot_status():
    """تحميل حالة البوت"""
    if os.path.exists(BOT_STATUS_FILE):
        with open(BOT_STATUS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "last_start": None,
        "last_stop": None,
        "stop_count": 0,
        "notified_stop": False
    }

def save_bot_status(status):
    """حفظ حالة البوت"""
    with open(BOT_STATUS_FILE, 'w', encoding='utf-8') as f:
        json.dump(status, f, indent=4, ensure_ascii=False)

def send_stop_notification():
    """إرسال إشعار بتوقف البوت"""
    try:
        status = load_bot_status()
        
        # إذا تم إرسال الإشعار مسبقاً، لا ترسل مرة أخرى
        if status.get("notified_stop"):
            return
        
        # تحديث حالة التوقف
        status["last_stop"] = datetime.now().isoformat()
        status["stop_count"] += 1
        status["notified_stop"] = True
        save_bot_status(status)
        
        # إرسال إشعار لجميع المستخدمين النشطين
        for user_id, user_bot in active_bots.items():
            try:
                user_config = load_user_config(user_id)
                if user_config and user_config.get("status") == "active":
                    bot.send_message(
                        user_config["target_channel"],
                        f"⚠️ **تنبيه: توقف البوت مؤقتاً**\n\n"
                        f"👤 المستخدم: {user_id}\n"
                        f"⏰ وقت التوقف: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"📊 عدد مرات التوقف: {status['stop_count']}\n\n"
                        f"🔄 سيتم إعادة التشغيل تلقائياً خلال لحظات..."
                    )
                    logging.info(f"📤 تم إرسال إشعار توقف للمستخدم {user_id}")
            except Exception as e:
                logging.error(f"❌ خطأ في إرسال إشعار التوقف للمستخدم {user_id}: {e}")
                
    except Exception as e:
        logging.error(f"❌ خطأ في إرسال إشعار التوقف: {e}")

def send_start_notification():
    """إرسال إشعار بعودة البوت للعمل"""
    try:
        status = load_bot_status()
        last_stop = status.get("last_stop")
        
        # تحديث حالة البدء
        status["last_start"] = datetime.now().isoformat()
        status["notified_stop"] = False  # إعادة تعيين علم الإشعار
        save_bot_status(status)
        
        # حساب مدة التوقف
        downtime = "غير معروف"
        if last_stop:
            try:
                stop_time = datetime.fromisoformat(last_stop)
                start_time = datetime.now()
                diff = start_time - stop_time
                seconds = int(diff.total_seconds())
                if seconds < 60:
                    downtime = f"{seconds} ثانية"
                elif seconds < 3600:
                    downtime = f"{seconds // 60} دقيقة"
                else:
                    downtime = f"{seconds // 3600} ساعة"
            except:
                pass
        
        # إرسال إشعار لجميع المستخدمين النشطين
        for user_id, user_bot in active_bots.items():
            try:
                user_config = load_user_config(user_id)
                if user_config and user_config.get("status") == "active":
                    bot.send_message(
                        user_config["target_channel"],
                        f"✅ **تم إعادة تشغيل البوت تلقائياً**\n\n"
                        f"👤 المستخدم: {user_id}\n"
                        f"⏰ وقت التشغيل: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"⏱️ مدة التوقف: {downtime}\n"
                        f"📊 عدد مرات التوقف: {status['stop_count']}\n\n"
                        f"📡 المصدر: {user_config['source_channel']}\n"
                        f"🎯 الهدف: {user_config['target_channel']}\n\n"
                        f"🔬 الفلتر يعمل: {len(get_user_tested_numbers(user_id))} رقم مجرب\n"
                        f"🚀 البوت يعمل الآن بشكل طبيعي"
                    )
                    logging.info(f"📤 تم إرسال إشعار تشغيل للمستخدم {user_id}")
            except Exception as e:
                logging.error(f"❌ خطأ في إرسال إشعار التشغيل للمستخدم {user_id}: {e}")
                
    except Exception as e:
        logging.error(f"❌ خطأ في إرسال إشعار التشغيل: {e}")

# ==================== دوال إحصائيات الأرقام ====================

def load_numbers_stats():
    """تحميل إحصائيات الأرقام"""
    if os.path.exists(NUMBERS_STATS_FILE):
        with open(NUMBERS_STATS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "total_processed": 0,
        "without_session": 0,
        "accessed": 0,
        "tested": 0,
        "last_update": datetime.now().isoformat(),
        "users_stats": {}
    }

def save_numbers_stats(stats):
    """حفظ إحصائيات الأرقام"""
    stats["last_update"] = datetime.now().isoformat()
    with open(NUMBERS_STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=4, ensure_ascii=False)

def update_number_stats(user_id, number_type, number_text=""):
    """تحديث إحصائيات الأرقام"""
    stats = load_numbers_stats()
    
    # إحصائيات عامة
    stats["total_processed"] += 1
    
    if number_type == 'type1':
        stats["without_session"] += 1
    elif number_type == 'type2':
        stats["accessed"] += 1
    
    # إحصائيات لكل مستخدم
    if user_id not in stats["users_stats"]:
        stats["users_stats"][user_id] = {
            "total": 0,
            "without_session": 0,
            "accessed": 0,
            "tested": 0,
            "last_numbers": []
        }
    
    user_stats = stats["users_stats"][user_id]
    user_stats["total"] += 1
    
    if number_type == 'type1':
        user_stats["without_session"] += 1
    elif number_type == 'type2':
        user_stats["accessed"] += 1
    
    # حفظ آخر 10 أرقام
    user_stats["last_numbers"].insert(0, {
        "type": number_type,
        "text": number_text[:100],
        "time": datetime.now().isoformat()
    })
    user_stats["last_numbers"] = user_stats["last_numbers"][:10]
    
    save_numbers_stats(stats)
    return stats

def update_tested_stats(user_id, tester_info):
    """تحديث إحصائيات التجريب"""
    stats = load_numbers_stats()
    stats["tested"] += 1
    
    if user_id in stats["users_stats"]:
        stats["users_stats"][user_id]["tested"] += 1
    
    save_numbers_stats(stats)

def get_total_numbers_count():
    """الحصول على إجمالي عدد الأرقام"""
    stats = load_numbers_stats()
    return {
        "total": stats["total_processed"],
        "without_session": stats["without_session"],
        "accessed": stats["accessed"],
        "tested": stats["tested"]
    }

# ==================== دوال الفلتر المتقدمة (الأرقام المجربة) ====================

def load_tested_numbers():
    """تحميل الأرقام المجربة (الفلتر)"""
    if os.path.exists(TESTED_NUMBERS_FILE):
        with open(TESTED_NUMBERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "numbers": {},  # {number_hash: {"user_id": "", "tested_at": "", "number_text": "", "message_ids": []}}
        "by_user": {},   # {user_id: [number_hashes]}
        "by_text": {}    # {number_text: hash} للبحث السريع
    }

def save_tested_numbers(tested_data):
    """حفظ الأرقام المجربة"""
    with open(TESTED_NUMBERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(tested_data, f, indent=4, ensure_ascii=False)

def extract_number_from_text(text):
    """استخراج الرقم الفعلي من النص"""
    if not text:
        return None
    
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        
        # تخطي سطور الحالة
        if 'الحالة' in line or 'الـحـالـة' in line:
            continue
        
        # ابحث عن أرقام (تجاهل الخطوط التي تحتوي على @ أو http)
        if '@' in line or 'http' in line or 'www.' in line:
            continue
        
        # إذا كان السطر يحتوي على أرقام فقط أو يبدأ برقم
        if line and (line.replace(' ', '').isdigit() or 
                    (line[0].isdigit() and len(line) > 5) or
                    re.search(r'\d{5,}', line)):
            # استخراج أول 50 حرف كحد أقصى
            return line[:100].strip()
    
    # إذا لم نجد رقماً واضحاً، استخدم أول 100 حرف
    return text[:100].strip()

def get_number_hash(text):
    """إنشاء هاش فريد للرقم بناءً على النص"""
    number = extract_number_from_text(text)
    if number:
        return hashlib.md5(number.encode()).hexdigest()
    return hashlib.md5(text[:100].encode()).hexdigest()

def is_number_tested(text, user_id):
    """التحقق إذا كان الرقم مجرب من قبل (بناءً على النص)"""
    tested_data = load_tested_numbers()
    number_hash = get_number_hash(text)
    
    # تحقق إذا كان الهاش موجود
    if number_hash in tested_data["numbers"]:
        # تحقق إذا كان لنفس المستخدم
        if tested_data["numbers"][number_hash]["user_id"] == user_id:
            return True
    return False

def mark_number_as_tested(user_id, source_message_id, number_text, tester_info=None):
    """تسجيل رقم كمجرب (باستخدام هاش النص)"""
    tested_data = load_tested_numbers()
    number_hash = get_number_hash(number_text)
    extracted_number = extract_number_from_text(number_text)
    
    # معلومات الرقم
    number_info = {
        "user_id": user_id,
        "tested_at": datetime.now().isoformat(),
        "number_text": extracted_number or number_text[:200],
        "full_text": number_text[:500],
        "message_ids": [source_message_id],
        "tester": tester_info or {}
    }
    
    # إذا كان الرقم موجود مسبقاً
    if number_hash in tested_data["numbers"]:
        # أضف message_id جديد إذا لم يكن موجوداً
        if source_message_id not in tested_data["numbers"][number_hash]["message_ids"]:
            tested_data["numbers"][number_hash]["message_ids"].append(source_message_id)
        # تحديث وقت التجريب
        tested_data["numbers"][number_hash]["tested_at"] = datetime.now().isoformat()
    else:
        # رقم جديد
        tested_data["numbers"][number_hash] = number_info
        
        # أضف للمستخدم
        if user_id not in tested_data["by_user"]:
            tested_data["by_user"][user_id] = []
        if number_hash not in tested_data["by_user"][user_id]:
            tested_data["by_user"][user_id].append(number_hash)
    
    save_tested_numbers(tested_data)
    
    # تحديث الإحصائيات
    update_tested_stats(user_id, tester_info)
    
    logging.info(f"✅ تم تسجيل رقم كمجرب - المستخدم: {user_id}, الهاش: {number_hash}")
    return number_hash

def get_user_tested_numbers(user_id):
    """الحصول على جميع الأرقام المجربة لمستخدم"""
    tested_data = load_tested_numbers()
    user_hashes = tested_data["by_user"].get(user_id, [])
    
    result = []
    for h in user_hashes:
        if h in tested_data["numbers"]:
            result.append(tested_data["numbers"][h])
    
    return result

def cleanup_old_tested_numbers(days=30):
    """تنظيف الأرقام المجربة القديمة"""
    tested_data = load_tested_numbers()
    current_time = datetime.now()
    to_delete = []
    
    for number_hash, info in tested_data["numbers"].items():
        tested_time = datetime.fromisoformat(info["tested_at"])
        if (current_time - tested_time) > timedelta(days=days):
            to_delete.append((number_hash, info["user_id"]))
    
    for number_hash, user_id in to_delete:
        # حذف من قائمة المستخدم
        if user_id in tested_data["by_user"] and number_hash in tested_data["by_user"][user_id]:
            tested_data["by_user"][user_id].remove(number_hash)
        # حذف الرقم
        del tested_data["numbers"][number_hash]
    
    if to_delete:
        save_tested_numbers(tested_data)
        logging.info(f"🧹 تم تنظيف {len(to_delete)} رقم مجرب قديم")

# ==================== مسار Webhook في Flask ====================

@app.route(WEBHOOK_URL_PATH, methods=['POST'])
def webhook():
    """استقبال التحديثات من Telegram عبر Webhook"""
    if request.headers.get('content-type') == 'application/json':
        try:
            json_string = request.get_data().decode('utf-8')
            update = telebot.types.Update.de_json(json_string)
            bot.process_new_updates([update])
            return '', 200
        except Exception as e:
            logging.error(f"❌ خطأ في معالجة Webhook: {e}")
            return 'Error', 500
    else:
        return 'Unsupported media type', 415

@app.route('/')
@app.route('/health')
def health_check():
    """فحص صحة البوت"""
    stats = get_total_numbers_count()
    status = load_bot_status()
    return json.dumps({
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "webhook_url": WEBHOOK_URL,
        "active_bots": len(active_bots) if 'active_bots' in globals() else 0,
        "statistics": stats,
        "bot_status": {
            "last_start": status.get("last_start"),
            "last_stop": status.get("last_stop"),
            "stop_count": status.get("stop_count", 0)
        }
    }), 200, {'Content-Type': 'application/json'}

@app.route('/healthz')
def healthz():
    """فحص صحة البوت (لـ Kubernetes/Render)"""
    return "OK", 200

@app.route('/stats')
def stats_page():
    """صفحة إحصائيات البوت"""
    stats = load_numbers_stats()
    tested_data = load_tested_numbers()
    bot_status = load_bot_status()
    
    html = f"""
    <html>
    <head>
        <title>إحصائيات البوت</title>
        <style>
            body {{ font-family: Arial; direction: rtl; padding: 20px; background: #f0f2f5; }}
            .container {{ max-width: 800px; margin: auto; }}
            .card {{ background: white; border-radius: 10px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
            h1 {{ color: #0088cc; }}
            .stat {{ display: inline-block; margin: 10px; padding: 15px; background: #f8f9fa; border-radius: 8px; min-width: 150px; }}
            .stat-value {{ font-size: 24px; font-weight: bold; color: #0088cc; }}
            .stat-label {{ font-size: 14px; color: #666; }}
            .good {{ color: #28a745; }}
            .warning {{ color: #ffc107; }}
            .danger {{ color: #dc3545; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📊 إحصائيات البوت</h1>
            
            <div class="card">
                <h2>حالة البوت</h2>
                <p><strong>🟢 الحالة:</strong> نشط</p>
                <p><strong>🕒 آخر تشغيل:</strong> {bot_status.get('last_start', 'غير معروف')[:19]}</p>
                <p><strong>⏹️ آخر توقف:</strong> {bot_status.get('last_stop', 'غير معروف')[:19] if bot_status.get('last_stop') else 'لم يتوقف'}</p>
                <p><strong>📊 عدد مرات التوقف:</strong> {bot_status.get('stop_count', 0)}</p>
            </div>
            
            <div class="card">
                <h2>إجمالي الأرقام</h2>
                <div class="stat">
                    <div class="stat-value">{stats['total_processed']}</div>
                    <div class="stat-label">إجمالي الأرقام</div>
                </div>
                <div class="stat">
                    <div class="stat-value good">{stats['without_session']}</div>
                    <div class="stat-label">✅ بدون جلسة</div>
                </div>
                <div class="stat">
                    <div class="stat-value warning">{stats['accessed']}</div>
                    <div class="stat-label">📱 تم الوصول</div>
                </div>
                <div class="stat">
                    <div class="stat-value danger">{stats['tested']}</div>
                    <div class="stat-label">🔬 مجرب</div>
                </div>
            </div>
            
            <div class="card">
                <h2>معلومات إضافية</h2>
                <p><strong>🕒 آخر تحديث:</strong> {stats['last_update'][:19]}</p>
                <p><strong>👥 عدد المستخدمين النشطين:</strong> {len(active_bots)}</p>
                <p><strong>🚫 الأرقام المجربة (فلتر):</strong> {len(tested_data['numbers'])}</p>
                <p><strong>💾 مساحة التخزين:</strong> {get_folder_size('data')} MB</p>
            </div>
            
            <div class="card">
                <h2>إحصائيات المستخدمين</h2>
                <table style="width:100%; border-collapse: collapse;">
                    <tr style="background: #0088cc; color: white;">
                        <th style="padding: 10px;">المستخدم</th>
                        <th>إجمالي</th>
                        <th>✅ بدون جلسة</th>
                        <th>📱 تم الوصول</th>
                        <th>🔬 مجرب</th>
                    </tr>
                    {''.join([f"<tr><td>{uid}</td><td>{u['total']}</td><td>{u['without_session']}</td><td>{u['accessed']}</td><td>{u['tested']}</td></tr>" for uid, u in stats['users_stats'].items()])}
                </table>
            </div>
        </div>
    </body>
    </html>
    """
    return html

def get_folder_size(folder):
    """حساب حجم المجلد بالميجابايت"""
    total = 0
    for root, dirs, files in os.walk(folder):
        for f in files:
            fp = os.path.join(root, f)
            total += os.path.getsize(fp)
    return round(total / (1024 * 1024), 2)

# ==================== دوال إعداد Webhook ====================

def setup_webhook():
    """إعداد webhook للبوت"""
    if not WEBHOOK_URL:
        logging.error("❌ لا يمكن تعيين Webhook: RENDER_EXTERNAL_URL غير موجود")
        return False
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            logging.info(f"🔄 محاولة تعيين Webhook {attempt + 1}/{max_retries}")
            
            # إزالة webhook القديم
            bot.remove_webhook()
            time.sleep(1)
            
            # تعيين webhook جديد
            bot.set_webhook(
                url=WEBHOOK_URL,
                max_connections=40,
                allowed_updates=["message", "edited_message", "channel_post", "edited_channel_post", "callback_query"]
            )
            
            # التحقق من تعيين webhook
            webhook_info = bot.get_webhook_info()
            if webhook_info.url == WEBHOOK_URL:
                logging.info(f"✅ Webhook تم تعيينه بنجاح: {WEBHOOK_URL}")
                logging.info(f"📊 معلومات Webhook: pending_updates={webhook_info.pending_update_count}")
                return True
            else:
                logging.warning(f"⚠️ Webhook لم يتم تعيينه بشكل صحيح: {webhook_info.url}")
                
        except requests.exceptions.ConnectionError as e:
            logging.error(f"❌ خطأ في الاتصال (محاولة {attempt + 1}): {e}")
            time.sleep(2 ** attempt)
        except Exception as e:
            logging.error(f"❌ خطأ في تعيين webhook (محاولة {attempt + 1}): {e}")
            time.sleep(2 ** attempt)
    
    logging.error("❌ فشل تعيين Webhook بعد كل المحاولات")
    return False

def verify_webhook():
    """التحقق الدوري من webhook"""
    while True:
        try:
            time.sleep(300)  # كل 5 دقائق
            
            webhook_info = bot.get_webhook_info()
            if webhook_info.url != WEBHOOK_URL:
                logging.warning("⚠️ Webhook تغير، جاري إعادة التعيين...")
                setup_webhook()
            elif webhook_info.pending_update_count > 100:
                logging.warning(f"⚠️ عدد كبير من التحديثات المعلقة: {webhook_info.pending_update_count}")
                
        except Exception as e:
            logging.error(f"❌ خطأ في التحقق من webhook: {e}")

# ==================== دوال المساعدة ====================

def load_button_states():
    """تحميل حالات الأزرار"""
    if os.path.exists(BUTTON_STATES_FILE):
        with open(BUTTON_STATES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_button_states(states):
    """حفظ حالات الأزرار"""
    with open(BUTTON_STATES_FILE, 'w', encoding='utf-8') as f:
        json.dump(states, f, indent=4, ensure_ascii=False)

def load_config():
    """تحميل الإعدادات العامة"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"active_users": []}

def save_config(config):
    """حفظ الإعدادات العامة"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

def load_user_config(user_id):
    """تحميل إعدادات مستخدم محدد"""
    user_file = f"users/{user_id}.json"
    if os.path.exists(user_file):
        with open(user_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def save_user_config(user_id, config):
    """حفظ إعدادات مستخدم محدد"""
    user_file = f"users/{user_id}.json"
    with open(user_file, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

def setup_logging(user_id):
    """إعداد التسجيل للمستخدم"""
    log_file = f"logs/user_{user_id}.txt"
    
    logger = logging.getLogger(f"user_{user_id}")
    logger.setLevel(logging.INFO)
    
    # إزالة المعالجات القديمة
    if logger.handlers:
        return logger
    
    # معالج الملف
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    
    # تنسيق السجلات
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    
    return logger

def validate_channel_id(channel_id):
    """التحقق من صحة معرف القناة"""
    channel_id_str = str(channel_id).strip()
    
    # 1. التحقق من التنسيق الأساسي
    # معرف رقمي: -100 + 10 أرقام
    numeric_pattern = r'^-100\d{10,}$'
    # معرف نصي: @ + 5-32 حرف/رقم/_
    username_pattern = r'^@[a-zA-Z0-9_]{5,32}$'
    
    is_valid_format = bool(re.match(numeric_pattern, channel_id_str) or 
                          re.match(username_pattern, channel_id_str))
    
    if not is_valid_format:
        return False, "❌ تنسيق المعرف غير صحيح!\n\n" \
                     "يجب أن يكون:\n" \
                     "• معرف رقمي: -1001234567890 (يبدأ بـ -100 ثم 10+ أرقام)\n" \
                     "• معرف نصي: @channel_name (يبدأ بـ @ ثم 5-32 حرف/رقم/_)"
    
    # 2. محاولة التحقق من وجود القناة
    try:
        chat_info = bot.get_chat(channel_id_str)
        
        # التحقق من نوع المحادثة
        if chat_info.type not in ["channel", "supergroup"]:
            return False, "❌ هذا المعرف ليس لقناة!\n\n" \
                         "يجب أن تكون قناة أو مجموعة عامة."
        
        return True, f"✅ القناة موجودة: {chat_info.title or 'بدون اسم'}"
        
    except telebot.apihelper.ApiTelegramException as e:
        error_message = str(e)
        
        if "chat not found" in error_message.lower():
            return False, "❌ القناة غير موجودة!\n\n" \
                         "تأكد من:\n" \
                         "1. المعرف صحيح\n" \
                         "2. القناة موجودة\n" \
                         "3. البوت عضو في القناة"
        
        elif "Forbidden" in error_message:
            return False, "❌ البوت محظور من القناة!\n\n" \
                         "يجب إلغاء حظر البوت من القناة أولاً."
        
        else:
            return False, f"❌ خطأ في التحقق: {error_message}"
    
    except Exception as e:
        return False, f"❌ خطأ غير متوقع: {str(e)}"

def validate_source_channel(channel_id):
    """تحقق خاص لقناة المصدر"""
    is_valid, message = validate_channel_id(channel_id)
    
    if not is_valid:
        return False, message
    
    # تحقق إضافي لقناة المصدر: البوت يجب أن يكون مشرفاً
    try:
        chat_member = bot.get_chat_member(channel_id, bot.get_me().id)
        
        # التحقق من صلاحيات البوت
        if chat_member.status in ["creator", "administrator"]:
            return True, "✅ البوت لديه صلاحيات كافية في القناة المصدر"
        
        else:
            return False, "❌ البوت ليس مشرفاً في القناة!\n\n" \
                         "أضف البوت إلى القناة كمشرف أولاً."
        
    except telebot.apihelper.ApiTelegramException as e:
        error_message = str(e)
        
        if "bot is not a member" in error_message.lower():
            return False, "❌ البوت ليس عضواً في القناة!\n\n" \
                         "أضف البوت إلى القناة أولاً."
        
        else:
            return False, f"❌ خطأ في التحقق من الصلاحيات: {error_message}"
    
    except Exception as e:
        return False, f"❌ خطأ غير متوقع في التحقق: {str(e)}"

def validate_target_channel(channel_id):
    """تحقق خاص لقناة الهدف"""
    is_valid, message = validate_channel_id(channel_id)
    
    if not is_valid:
        return False, message
    
    # تحقق إضافي لقناة الهدف: البوت يجب أن يستطيع الكتابة
    try:
        # محاولة إرسال رسالة تجريبية
        test_message = bot.send_message(
            channel_id,
            "🔍 جاري التحقق من صلاحيات البوت...\n"
            "هذه رسالة تجريبية وسيتم حذفها تلقائياً.",
            disable_notification=True
        )
        
        # حذف الرسالة التجريبية
        try:
            time.sleep(1)
            bot.delete_message(channel_id, test_message.message_id)
        except:
            pass  # لا بأس إذا فشل الحذف
        
        return True, "✅ البوت يستطيع الكتابة في القناة الهدف"
        
    except telebot.apihelper.ApiTelegramException as e:
        error_message = str(e)
        
        if "not enough rights" in error_message.lower():
            return False, "❌ البوت لا يستطيع الكتابة في القناة!\n\n" \
                         "أعط البوت صلاحية 'إرسال رسائل' في إعدادات المشرفين."
        
        else:
            return False, f"❌ خطأ في التحقق من الكتابة: {error_message}"
    
    except Exception as e:
        return False, f"❌ خطأ غير متوقع: {str(e)}"

def convert_to_chat_id(channel_input):
    """تحويل المعرف إلى ID رقمي"""
    try:
        if isinstance(channel_input, int):
            return channel_input
        
        if isinstance(channel_input, str):
            channel_input = channel_input.strip()
            
            if channel_input.lstrip('-').isdigit():
                return int(channel_input)
            
            elif channel_input.startswith('@'):
                try:
                    chat_info = bot.get_chat(channel_input)
                    return chat_info.id
                except:
                    return channel_input
        
        return channel_input
    except:
        return channel_input

# ==================== كلاس البوت الرئيسي ====================

class UserBot:
    """كلاس يمثل بوت مستخدم واحد"""
    
    def __init__(self, user_id, source_channel, target_channel):
        self.user_id = user_id
        self.source_channel = convert_to_chat_id(source_channel)
        self.target_channel = convert_to_chat_id(target_channel)
        self.processed_messages = set()
        self.logger = setup_logging(user_id)
        self.last_activity = datetime.now()
        
        # التحقق النهائي قبل الحفظ
        is_valid_source, source_msg = validate_source_channel(self.source_channel)
        if not is_valid_source:
            raise ValueError(f"قناة المصدر غير صالحة: {source_msg}")
        
        is_valid_target, target_msg = validate_target_channel(self.target_channel)
        if not is_valid_target:
            raise ValueError(f"قناة الهدف غير صالحة: {target_msg}")
        
        # حفظ إعدادات المستخدم
        user_config = {
            "user_id": user_id,
            "source_channel": self.source_channel,
            "target_channel": self.target_channel,
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "last_activity": datetime.now().isoformat(),
            "status": "active"
        }
        save_user_config(user_id, user_config)
        
        self.logger.info(f"✅ تم إنشاء/تحديث بوت للمستخدم {user_id}")
        self.logger.info(f"📡 المصدر: {self.source_channel}")
        self.logger.info(f"🎯 الهدف: {self.target_channel}")
        
        # تسجيل في الإعدادات العامة
        config = load_config()
        if user_id not in config["active_users"]:
            config["active_users"].append(user_id)
            save_config(config)
    
    def update_activity(self):
        """تحديث وقت آخر نشاط"""
        self.last_activity = datetime.now()
        user_config = load_user_config(self.user_id)
        if user_config:
            user_config["last_activity"] = self.last_activity.isoformat()
            save_user_config(self.user_id, user_config)
    
    def update_channels(self, source_channel=None, target_channel=None):
        """تحديث إعدادات القنوات"""
        new_source = source_channel if source_channel else self.source_channel
        new_target = target_channel if target_channel else self.target_channel
        
        # التحقق من القنوات الجديدة
        if source_channel:
            new_source_id = convert_to_chat_id(source_channel)
            is_valid, message = validate_source_channel(new_source_id)
            if not is_valid:
                return False, message
            self.source_channel = new_source_id
        
        if target_channel:
            new_target_id = convert_to_chat_id(target_channel)
            is_valid, message = validate_target_channel(new_target_id)
            if not is_valid:
                return False, message
            self.target_channel = new_target_id
        
        self.logger.info(f"🔄 تم تحديث القنوات - المصدر: {self.source_channel}, الهدف: {self.target_channel}")
        
        # تحديث ملف الإعدادات
        user_config = load_user_config(self.user_id)
        if user_config:
            if source_channel:
                user_config["source_channel"] = self.source_channel
            if target_channel:
                user_config["target_channel"] = self.target_channel
            
            user_config["last_updated"] = datetime.now().isoformat()
            save_user_config(self.user_id, user_config)
        
        # إرسال رسالة تأكيد
        try:
            bot.send_message(
                self.target_channel,
                f"🔄 تم تحديث إعدادات البوت\n"
                f"👤 المستخدم: {self.user_id}\n"
                f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"📡 المصدر: {self.source_channel}\n"
                f"🎯 الهدف: {self.target_channel}\n"
                f"🚀 البوت يعمل الآن بالقنوات الجديدة"
            )
        except Exception as e:
            self.logger.error(f"❌ خطأ في إرسال رسالة التحديث: {e}")
        
        return True, "✅ تم تحديث القنوات بنجاح!"
    
    def check_condition(self, text):
        """تحقق إذا كان النص يحتوي على الشرط المطلوب"""
        if not text:
            return False, None
        
        for line in text.split('\n'):
            line = line.strip()
            # البحث عن سطر الحالة
            if 'الحالة' in line or 'الـحـالـة' in line:
                self.logger.info(f"📋 وجد سطر الحالة: {line}")
                
                # النوع 1: بدون جلسة
                if '✅' in line and 'بدون جلسة' in line and 'لديه جلسة' not in line:
                    self.logger.info(f"✅ وجد النوع 1 (بدون جلسة)")
                    return True, 'type1'
                
                # النوع 2: تم الوصول
                if '✅ تـم الـوصـول' in line or '✅ تم الوصول' in line:
                    self.logger.info(f"✅ وجد النوع 2 (✅ تـم الـوصـول)")
                    return True, 'type2'
        
        return False, None
    
    def handle_channel_post(self, message):
        """معالجة الرسائل الجديدة في القنوات"""
        try:
            # تحديث وقت النشاط
            self.update_activity()
            
            # التحقق إذا كانت الرسالة من قناة هذا المستخدم
            if message.chat.id != self.source_channel:
                return
            
            # الحصول على النص
            text = message.text or message.caption
            
            if not text:
                self.logger.info("⏭️ رسالة بدون نص")
                return
            
            self.logger.info(f"📝 النص: {text[:100]}...")
            
            # التحقق من الشرط
            condition_met, msg_type = self.check_condition(text)
            
            if condition_met:
                # التحقق من الفلتر المتقدم: هل الرقم مجرب من قبل (بناءً على النص)؟
                if is_number_tested(text, self.user_id):
                    self.logger.info(f"⏭️ هذا الرقم مجرب مسبقاً (فلتر) - لن يتم إرساله مرة أخرى")
                    return
                
                # منع التكرار العادي
                msg_id = f"{message.chat.id}_{message.message_id}"
                if msg_id in self.processed_messages:
                    self.logger.info(f"⏭️ تم معالجة هذه الرسالة مسبقاً")
                    return
                
                self.logger.info(f"🎯 الشرط متوفر - النوع: {msg_type}")
                
                try:
                    # إنشاء زر "غير مجرب" مع بيانات callback فريدة
                    callback_data = f"test_{self.user_id}_{message.message_id}_{int(time.time())}"
                    
                    keyboard = telebot.types.InlineKeyboardMarkup()
                    button = telebot.types.InlineKeyboardButton(
                        text="❌ غير مجرب",
                        callback_data=callback_data
                    )
                    keyboard.add(button)
                    
                    # إرسال الرسالة للقناة الهدف مع الزر
                    sent_message = bot.send_message(
                        chat_id=self.target_channel,
                        text=text,
                        parse_mode=None,
                        reply_markup=keyboard
                    )
                    
                    # حفظ حالة الزر في ملف
                    button_states = load_button_states()
                    button_states[callback_data] = {
                        "user_id": self.user_id,
                        "source_message_id": message.message_id,
                        "target_message_id": sent_message.message_id,
                        "target_chat_id": self.target_channel,
                        "status": "untested",
                        "timestamp": datetime.now().isoformat(),
                        "number_text": extract_number_from_text(text),
                        "full_text": text[:500]
                    }
                    save_button_states(button_states)
                    
                    # تحديث إحصائيات الأرقام
                    update_number_stats(self.user_id, msg_type, text)
                    
                    # إذا كانت الرسالة من النوع 2، أرسل رسالة إضافية
                    if msg_type == 'type2':
                        time.sleep(1)
                        bot.send_message(
                            chat_id=self.target_channel,
                            text="📢 الكود جاهز",
                            parse_mode=None
                        )
                    
                    self.logger.info(f"📤 تم الإرسال بنجاح مع زر التقييم!")
                    
                    # إضافة للقائمة لمنع التكرار
                    self.processed_messages.add(msg_id)
                    
                    # تسجيل في ملف المستخدم
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    user_data_file = f"data/user_{self.user_id}_sent.txt"
                    with open(user_data_file, 'a', encoding='utf-8') as f:
                        f.write(f"\n{'='*50}\n")
                        f.write(f"⏰ الوقت: {timestamp}\n")
                        f.write(f"🆔 ID: {message.message_id}\n")
                        f.write(f"📌 النوع: {msg_type}\n")
                        f.write(f"📝 النص:\n{text[:500]}\n")
                        
                except Exception as e:
                    self.logger.error(f"❌ خطأ في الإرسال: {e}")
            else:
                self.logger.info(f"⏭️ لا تطابق الشرط")
            
        except Exception as e:
            self.logger.error(f"💥 خطأ غير متوقع: {e}")
    
    def handle_edited_channel_post(self, message):
        """معالجة تعديلات الرسائل"""
        try:
            # تحديث وقت النشاط
            self.update_activity()
            
            if message.chat.id != self.source_channel:
                return
            
            text = message.text or message.caption
            
            if not text:
                return
            
            self.logger.info(f"✏️ نص معدل: {text[:100]}...")
            
            condition_met, msg_type = self.check_condition(text)
            
            if condition_met:
                # التحقق من الفلتر المتقدم: هل الرقم مجرب من قبل؟
                if is_number_tested(text, self.user_id):
                    self.logger.info(f"⏭️ هذا الرقم مجرب مسبقاً (فلتر) - لن يتم إرسال التعديل")
                    return
                
                msg_id = f"{message.chat.id}_{message.message_id}_edited"
                if msg_id in self.processed_messages:
                    return
                
                self.logger.info(f"🎯 التعديل يطابق الشرط - النوع: {msg_type}")
                
                try:
                    # إنشاء زر "غير مجرب" مع بيانات callback فريدة
                    callback_data = f"test_{self.user_id}_{message.message_id}_edit_{int(time.time())}"
                    
                    keyboard = telebot.types.InlineKeyboardMarkup()
                    button = telebot.types.InlineKeyboardButton(
                        text="❌ غير مجرب",
                        callback_data=callback_data
                    )
                    keyboard.add(button)
                    
                    # إرسال الرسالة المعدلة مع الزر
                    sent_message = bot.send_message(
                        chat_id=self.target_channel,
                        text=text,
                        parse_mode=None,
                        reply_markup=keyboard
                    )
                    
                    # حفظ حالة الزر
                    button_states = load_button_states()
                    button_states[callback_data] = {
                        "user_id": self.user_id,
                        "source_message_id": message.message_id,
                        "target_message_id": sent_message.message_id,
                        "target_chat_id": self.target_channel,
                        "status": "untested",
                        "timestamp": datetime.now().isoformat(),
                        "number_text": extract_number_from_text(text),
                        "full_text": text[:500],
                        "is_edit": True
                    }
                    save_button_states(button_states)
                    
                    # تحديث إحصائيات الأرقام (للتعديل)
                    update_number_stats(self.user_id, msg_type, f"[تعديل] {text}")
                    
                    if msg_type == 'type2':
                        time.sleep(1)
                        bot.send_message(
                            chat_id=self.target_channel,
                            text="📢 الكود جاهز (تعديل)",
                            parse_mode=None
                        )
                    
                    self.processed_messages.add(msg_id)
                    
                    # تسجيل التعديل
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    user_edit_file = f"data/user_{self.user_id}_edits.txt"
                    with open(user_edit_file, 'a', encoding='utf-8') as f:
                        f.write(f"\n{'='*50}\n")
                        f.write(f"⏰ الوقت: {timestamp}\n")
                        f.write(f"🆔 ID: {message.message_id}\n")
                        f.write(f"📌 النوع: {msg_type}\n")
                        f.write(f"📝 النص المعدل:\n{text[:500]}\n")
                        
                except Exception as e:
                    self.logger.error(f"❌ خطأ في إرسال التعديل: {e}")
            
        except Exception as e:
            self.logger.error(f"💥 خطأ في التعديل: {e}")

# ==================== المتغيرات العامة ====================

# قاموس لتخزين البوتات النشطة
active_bots = {}

# ==================== دوال تحميل البوتات ====================

def load_all_bots():
    """تحميل جميع البوتات النشطة - تعمل تلقائياً عند بدء التشغيل"""
    config = load_config()
    loaded_count = 0
    
    logging.info("🔄 جاري تحميل البوتات النشطة تلقائياً...")
    
    for user_id in config["active_users"]:
        user_config = load_user_config(user_id)
        if user_config and user_config.get("status") == "active":
            try:
                bot_instance = UserBot(
                    user_id=user_config["user_id"],
                    source_channel=user_config["source_channel"],
                    target_channel=user_config["target_channel"]
                )
                active_bots[user_id] = bot_instance
                loaded_count += 1
                logging.info(f"✅ تم تحميل بوت المستخدم: {user_id}")
                
            except Exception as e:
                logging.error(f"❌ خطأ في تحميل بوت {user_id}: {str(e)}")
    
    # تنظيف الأرقام المجربة القديمة (أكثر من 30 يوم)
    cleanup_old_tested_numbers(30)
    
    logging.info(f"📊 تم تحميل {loaded_count} بوت نشط تلقائياً")
    
    # عرض إحصائيات الأرقام
    stats = get_total_numbers_count()
    logging.info(f"📊 إحصائيات الأرقام: إجمالي={stats['total']}, بدون جلسة={stats['without_session']}, تم الوصول={stats['accessed']}, مجرب={stats['tested']}")
    
    # إرسال إشعار بعودة البوت للعمل
    if loaded_count > 0:
        send_start_notification()
    
    return loaded_count

# ==================== معالجات البوت العامة ====================

@bot.channel_post_handler(func=lambda message: True)
def handle_all_channel_posts(message):
    """توزيع الرسائل على جميع البوتات النشطة"""
    for user_bot in active_bots.values():
        try:
            user_bot.handle_channel_post(message)
        except Exception as e:
            logging.error(f"❌ خطأ في معالجة رسالة للمستخدم {user_bot.user_id}: {e}")

@bot.edited_channel_post_handler(func=lambda message: True)
def handle_all_edited_posts(message):
    """توزيع التعديلات على جميع البوتات النشطة"""
    for user_bot in active_bots.values():
        try:
            user_bot.handle_edited_channel_post(message)
        except Exception as e:
            logging.error(f"❌ خطأ في معالجة تعديل للمستخدم {user_bot.user_id}: {e}")

# ==================== معالج الضغط على الأزرار ====================

@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    """معالجة الضغط على الأزرار"""
    callback_data = call.data
    
    # تحميل حالات الأزرار
    button_states = load_button_states()
    
    if callback_data in button_states:
        button_info = button_states[callback_data]
        
        # التحقق من أن المستخدم الذي ضغط على الزر هو نفسه صاحب البوت
        if button_info["status"] == "untested":
            
            # معلومات المختبر
            tester_info = {
                "id": call.from_user.id,
                "username": call.from_user.username,
                "first_name": call.from_user.first_name,
                "tested_at": datetime.now().isoformat()
            }
            
            # تسجيل الرقم في الفلتر (باستخدام نص الرقم)
            source_message_id = button_info["source_message_id"]
            number_text = button_info.get("full_text") or button_info.get("number_text", "")
            mark_number_as_tested(button_info["user_id"], source_message_id, number_text, tester_info)
            
            # تحديث حالة الزر
            button_info["status"] = "tested"
            button_info["tested_by"] = call.from_user.id
            button_info["tested_at"] = datetime.now().isoformat()
            button_info["tester_username"] = call.from_user.username or call.from_user.first_name
            save_button_states(button_states)
            
            # تحديث الزر في الرسالة
            try:
                keyboard = telebot.types.InlineKeyboardMarkup()
                button = telebot.types.InlineKeyboardButton(
                    text="✅ مجرب (تم حفظه في الفلتر)",
                    callback_data=callback_data
                )
                keyboard.add(button)
                
                bot.edit_message_reply_markup(
                    chat_id=button_info["target_chat_id"],
                    message_id=button_info["target_message_id"],
                    reply_markup=keyboard
                )
                
                # إرسال إشعار للمستخدم بأنه تم التحديث
                bot.answer_callback_query(
                    call.id,
                    text="✅ تم حفظ الرقم في الفلتر - لن يتم إرساله مرة أخرى",
                    show_alert=False
                )
                
                # تسجيل التغيير في ملف خاص
                user_id = button_info["user_id"]
                log_file = f"data/user_{user_id}_tested.txt"
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(f"\n{'='*50}\n")
                    f.write(f"⏰ الوقت: {datetime.now().isoformat()}\n")
                    f.write(f"📌 الرسالة المصدر: {button_info['source_message_id']}\n")
                    f.write(f"📝 المختبر: {call.from_user.username or call.from_user.first_name} ({call.from_user.id})\n")
                    f.write(f"✅ تم إضافته للفلتر بناءً على نص الرقم\n")
                
            except Exception as e:
                logging.error(f"❌ خطأ في تحديث الزر: {e}")
                bot.answer_callback_query(
                    call.id,
                    text=f"❌ حدث خطأ: {str(e)}",
                    show_alert=True
                )
        else:
            bot.answer_callback_query(
                call.id,
                text="⚠️ تم تجربة هذه الرسالة مسبقاً",
                show_alert=False
            )
    else:
        bot.answer_callback_query(
            call.id,
            text="❌ هذه الرسالة غير موجودة في النظام",
            show_alert=True
        )

# ==================== أوامر البوت ====================

@bot.message_handler(commands=['start'])
def start_command(message):
    """بدء إعداد بوت جديد"""
    user_id = str(message.from_user.id)
    
    if user_id in active_bots:
        bot.reply_to(message, 
            "⚠️ لديك بوت نشط بالفعل!\n\n"
            "استخدم:\n"
            "/status - لعرض حالة البوت\n"
            "/edit - لتعديل إعدادات القنوات\n"
            "/stop - لإيقاف البوت"
        )
        return
    
    bot.reply_to(message, 
        "👋 أهلاً بك في بوت التلقائي!\n\n"
        "📝 الرجاء إرسال:\n"
        "1️⃣ معرف قناة المصدر (يجب أن يكون البوت مشرفاً فيها)\n\n"
        "📌 أمثلة:\n"
        "• معرف رقمي: -1001234567890\n"
        "• معرف نصي: @channel_name\n\n"
        "أرسل الآن معرف قناة المصدر:"
    )
    
    bot.register_next_step_handler(message, get_source_channel)

def get_source_channel(message):
    """الحصول على قناة المصدر"""
    user_id = str(message.from_user.id)
    source_channel = message.text.strip()
    
    # إظهار حالة الكتابة
    bot.send_chat_action(message.chat.id, 'typing')
    
    # التحقق من صحة القناة المصدر
    is_valid, validation_message = validate_source_channel(source_channel)
    
    if not is_valid:
        bot.reply_to(message, validation_message + "\n\nأرسل معرف قناة المصدر الصحيح:")
        bot.register_next_step_handler(message, get_source_channel)
        return
    
    # حفظ مؤقت
    user_edit_state[user_id] = {
        "source_channel": source_channel,
        "step": "waiting_for_target"
    }
    
    bot.reply_to(message,
        f"{validation_message}\n\n"
        f"2️⃣ الرجاء إرسال معرف القناة الهدف (سيتم إرسال الرسائل إليها):\n\n"
        f"📌 أمثلة:\n"
        f"• معرف رقمي: -1009876543210\n"
        f"• معرف نصي: @target_channel\n\n"
        f"أرسل الآن معرف قناة الهدف:"
    )
    
    bot.register_next_step_handler(message, get_target_channel)

def get_target_channel(message):
    """الحصول على قناة الهدف"""
    user_id = str(message.from_user.id)
    target_channel = message.text.strip()
    
    if user_id not in user_edit_state:
        bot.reply_to(message, "❌ انتهت الجلسة. استخدم /start للبدء من جديد")
        return
    
    # إظهار حالة الكتابة
    bot.send_chat_action(message.chat.id, 'typing')
    
    # التحقق من صحة القناة الهدف
    is_valid, validation_message = validate_target_channel(target_channel)
    
    if not is_valid:
        bot.reply_to(message, validation_message + "\n\nأرسل معرف قناة الهدف الصحيح:")
        bot.register_next_step_handler(message, get_target_channel)
        return
    
    source_channel = user_edit_state[user_id]["source_channel"]
    
    # إنشاء بوت جديد للمستخدم
    try:
        user_bot = UserBot(
            user_id=user_id,
            source_channel=source_channel,
            target_channel=target_channel
        )
        active_bots[user_id] = user_bot
        
        # تنظيف الحالة المؤقتة
        if user_id in user_edit_state:
            del user_edit_state[user_id]
        
        # إرسال رسالة بدء في قناة الهدف
        try:
            bot.send_message(
                target_channel,
                f"🤖 البوت بدأ العمل\n"
                f"👤 للمستخدم: {user_id}\n"
                f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"🔍 جاري البحث عن:\n"
                f"• '✅ بدون جلسة'\n"
                f"• '✅ تم الوصول'\n"
                f"📤 سيتم إرسال كل رسالة مع زر تقييم\n"
                f"🔄 عند الضغط على الزر:\n"
                f"   - يتحول إلى '✅ مجرب'\n"
                f"   - يتم حفظ الرقم في الفلتر بناءً على النص\n"
                f"   - **لن يتم إرسال نفس الرقم مرة أخرى** حتى لو ظهر في رسالة جديدة\n\n"
                f"📊 لعرض الإحصائيات: /stats\n\n"
                f"⚠️ ملاحظة: عند توقف البوت سيتم إرسال إشعار تلقائي"
            )
        except:
            pass
        
        # إحصائيات بعد الإنشاء
        stats = get_total_numbers_count()
        
        bot.reply_to(message,
            f"✅ {validation_message}\n\n"
            f"🎉 **تم إنشاء البوت بنجاح!**\n\n"
            f"📊 **معلومات البوت:**\n"
            f"👤 **المستخدم:** `{user_id}`\n"
            f"📡 **المصدر:** `{source_channel}`\n"
            f"🎯 **الهدف:** `{target_channel}`\n\n"
            f"📊 **إحصائيات عامة:**\n"
            f"• إجمالي الأرقام: {stats['total']}\n"
            f"• ✅ بدون جلسة: {stats['without_session']}\n"
            f"• 📱 تم الوصول: {stats['accessed']}\n"
            f"• 🔬 مجرب: {stats['tested']}\n\n"
            f"⚙️ **الأوامر:**\n"
            f"• `/status` - عرض الحالة\n"
            f"• `/stats` - عرض إحصائيات التقييم\n"
            f"• `/filter` - عرض الأرقام المجربة\n"
            f"• `/edit` - تعديل الإعدادات\n"
            f"• `/stop` - إيقاف البوت\n\n"
            f"🚀 **البوت يعمل الآن ويتم مراقبة القناة المصدر!**\n"
            f"🔒 **ملاحظة مهمة:** إذا ضغطت على زر 'مجرب' لن يتم إرسال نفس الرقم مرة أخرى أبداً!\n"
            f"📢 **سيتم إشعارك عند توقف البوت وعودته للعمل تلقائياً**",
            parse_mode="Markdown"
        )
        
    except ValueError as e:
        bot.reply_to(message, f"❌ {str(e)}\n\nاستخدم /start للبدء من جديد")
    except Exception as e:
        bot.reply_to(message, f"❌ خطأ في إنشاء البوت: {str(e)}\n\nاستخدم /start للبدء من جديد")

@bot.message_handler(commands=['filter'])
def filter_command(message):
    """عرض الأرقام المجربة (الفلتر)"""
    user_id = str(message.from_user.id)
    
    tested_numbers = get_user_tested_numbers(user_id)
    
    if not tested_numbers:
        bot.reply_to(message, "📊 لا توجد أرقام مجربة بعد")
        return
    
    filter_text = f"🔬 **الأرقام المجربة (الفلتر):** {len(tested_numbers)}\n\n"
    filter_text += "هذه الأرقام لن يتم إرسالها مرة أخرى:\n\n"
    
    # عرض آخر 10 أرقام مجربة
    for i, num in enumerate(tested_numbers[-10:], 1):
        filter_text += f"{i}. **{num['number_text']}**\n"
        filter_text += f"   ⏰ {num['tested_at'][:19]}\n"
        if num.get('tester') and num['tester'].get('username'):
            filter_text += f"   👤 بواسطة: @{num['tester']['username']}\n"
        filter_text += "\n"
    
    filter_text += f"\n📊 إجمالي الأرقام المجربة: {len(tested_numbers)}"
    
    bot.reply_to(message, filter_text, parse_mode="Markdown")

@bot.message_handler(commands=['status'])
def status_command(message):
    """عرض حالة البوت"""
    user_id = str(message.from_user.id)
    
    if user_id in active_bots:
        user_config = load_user_config(user_id)
        if user_config:
            # محاولة جلب أسماء القنوات
            source_name = str(user_config['source_channel'])
            target_name = str(user_config['target_channel'])
            
            try:
                source_chat = bot.get_chat(user_config['source_channel'])
                source_name = f"{source_chat.title} (`{source_chat.id}`)"
            except:
                pass
            
            try:
                target_chat = bot.get_chat(user_config['target_channel'])
                target_name = f"{target_chat.title} (`{target_chat.id}`)"
            except:
                pass
            
            # إحصائيات الأزرار
            button_states = load_button_states()
            user_buttons = [b for b in button_states.values() if b["user_id"] == user_id]
            total_buttons = len(user_buttons)
            tested_buttons = len([b for b in user_buttons if b["status"] == "tested"])
            untested_buttons = total_buttons - tested_buttons
            
            # إحصائيات الأرقام للمستخدم
            stats = load_numbers_stats()
            user_stats = stats["users_stats"].get(user_id, {"total": 0, "without_session": 0, "accessed": 0, "tested": 0})
            
            # الأرقام المجربة
            tested_numbers = get_user_tested_numbers(user_id)
            user_tested_count = len(tested_numbers)
            
            # حالة البوت العامة
            bot_status = load_bot_status()
            
            bot.reply_to(message,
                f"📊 **حالة البوت:**\n\n"
                f"✅ **البوت نشط**\n"
                f"👤 **المستخدم:** `{user_id}`\n"
                f"📡 **المصدر:** {source_name}\n"
                f"🎯 **الهدف:** {target_name}\n"
                f"📅 **الإنشاء:** {user_config['created_at'][:19]}\n"
                f"🔄 **آخر تحديث:** {user_config['last_updated'][:19]}\n"
                f"⏰ **آخر نشاط:** {user_config.get('last_activity', 'غير معروف')[:19]}\n\n"
                f"📊 **إحصائيات الأرقام:**\n"
                f"• إجمالي الأرقام: {user_stats['total']}\n"
                f"• ✅ بدون جلسة: {user_stats['without_session']}\n"
                f"• 📱 تم الوصول: {user_stats['accessed']}\n"
                f"• 🔬 مجرب (فلتر): {user_tested_count}\n\n"
                f"📊 **إحصائيات التقييم:**\n"
                f"• إجمالي الرسائل: {total_buttons}\n"
                f"• ✅ مجرب: {tested_buttons}\n"
                f"• ❌ غير مجرب: {untested_buttons}\n\n"
                f"📊 **حالة البوت العام:**\n"
                f"• آخر تشغيل: {bot_status.get('last_start', 'غير معروف')[:19]}\n"
                f"• آخر توقف: {bot_status.get('last_stop', 'لم يتوقف')[:19] if bot_status.get('last_stop') else 'لم يتوقف'}\n"
                f"• عدد مرات التوقف: {bot_status.get('stop_count', 0)}\n\n"
                f"📁 **الملفات:**\n"
                f"• `logs/user_{user_id}.txt` - السجلات\n"
                f"• `data/user_{user_id}_*.txt` - البيانات\n\n"
                f"⚙️ **الأوامر:**\n"
                f"• `/edit` - تعديل الإعدادات\n"
                f"• `/filter` - عرض الأرقام المجربة\n"
                f"• `/stop` - إيقاف البوت",
                parse_mode="Markdown"
            )
        else:
            bot.reply_to(message, "❌ لا توجد معلومات عن البوت")
    else:
        bot.reply_to(message, "⚠️ ليس لديك بوت نشط. استخدم /start لإنشاء بوت")

@bot.message_handler(commands=['stats'])
def stats_command(message):
    """عرض إحصائيات التقييم"""
    user_id = str(message.from_user.id)
    
    stats = load_numbers_stats()
    user_stats = stats["users_stats"].get(user_id, {})
    tested_numbers = get_user_tested_numbers(user_id)
    
    if not user_stats:
        bot.reply_to(message, "📊 لا توجد إحصائيات بعد")
        return
    
    stats_text = f"📊 **إحصائيات الأرقام**\n\n"
    stats_text += f"📈 **الإجمالي:** {user_stats.get('total', 0)} رقم\n"
    stats_text += f"✅ **بدون جلسة:** {user_stats.get('without_session', 0)}\n"
    stats_text += f"📱 **تم الوصول:** {user_stats.get('accessed', 0)}\n"
    stats_text += f"🔬 **مجرب (فلتر):** {len(tested_numbers)}\n\n"
    
    if user_stats.get('total', 0) > 0:
        without_percent = (user_stats.get('without_session', 0) / user_stats['total']) * 100
        accessed_percent = (user_stats.get('accessed', 0) / user_stats['total']) * 100
        tested_percent = (len(tested_numbers) / user_stats['total']) * 100
        
        stats_text += f"📊 **النسب المئوية:**\n"
        stats_text += f"• بدون جلسة: {without_percent:.1f}%\n"
        stats_text += f"• تم الوصول: {accessed_percent:.1f}%\n"
        stats_text += f"• مجرب: {tested_percent:.1f}%\n\n"
    
    # آخر 5 أرقام
    if user_stats.get('last_numbers'):
        stats_text += "🕒 **آخر 5 أرقام:**\n"
        for num in user_stats['last_numbers'][:5]:
            emoji = "✅" if num['type'] == 'type1' else "📱"
            stats_text += f"• {emoji} {num['time'][11:19]} - {num['text'][:50]}...\n"
    
    bot.reply_to(message, stats_text, parse_mode="Markdown")

@bot.message_handler(commands=['edit'])
def edit_command(message):
    """بدء عملية تعديل الإعدادات"""
    user_id = str(message.from_user.id)
    
    if user_id not in active_bots:
        bot.reply_to(message, "⚠️ ليس لديك بوت نشط. استخدم /start لإنشاء بوت")
        return
    
    # حفظ حالة المستخدم
    user_edit_state[user_id] = {
        "step": "waiting_for_option",
        "user_bot": active_bots[user_id]
    }
    
    # عرض خيارات التعديل
    keyboard = telebot.types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True, one_time_keyboard=True)
    keyboard.add("📡 تعديل قناة المصدر", "🎯 تعديل قناة الهدف")
    keyboard.add("🔄 تعديل كلتا القناتين", "❌ إلغاء التعديل")
    
    bot.reply_to(message,
        "🔄 **تعديل إعدادات البوت**\n\n"
        "اختر ما تريد تعديله:\n\n"
        "📡 تعديل قناة المصدر - تغيير القناة التي يتابعها البوت\n"
        "🎯 تعديل قناة الهدف - تغيير القناة التي يرسل إليها البوت\n"
        "🔄 تعديل كلتا القناتين - تغيير القناتين معاً\n"
        "❌ إلغاء التعديل - الرجوع دون تعديل",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    
    bot.register_next_step_handler(message, handle_edit_option)

def handle_edit_option(message):
    """معالجة خيار التعديل"""
    user_id = str(message.from_user.id)
    
    if user_id not in user_edit_state:
        bot.reply_to(message, "❌ انتهت جلسة التعديل. استخدم /edit لبدء جديدة", 
                    reply_markup=telebot.types.ReplyKeyboardRemove())
        return
    
    option = message.text
    user_edit_state[user_id]["option"] = option
    
    if option == "❌ إلغاء التعديل":
        bot.reply_to(message, "✅ تم إلغاء التعديل", 
                    reply_markup=telebot.types.ReplyKeyboardRemove())
        del user_edit_state[user_id]
        return
    
    # تحديد الخطوة التالية بناءً على الخيار
    if option == "📡 تعديل قناة المصدر":
        user_edit_state[user_id]["step"] = "waiting_for_source"
        bot.reply_to(message,
            "📡 **تعديل قناة المصدر**\n\n"
            "أرسل الآن معرف قناة المصدر الجديدة:\n\n"
            "📌 أمثلة:\n"
            "• معرف رقمي: -1001234567890\n"
            "• معرف نصي: @channel_name\n\n"
            "⚠️ تأكد أن البوت مشرف في القناة",
            reply_markup=telebot.types.ReplyKeyboardRemove(),
            parse_mode="Markdown"
        )
        bot.register_next_step_handler(message, handle_source_update)
    
    elif option == "🎯 تعديل قناة الهدف":
        user_edit_state[user_id]["step"] = "waiting_for_target"
        bot.reply_to(message,
            "🎯 **تعديل قناة الهدف**\n\n"
            "أرسل الآن معرف قناة الهدف الجديدة:\n\n"
            "📌 أمثلة:\n"
            "• معرف رقمي: -1001234567890\n"
            "• معرف نصي: @channel_name\n\n"
            "⚠️ تأكد أن البوت يستطيع الكتابة في القناة",
            reply_markup=telebot.types.ReplyKeyboardRemove(),
            parse_mode="Markdown"
        )
        bot.register_next_step_handler(message, handle_target_update)
    
    elif option == "🔄 تعديل كلتا القناتين":
        user_edit_state[user_id]["step"] = "waiting_for_source"
        bot.reply_to(message,
            "🔄 **تعديل كلتا القناتين**\n\n"
            "أولاً، أرسل معرف قناة المصدر الجديدة:\n\n"
            "📌 أمثلة:\n"
            "• معرف رقمي: -1001234567890\n"
            "• معرف نصي: @channel_name\n\n"
            "⚠️ تأكد أن البوت مشرف في القناة",
            reply_markup=telebot.types.ReplyKeyboardRemove(),
            parse_mode="Markdown"
        )
        bot.register_next_step_handler(message, handle_source_update)

def handle_source_update(message):
    """معالجة تحديث قناة المصدر"""
    user_id = str(message.from_user.id)
    
    if user_id not in user_edit_state:
        bot.reply_to(message, "❌ انتهت جلسة التعديل")
        return
    
    new_source = message.text.strip()
    
    # إظهار حالة الكتابة
    bot.send_chat_action(message.chat.id, 'typing')
    
    # التحقق من صحة القناة المصدر
    is_valid, validation_message = validate_source_channel(new_source)
    
    if not is_valid:
        bot.reply_to(message, validation_message + "\n\nأرسل معرف قناة المصدر الصحيح:")
        bot.register_next_step_handler(message, handle_source_update)
        return
    
    user_edit_state[user_id]["new_source"] = new_source
    user_edit_state[user_id]["source_validation"] = validation_message
    
    if user_edit_state[user_id]["option"] == "📡 تعديل قناة المصدر":
        # تحديث قناة المصدر فقط
        user_bot = user_edit_state[user_id]["user_bot"]
        success, message_text = user_bot.update_channels(source_channel=new_source)
        
        if success:
            bot.reply_to(message, f"✅ {validation_message}\n\n{message_text}")
        else:
            bot.reply_to(message, f"❌ {message_text}")
        
        del user_edit_state[user_id]
    
    elif user_edit_state[user_id]["option"] == "🔄 تعديل كلتا القناتين":
        # الانتقال إلى خطوة قناة الهدف
        user_edit_state[user_id]["step"] = "waiting_for_target"
        bot.reply_to(message,
            f"✅ {validation_message}\n\n"
            f"الآن أرسل معرف قناة الهدف الجديدة:\n\n"
            f"📌 أمثلة:\n"
            f"• معرف رقمي: -1001234567890\n"
            f"• معرف نصي: @channel_name"
        )
        bot.register_next_step_handler(message, handle_target_update)

def handle_target_update(message):
    """معالجة تحديث قناة الهدف"""
    user_id = str(message.from_user.id)
    
    if user_id not in user_edit_state:
        bot.reply_to(message, "❌ انتهت جلسة التعديل")
        return
    
    new_target = message.text.strip()
    
    # إظهار حالة الكتابة
    bot.send_chat_action(message.chat.id, 'typing')
    
    # التحقق من صحة القناة الهدف
    is_valid, validation_message = validate_target_channel(new_target)
    
    if not is_valid:
        bot.reply_to(message, validation_message + "\n\nأرسل معرف قناة الهدف الصحيح:")
        bot.register_next_step_handler(message, handle_target_update)
        return
    
    user_bot = user_edit_state[user_id]["user_bot"]
    
    if user_edit_state[user_id]["option"] == "🎯 تعديل قناة الهدف":
        # تحديث قناة الهدف فقط
        success, message_text = user_bot.update_channels(target_channel=new_target)
        
        if success:
            bot.reply_to(message, f"✅ {validation_message}\n\n{message_text}")
        else:
            bot.reply_to(message, f"❌ {message_text}")
    
    elif user_edit_state[user_id]["option"] == "🔄 تعديل كلتا القناتين":
        # تحديث كلتا القناتين
        new_source = user_edit_state[user_id]["new_source"]
        success, message_text = user_bot.update_channels(
            source_channel=new_source,
            target_channel=new_target
        )
        
        if success:
            bot.reply_to(message, 
                f"✅ **تم تحديث كلا القناتين بنجاح!**\n\n"
                f"{user_edit_state[user_id]['source_validation']}\n"
                f"{validation_message}\n\n"
                f"📡 **المصدر:** `{new_source}`\n"
                f"🎯 **الهدف:** `{new_target}`\n\n"
                f"{message_text}",
                parse_mode="Markdown"
            )
        else:
            bot.reply_to(message, f"❌ {message_text}")
    
    del user_edit_state[user_id]

@bot.message_handler(commands=['stop'])
def stop_command(message):
    """إيقاف البوت"""
    user_id = str(message.from_user.id)
    
    if user_id in active_bots:
        # تحديث حالة المستخدم
        user_config = load_user_config(user_id)
        if user_config:
            user_config["status"] = "stopped"
            user_config["stopped_at"] = datetime.now().isoformat()
            save_user_config(user_id, user_config)
        
        # إرسال رسالة وداع في قناة الهدف
        try:
            user_bot = active_bots[user_id]
            bot.send_message(
                user_bot.target_channel,
                f"🛑 البوت توقف عن العمل\n"
                f"👤 المستخدم: {user_id}\n"
                f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"لإعادة التشغيل استخدم /start"
            )
        except:
            pass
        
        # إزالة من البوتات النشطة
        del active_bots[user_id]
        
        # إزالة من القائمة العامة
        config = load_config()
        if user_id in config["active_users"]:
            config["active_users"].remove(user_id)
            save_config(config)
        
        # تنظيف حالة التعديل إذا كانت موجودة
        if user_id in user_edit_state:
            del user_edit_state[user_id]
        
        bot.reply_to(message, "✅ تم إيقاف البوت بنجاح")
    else:
        bot.reply_to(message, "⚠️ ليس لديك بوت نشط لإيقافه")

@bot.message_handler(commands=['help', 'المساعدة'])
def help_command(message):
    """عرض المساعدة"""
    help_text = """
🤖 **أوامر البوت:**

/start - بدء إعداد بوت جديد
/status - عرض حالة البوت الخاص بك
/stats - عرض إحصائيات الأرقام
/filter - عرض الأرقام المجربة (الفلتر)
/edit - تعديل إعدادات القنوات
/stop - إيقاف البوت الخاص بك
/help - عرض هذه الرسالة

📝 **متطلبات القنوات:**

**قناة المصدر:**
✅ البوت يجب أن يكون مشرفاً
✅ يمكن أن تكون معرف رقمي (-100...) أو نصي (@...)

**قناة الهدف:**
✅ البوت يجب أن يستطيع الكتابة
✅ يمكن أن تكون معرف رقمي (-100...) أو نصي (@...)

🔄 **نظام الفلتر (منع التكرار):**
• عند الضغط على زر "❌ غير مجرب"
• يتحول الزر إلى "✅ مجرب"
• يتم حفظ الرقم في الفلتر بناءً على نص الرقم
• **إذا ظهر نفس الرقم مرة أخرى في المصدر**
• **لن يتم إرساله للهدف مرة أخرى** (حتى لو كان برسالة جديدة)

📊 **أنواع الأرقام:**
• ✅ بدون جلسة - أرقام جديدة
• 📱 تم الوصول - أرقام مفتوحة
• 🔬 مجرب - أرقام تم اختبارها (محفوظة في الفلتر)

🔄 **إشعارات التوقف والتشغيل:**
• عند توقف البوت، سيتم إرسال إشعار تلقائي
• عند عودة البوت للعمل، سيتم إرسال إشعار تلقائي
• يتم تسجيل عدد مرات التوقف
• **لا تحتاج لأي تدخل يدوي** - البوت يعيد تشغيل نفسه

🔄 **عملية التعديل (/edit):**
1. اختر ما تريد تعديله
2. أرسل المعرف الجديد
3. يتم التحقق من الصلاحيات تلقائياً

📊 **ملاحظات مهمة:**
• البوت يعيد تشغيل نفسه تلقائياً عند الانقطاع
• جميع الإعدادات محفوظة ولا تحتاج لإعادة إدخال
• الفلتر يمنع تكرار الأرقام المجربة نهائياً
• كل مستخدم له بياناته المنفصلة
• يتم إشعارك عند توقف البوت وعودته للعمل
"""
    bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def handle_other_messages(message):
    """معالجة الرسائل الأخرى"""
    user_id = str(message.from_user.id)
    
    # إذا كان المستخدم في حالة تعديل
    if user_id in user_edit_state:
        # إعادة توجيه الرسالة إلى المعالج المناسب
        step = user_edit_state[user_id].get("step")
        
        if step == "waiting_for_option":
            handle_edit_option(message)
        elif step == "waiting_for_source":
            handle_source_update(message)
        elif step == "waiting_for_target":
            handle_target_update(message)
    else:
        bot.reply_to(message, 
            "ℹ️ **أرسل:**\n"
            "/start - لإنشاء بوت جديد\n"
            "/help - لعرض الأوامر المتاحة",
            parse_mode="Markdown"
        )

# ==================== مراقبة صحة البوت وإعادة التشغيل التلقائي ====================

def health_monitor():
    """مراقبة صحة البوت وإعادة التشغيل إذا لزم الأمر"""
    last_heartbeat = time.time()
    heartbeat_interval = 300  # 5 دقائق
    
    while True:
        try:
            time.sleep(60)  # فحص كل دقيقة
            
            # فحص اتصال البوت
            bot.get_me()
            last_heartbeat = time.time()
            
            # فحص webhook
            webhook_info = bot.get_webhook_info()
            if webhook_info.url != WEBHOOK_URL:
                logging.warning("⚠️ Webhook تغير، جاري إعادة التعيين...")
                setup_webhook()
            
            # تنظيف الذاكرة من الرسائل القديمة
            for user_bot in active_bots.values():
                # الاحتفاظ بآخر 1000 رسالة فقط
                if len(user_bot.processed_messages) > 1000:
                    user_bot.processed_messages = set(list(user_bot.processed_messages)[-1000:])
            
            # تنظيف الأرقام المجربة القديمة مرة في اليوم
            if datetime.now().hour == 3 and datetime.now().minute == 0:  # الساعة 3 صباحاً
                cleanup_old_tested_numbers(30)
            
            # التحقق من أن البوت لا يزال يعمل
            if time.time() - last_heartbeat > heartbeat_interval:
                logging.warning("⚠️ البوت قد يكون متوقفاً، جاري إعادة التشغيل...")
                send_stop_notification()
                # إعادة تشغيل خفيفة
                python = sys.executable
                os.execl(python, python, *sys.argv)
            
        except requests.exceptions.ConnectionError:
            logging.error("❌ خطأ في الاتصال بالإنترنت")
            time.sleep(10)
        except Exception as e:
            logging.error(f"❌ خطأ في مراقبة الصحة: {e}")
            # إذا كان الخطأ خطيراً، أرسل إشعار توقف
            if "Connection" in str(e) or "timeout" in str(e).lower():
                send_stop_notification()

# ==================== معالج الإشارات ====================

def signal_handler(sig, frame):
    """معالجة إشارات التوقف"""
    logging.info("📥 تم استلام إشارة توقف")
    send_stop_notification()
    sys.exit(0)

import signal
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ==================== الدالة الرئيسية ====================

def main():
    """الدالة الرئيسية"""
    print("="*70)
    print("🤖 TELEBOT MULTI-USER SYSTEM WITH AUTO-RESTART & FILTER")
    print("="*70)
    
    # معلومات البوت
    try:
        bot_info = bot.get_me()
        print(f"🔑 البوت: @{bot_info.username}")
    except:
        print("❌ فشل الاتصال بالبوت!")
        return
    
    print(f"🌐 Webhook URL: {WEBHOOK_URL or 'غير معرف'}")
    print("👥 يدعم عدة مستخدمين")
    print("🔄 إعادة تشغيل تلقائي عند الانقطاع")
    print("🔍 فلتر لمنع تكرار الأرقام المجربة")
    print("📊 إحصائيات تفصيلية للأرقام")
    print("📢 إشعارات تلقائية عند التوقف والعودة")
    print("="*70)
    
    # تحميل البوتات النشطة تلقائياً
    loaded_bots = load_all_bots()
    print(f"✅ تم تحميل {loaded_bots} بوت نشط تلقائياً")
    
    # عرض إحصائيات الأرقام
    stats = get_total_numbers_count()
    print(f"📊 إحصائيات الأرقام:")
    print(f"   • إجمالي: {stats['total']}")
    print(f"   • بدون جلسة: {stats['without_session']}")
    print(f"   • تم الوصول: {stats['accessed']}")
    print(f"   • مجرب: {stats['tested']}")
    print("="*70)
    
    # إعداد Webhook
    if WEBHOOK_URL:
        print("🔄 جاري تعيين Webhook...")
        if setup_webhook():
            print("✅ Webhook تم تعيينه بنجاح!")
            
            # بدء مراقبة webhook في thread منفصل
            monitor_thread = threading.Thread(target=verify_webhook, daemon=True)
            monitor_thread.start()
            
            # بدء مراقبة الصحة في thread منفصل
            health_thread = threading.Thread(target=health_monitor, daemon=True)
            health_thread.start()
        else:
            print("❌ فشل تعيين Webhook!")
            return
    else:
        print("⚠️ RENDER_EXTERNAL_URL غير موجود، سيتم استخدام polling")
        print("⚠️ هذا قد يسبب مشاكل في الاستقرار!")
        
        # بدء polling في thread منفصل
        def run_polling():
            try:
                bot.polling(non_stop=True, interval=2)
            except Exception as e:
                logging.error(f"❌ خطأ في polling: {e}")
                send_stop_notification()
        
        polling_thread = threading.Thread(target=run_polling, daemon=True)
        polling_thread.start()
    
    print("\n🚀 البوت يعمل الآن تلقائياً!")
    print("✅ لا حاجة لإعادة إدخال القنوات بعد إعادة التشغيل")
    print("📢 سيتم إشعارك عند توقف البوت وعودته للعمل")
    print("👤 أرسل /start لإنشاء بوت جديد")
    print("📊 أرسل /status للتحقق من حالة بوتك")
    print("📈 أرسل /stats لعرض إحصائيات الأرقام")
    print("🔬 أرسل /filter لعرض الأرقام المجربة")
    print("🔄 أرسل /edit لتعديل إعدادات قنواتك")
    print("🛑 أرسل /stop لإيقاف بوتك")
    print("="*70)
    
    # تشغيل Flask (هذا سيبقى البرنامج قيد التشغيل)
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️ تم إيقاف البوت يدوياً")
        send_stop_notification()
    except Exception as e:
        print(f"💥 خطأ غير متوقع: {e}")
        traceback.print_exc()
        print("🔄 جاري إعادة التشغيل بعد 5 ثوان...")
        send_stop_notification()
        time.sleep(5)
        os.execl(sys.executable, sys.executable, *sys.argv)