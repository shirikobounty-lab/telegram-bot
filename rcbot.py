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

# ==================== الإعدادات الثابتة للمستخدمين ====================

# معرف المستخدم الرئيسي (ثابت)
MASTER_USER_ID = "123456789"  # ضع معرفك هنا

# القنوات الثابتة - كل مصدر مع هدفه الخاص
FIXED_CHANNELS = [
    {
        "user_id": MASTER_USER_ID,
        "source": "-1003437952069",  # مصدر 1
        "target": "-1003803319987"    # هدف 1
    },
    {
        "user_id": MASTER_USER_ID,
        "source": "-1003361106043",  # مصدر 2
        "target": "-1003701648173"    # هدف 2
    },
    {
        "user_id": MASTER_USER_ID,
        "source": "-1003670244603",  # مصدر 3
        "target": "-1003834998027"    # هدف 3
    }
]

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
        
        # إرسال إشعار لجميع القنوات الهدف
        for channel_info in FIXED_CHANNELS:
            try:
                bot.send_message(
                    channel_info["target"],
                    f"⚠️ **تنبيه: توقف البوت مؤقتاً**\n\n"
                    f"👤 المستخدم: {channel_info['user_id']}\n"
                    f"📡 المصدر: {channel_info['source']}\n"
                    f"🎯 الهدف: {channel_info['target']}\n"
                    f"⏰ وقت التوقف: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"📊 عدد مرات التوقف: {status['stop_count']}\n\n"
                    f"🔄 سيتم إعادة التشغيل تلقائياً خلال لحظات..."
                )
                logging.info(f"📤 تم إرسال إشعار توقف للقناة {channel_info['target']}")
            except Exception as e:
                logging.error(f"❌ خطأ في إرسال إشعار التوقف للقناة {channel_info['target']}: {e}")
                
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
                    downtime = f"{seconds // 60} دقيقة و{seconds % 60} ثانية"
                else:
                    hours = seconds // 3600
                    minutes = (seconds % 3600) // 60
                    downtime = f"{hours} ساعة و{minutes} دقيقة"
            except:
                pass
        
        # إرسال إشعار لجميع القنوات الهدف
        for channel_info in FIXED_CHANNELS:
            try:
                # إحصائيات الأرقام لهذا المصدر
                source_hash = hashlib.md5(channel_info["source"].encode()).hexdigest()[:8]
                tested_numbers = get_source_tested_numbers(channel_info["source"])
                
                bot.send_message(
                    channel_info["target"],
                    f"✅ **تم إعادة تشغيل البوت تلقائياً**\n\n"
                    f"👤 المستخدم: {channel_info['user_id']}\n"
                    f"📡 المصدر: {channel_info['source']}\n"
                    f"🎯 الهدف: {channel_info['target']}\n"
                    f"⏰ وقت التشغيل: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"⏱️ مدة التوقف: {downtime}\n"
                    f"📊 عدد مرات التوقف: {status['stop_count']}\n\n"
                    f"🔬 الأرقام المجربة لهذا المصدر: {len(tested_numbers)}\n"
                    f"🚀 البوت يعمل الآن بشكل طبيعي\n"
                    f"💾 تم استعادة جميع الإعدادات تلقائياً"
                )
                logging.info(f"📤 تم إرسال إشعار تشغيل للقناة {channel_info['target']}")
            except Exception as e:
                logging.error(f"❌ خطأ في إرسال إشعار التشغيل للقناة {channel_info['target']}: {e}")
                
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
        "sources_stats": {}  # إحصائيات حسب المصدر
    }

def save_numbers_stats(stats):
    """حفظ إحصائيات الأرقام"""
    stats["last_update"] = datetime.now().isoformat()
    with open(NUMBERS_STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=4, ensure_ascii=False)

def update_number_stats(source_channel, number_type, number_text=""):
    """تحديث إحصائيات الأرقام حسب المصدر"""
    stats = load_numbers_stats()
    
    # إحصائيات عامة
    stats["total_processed"] += 1
    
    if number_type == 'type1':
        stats["without_session"] += 1
    elif number_type == 'type2':
        stats["accessed"] += 1
    
    # إحصائيات لكل مصدر
    source_key = str(source_channel)
    if source_key not in stats["sources_stats"]:
        stats["sources_stats"][source_key] = {
            "total": 0,
            "without_session": 0,
            "accessed": 0,
            "tested": 0,
            "last_numbers": []
        }
    
    source_stats = stats["sources_stats"][source_key]
    source_stats["total"] += 1
    
    if number_type == 'type1':
        source_stats["without_session"] += 1
    elif number_type == 'type2':
        source_stats["accessed"] += 1
    
    # حفظ آخر 10 أرقام
    source_stats["last_numbers"].insert(0, {
        "type": number_type,
        "text": number_text[:100],
        "time": datetime.now().isoformat()
    })
    source_stats["last_numbers"] = source_stats["last_numbers"][:10]
    
    save_numbers_stats(stats)
    return stats

def update_tested_stats(source_channel, tester_info):
    """تحديث إحصائيات التجريب حسب المصدر"""
    stats = load_numbers_stats()
    stats["tested"] += 1
    
    source_key = str(source_channel)
    if source_key in stats["sources_stats"]:
        stats["sources_stats"][source_key]["tested"] += 1
    
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
        "numbers": {},  # {number_hash: {"source": "", "tested_at": "", "number_text": "", "message_ids": []}}
        "by_source": {}  # {source: [number_hashes]}
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

def is_number_tested(text, source_channel):
    """التحقق إذا كان الرقم مجرب من قبل لمصدر معين"""
    tested_data = load_tested_numbers()
    number_hash = get_number_hash(text)
    source_key = str(source_channel)
    
    # تحقق إذا كان الهاش موجود لهذا المصدر
    if source_key in tested_data["by_source"]:
        if number_hash in tested_data["by_source"][source_key]:
            return True
    return False

def mark_number_as_tested(source_channel, source_message_id, number_text, tester_info=None):
    """تسجيل رقم كمجرب لمصدر معين"""
    tested_data = load_tested_numbers()
    number_hash = get_number_hash(number_text)
    extracted_number = extract_number_from_text(number_text)
    source_key = str(source_channel)
    
    # معلومات الرقم
    number_info = {
        "source": source_key,
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
        
        # أضف للمصدر
        if source_key not in tested_data["by_source"]:
            tested_data["by_source"][source_key] = []
        if number_hash not in tested_data["by_source"][source_key]:
            tested_data["by_source"][source_key].append(number_hash)
    
    save_tested_numbers(tested_data)
    
    # تحديث الإحصائيات
    update_tested_stats(source_key, tester_info)
    
    logging.info(f"✅ تم تسجيل رقم كمجرب - المصدر: {source_key}, الهاش: {number_hash}")
    return number_hash

def get_source_tested_numbers(source_channel):
    """الحصول على جميع الأرقام المجربة لمصدر معين"""
    tested_data = load_tested_numbers()
    source_key = str(source_channel)
    
    if source_key not in tested_data["by_source"]:
        return []
    
    result = []
    for h in tested_data["by_source"][source_key]:
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
            to_delete.append((number_hash, info["source"]))
    
    for number_hash, source_key in to_delete:
        # حذف من قائمة المصدر
        if source_key in tested_data["by_source"] and number_hash in tested_data["by_source"][source_key]:
            tested_data["by_source"][source_key].remove(number_hash)
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
        "fixed_channels": len(FIXED_CHANNELS),
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
                <p><strong>📡 القنوات الثابتة:</strong> {len(FIXED_CHANNELS)}</p>
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
                <p><strong>🚫 الأرقام المجربة (فلتر):</strong> {len(tested_data['numbers'])}</p>
                <p><strong>💾 مساحة التخزين:</strong> {get_folder_size('data')} MB</p>
            </div>
            
            <div class="card">
                <h2>إحصائيات المصادر</h2>
                <table style="width:100%; border-collapse: collapse;">
                    <tr style="background: #0088cc; color: white;">
                        <th style="padding: 10px;">المصدر</th>
                        <th>إجمالي</th>
                        <th>✅ بدون جلسة</th>
                        <th>📱 تم الوصول</th>
                        <th>🔬 مجرب</th>
                    </tr>
                    {''.join([f"<tr><td>{source}</td><td>{s['total']}</td><td>{s['without_session']}</td><td>{s['accessed']}</td><td>{s['tested']}</td></tr>" for source, s in stats['sources_stats'].items()])}
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
    return {"active_sources": []}

def save_config(config):
    """حفظ الإعدادات العامة"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

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

# ==================== كلاس البوت الرئيسي للقنوات الثابتة ====================

class FixedChannelBot:
    """كلاس يمثل بوت للقنوات الثابتة"""
    
    def __init__(self, source_channel, target_channel):
        self.source_channel = convert_to_chat_id(source_channel)
        self.target_channel = convert_to_chat_id(target_channel)
        self.processed_messages = set()
        self.source_key = str(self.source_channel)
        self.logger = logging.getLogger(f"channel_{self.source_key[-8:]}")
        self.last_activity = datetime.now()
        
        # التحقق من صلاحيات القنوات
        self.validate_channels()
        
        self.logger.info(f"✅ تم تهيئة بوت للقنوات الثابتة")
        self.logger.info(f"📡 المصدر: {self.source_channel}")
        self.logger.info(f"🎯 الهدف: {self.target_channel}")
    
    def validate_channels(self):
        """التحقق من صلاحيات القنوات"""
        # التحقق من قناة المصدر
        is_valid_source, source_msg = validate_source_channel(self.source_channel)
        if not is_valid_source:
            raise ValueError(f"قناة المصدر غير صالحة: {source_msg}")
        
        # التحقق من قناة الهدف
        is_valid_target, target_msg = validate_target_channel(self.target_channel)
        if not is_valid_target:
            raise ValueError(f"قناة الهدف غير صالحة: {target_msg}")
        
        self.logger.info(f"✅ التحقق من القنوات: {source_msg} | {target_msg}")
    
    def update_activity(self):
        """تحديث وقت آخر نشاط"""
        self.last_activity = datetime.now()
    
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
            
            # التحقق إذا كانت الرسالة من قناة هذا المصدر
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
                # التحقق من الفلتر: هل الرقم مجرب من قبل لهذا المصدر؟
                if is_number_tested(text, self.source_channel):
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
                    callback_data = f"test_{self.source_key}_{message.message_id}_{int(time.time())}"
                    
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
                        "source": self.source_key,
                        "target": str(self.target_channel),
                        "source_message_id": message.message_id,
                        "target_message_id": sent_message.message_id,
                        "status": "untested",
                        "timestamp": datetime.now().isoformat(),
                        "number_text": extract_number_from_text(text),
                        "full_text": text[:500]
                    }
                    save_button_states(button_states)
                    
                    # تحديث إحصائيات الأرقام
                    update_number_stats(self.source_channel, msg_type, text)
                    
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
                    
                    # تسجيل في ملف خاص
                    log_file = f"data/channel_{self.source_key[-8:]}_sent.txt"
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(f"\n{'='*50}\n")
                        f.write(f"⏰ الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
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
                # التحقق من الفلتر: هل الرقم مجرب من قبل؟
                if is_number_tested(text, self.source_channel):
                    self.logger.info(f"⏭️ هذا الرقم مجرب مسبقاً (فلتر) - لن يتم إرسال التعديل")
                    return
                
                msg_id = f"{message.chat.id}_{message.message_id}_edited"
                if msg_id in self.processed_messages:
                    return
                
                self.logger.info(f"🎯 التعديل يطابق الشرط - النوع: {msg_type}")
                
                try:
                    # إنشاء زر "غير مجرب" مع بيانات callback فريدة
                    callback_data = f"test_{self.source_key}_{message.message_id}_edit_{int(time.time())}"
                    
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
                        "source": self.source_key,
                        "target": str(self.target_channel),
                        "source_message_id": message.message_id,
                        "target_message_id": sent_message.message_id,
                        "status": "untested",
                        "timestamp": datetime.now().isoformat(),
                        "number_text": extract_number_from_text(text),
                        "full_text": text[:500],
                        "is_edit": True
                    }
                    save_button_states(button_states)
                    
                    # تحديث إحصائيات الأرقام
                    update_number_stats(self.source_channel, msg_type, f"[تعديل] {text}")
                    
                    if msg_type == 'type2':
                        time.sleep(1)
                        bot.send_message(
                            chat_id=self.target_channel,
                            text="📢 الكود جاهز (تعديل)",
                            parse_mode=None
                        )
                    
                    self.processed_messages.add(msg_id)
                    
                    # تسجيل التعديل
                    log_file = f"data/channel_{self.source_key[-8:]}_edits.txt"
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(f"\n{'='*50}\n")
                        f.write(f"⏰ الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write(f"🆔 ID: {message.message_id}\n")
                        f.write(f"📌 النوع: {msg_type}\n")
                        f.write(f"📝 النص المعدل:\n{text[:500]}\n")
                        
                except Exception as e:
                    self.logger.error(f"❌ خطأ في إرسال التعديل: {e}")
            
        except Exception as e:
            self.logger.error(f"💥 خطأ في التعديل: {e}")

# ==================== المتغيرات العامة ====================

# قاموس لتخزين البوتات النشطة للقنوات الثابتة
fixed_bots = {}

# ==================== دوال تحميل البوتات الثابتة ====================

def load_fixed_bots():
    """تحميل جميع البوتات للقنوات الثابتة"""
    loaded_count = 0
    
    logging.info("🔄 جاري تحميل البوتات للقنوات الثابتة...")
    
    for channel_info in FIXED_CHANNELS:
        try:
            source = channel_info["source"]
            target = channel_info["target"]
            source_key = str(source)
            
            # إنشاء بوت جديد للقنوات الثابتة
            bot_instance = FixedChannelBot(
                source_channel=source,
                target_channel=target
            )
            fixed_bots[source_key] = bot_instance
            loaded_count += 1
            
            logging.info(f"✅ تم تحميل بوت للمصدر: {source}")
            logging.info(f"   🎯 الهدف: {target}")
            
        except Exception as e:
            logging.error(f"❌ خطأ في تحميل بوت للمصدر {channel_info['source']}: {str(e)}")
    
    # تنظيف الأرقام المجربة القديمة
    cleanup_old_tested_numbers(30)
    
    logging.info(f"📊 تم تحميل {loaded_count} بوت للقنوات الثابتة")
    
    # عرض إحصائيات الأرقام
    stats = get_total_numbers_count()
    logging.info(f"📊 إحصائيات الأرقام: إجمالي={stats['total']}, بدون جلسة={stats['without_session']}, تم الوصول={stats['accessed']}, مجرب={stats['tested']}")
    
    # إرسال إشعار بعودة البوت للعمل إذا كان هناك بوتات
    if loaded_count > 0:
        send_start_notification()
    
    return loaded_count

# ==================== معالجات البوت العامة ====================

@bot.channel_post_handler(func=lambda message: True)
def handle_all_channel_posts(message):
    """توزيع الرسائل على جميع البوتات الثابتة"""
    for bot_instance in fixed_bots.values():
        try:
            bot_instance.handle_channel_post(message)
        except Exception as e:
            logging.error(f"❌ خطأ في معالجة رسالة: {e}")

@bot.edited_channel_post_handler(func=lambda message: True)
def handle_all_edited_posts(message):
    """توزيع التعديلات على جميع البوتات الثابتة"""
    for bot_instance in fixed_bots.values():
        try:
            bot_instance.handle_edited_channel_post(message)
        except Exception as e:
            logging.error(f"❌ خطأ في معالجة تعديل: {e}")

# ==================== معالج الضغط على الأزرار ====================

@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    """معالجة الضغط على الأزرار"""
    callback_data = call.data
    
    # تحميل حالات الأزرار
    button_states = load_button_states()
    
    if callback_data in button_states:
        button_info = button_states[callback_data]
        
        if button_info["status"] == "untested":
            
            # معلومات المختبر
            tester_info = {
                "id": call.from_user.id,
                "username": call.from_user.username,
                "first_name": call.from_user.first_name,
                "tested_at": datetime.now().isoformat()
            }
            
            # تسجيل الرقم في الفلتر
            source_message_id = button_info["source_message_id"]
            number_text = button_info.get("full_text") or button_info.get("number_text", "")
            source_key = button_info["source"]
            
            # البحث عن المصدر الأصلي
            source_channel = None
            for channel_info in FIXED_CHANNELS:
                if str(channel_info["source"]) == source_key:
                    source_channel = channel_info["source"]
                    break
            
            if source_channel:
                mark_number_as_tested(source_channel, source_message_id, number_text, tester_info)
            
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
                    chat_id=button_info["target"],
                    message_id=button_info["target_message_id"],
                    reply_markup=keyboard
                )
                
                bot.answer_callback_query(
                    call.id,
                    text="✅ تم حفظ الرقم في الفلتر - لن يتم إرساله مرة أخرى",
                    show_alert=False
                )
                
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
            for bot_instance in fixed_bots.values():
                if len(bot_instance.processed_messages) > 1000:
                    bot_instance.processed_messages = set(list(bot_instance.processed_messages)[-1000:])
            
            # تنظيف الأرقام المجربة القديمة مرة في اليوم
            if datetime.now().hour == 3 and datetime.now().minute == 0:
                cleanup_old_tested_numbers(30)
            
            # التحقق من أن البوت لا يزال يعمل
            if time.time() - last_heartbeat > heartbeat_interval:
                logging.warning("⚠️ البوت قد يكون متوقفاً، جاري إعادة التشغيل...")
                send_stop_notification()
                python = sys.executable
                os.execl(python, python, *sys.argv)
            
        except requests.exceptions.ConnectionError:
            logging.error("❌ خطأ في الاتصال بالإنترنت")
            time.sleep(10)
        except Exception as e:
            logging.error(f"❌ خطأ في مراقبة الصحة: {e}")
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
    print("🤖 TELEBOT FIXED CHANNELS SYSTEM WITH AUTO-RESTART")
    print("="*70)
    
    # معلومات البوت
    try:
        bot_info = bot.get_me()
        print(f"🔑 البوت: @{bot_info.username}")
    except:
        print("❌ فشل الاتصال بالبوت!")
        return
    
    print(f"🌐 Webhook URL: {WEBHOOK_URL or 'غير معرف'}")
    print(f"📡 القنوات الثابتة: {len(FIXED_CHANNELS)}")
    for i, ch in enumerate(FIXED_CHANNELS, 1):
        print(f"   {i}. مصدر: {ch['source']} -> هدف: {ch['target']}")
    print("🔄 إعادة تشغيل تلقائي عند الانقطاع")
    print("🔍 فلتر لمنع تكرار الأرقام المجربة")
    print("📊 إحصائيات تفصيلية للأرقام")
    print("📢 إشعارات تلقائية عند التوقف والعودة")
    print("="*70)
    
    # تحميل البوتات للقنوات الثابتة
    loaded_bots = load_fixed_bots()
    print(f"✅ تم تحميل {loaded_bots} بوت للقنوات الثابتة")
    
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
            
            # بدء مراقبة webhook
            monitor_thread = threading.Thread(target=verify_webhook, daemon=True)
            monitor_thread.start()
            
            # بدء مراقبة الصحة
            health_thread = threading.Thread(target=health_monitor, daemon=True)
            health_thread.start()
        else:
            print("❌ فشل تعيين Webhook!")
            return
    else:
        print("⚠️ RENDER_EXTERNAL_URL غير موجود، سيتم استخدام polling")
        
        def run_polling():
            try:
                bot.polling(non_stop=True, interval=2)
            except Exception as e:
                logging.error(f"❌ خطأ في polling: {e}")
                send_stop_notification()
        
        polling_thread = threading.Thread(target=run_polling, daemon=True)
        polling_thread.start()
    
    print("\n🚀 البوت يعمل الآن تلقائياً!")
    print("✅ القنوات الثابتة: مصدر 1 ← هدف 1")
    print("✅ القنوات الثابتة: مصدر 2 ← هدف 2") 
    print("✅ القنوات الثابتة: مصدر 3 ← هدف 3")
    print("📢 سيتم إشعارك عند توقف البوت وعودته للعمل")
    print("💾 جميع الإعدادات محفوظة ويتم استعادتها تلقائياً")
    print("="*70)
    
    # تشغيل Flask
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