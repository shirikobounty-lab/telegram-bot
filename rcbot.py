#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import telebot
import json
import os
import logging
import time
import re
from datetime import datetime
from pathlib import Path

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
        if chat_member.status == "creator":
            return True, "✅ البوت هو منشئ القناة!"
        
        elif chat_member.status == "administrator":
            # طريقة بديلة أبسط: التحقق من أن البوت مشرف
            # سنفترض أن كون البوت مشرفاً كافٍ لقراءة الرسائل
            return True, "✅ البوت مشرف في القناة المصدر"
        
        elif chat_member.status == "member":
            # إذا كان البوت عضواً فقط، نحتاج للتحقق بشكل مختلف
            try:
                # محاولة جلب معلومات القناة للتأكد من الوصول
                chat_info = bot.get_chat(channel_id)
                
                # إذا نجحنا في جلب معلومات القناة، البوت يمكنه قراءتها
                if chat_info:
                    return True, "✅ البوت عضو في القناة المصدر"
                else:
                    return False, "❌ البوت لا يستطيع قراءة الرسائل!\n\n" \
                                 "يجب أن يكون البوت مشرفاً أو لديه صلاحية عرض الرسائل."
            except:
                return False, "❌ البوت لا يستطيع قراءة الرسائل!\n\n" \
                             "يجب أن يكون البوت مشرفاً في القناة المصدر."
        
        else:
            return False, "❌ البوت ليس مشرفاً أو عضواً في القناة!\n\n" \
                         "أضف البوت إلى القناة كمشرف أولاً."
        
    except telebot.apihelper.ApiTelegramException as e:
        error_message = str(e)
        
        if "bot is not a member" in error_message.lower():
            return False, "❌ البوت ليس عضواً في القناة!\n\n" \
                         "أضف البوت إلى القناة أولاً."
        
        elif "user not found" in error_message.lower():
            return False, "❌ البوت ليس في القناة!\n\n" \
                         "أضف البوت إلى القناة كعضو أولاً."
        
        elif "not enough rights" in error_message.lower():
            return False, "❌ البوت ليس مشرفاً في القناة!\n\n" \
                         "يجب ترقية البوت كمشرف في القناة المصدر."
        
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
        
        elif "can't send messages" in error_message.lower():
            return False, "❌ البوت ممنوع من الكتابة في القناة!\n\n" \
                         "قم بإلغاء تقييد البوت في إعدادات القناة."
        
        elif "bot was kicked" in error_message.lower():
            return False, "❌ البوت مطرود من القناة!\n\n" \
                         "أضف البوت إلى القناة مرة أخرى."
        
        else:
            return False, f"❌ خطأ في التحقق من الكتابة: {error_message}"
    
    except Exception as e:
        return False, f"❌ خطأ غير متوقع: {str(e)}"

def convert_to_chat_id(channel_input):
    """تحويل المعرف إلى ID رقمي"""
    try:
        # إذا كان معرفاً رقمياً
        if isinstance(channel_input, int):
            return channel_input
        
        if isinstance(channel_input, str):
            channel_input = channel_input.strip()
            
            # إذا كان رقمياً
            if channel_input.lstrip('-').isdigit():
                return int(channel_input)
            
            # إذا كان @username
            elif channel_input.startswith('@'):
                try:
                    chat_info = bot.get_chat(channel_input)
                    return chat_info.id
                except:
                    return channel_input
        
        # إذا كان بالفعل ID
        return channel_input
    except:
        return channel_input

class UserBot:
    """كلاس يمثل بوت مستخدم واحد"""
    
    def __init__(self, user_id, source_channel, target_channel):
        self.user_id = user_id
        self.source_channel = convert_to_chat_id(source_channel)
        self.target_channel = convert_to_chat_id(target_channel)
        self.processed_messages = set()
        self.logger = setup_logging(user_id)
        
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
                
                # النوع 1: بدون جلسة (النسخة الأصلية)
                if '✅' in line and 'بدون جلسة' in line and 'لديه جلسة' not in line:
                    self.logger.info(f"✅ وجد النوع 1 (بدون جلسة)")
                    return True, 'type1'
                
                # النوع 2: تم الوصول (بعد التعديل) - ✅ قبل النص
                if '✅ تـم الـوصـول' in line or '✅ تم الوصول' in line:
                    self.logger.info(f"✅ وجد النوع 2 (✅ تـم الـوصـول)")
                    return True, 'type2'
        
        return False, None
    
    def handle_channel_post(self, message):
        """معالجة الرسائل الجديدة في القنوات"""
        try:
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
                # منع التكرار
                msg_id = f"{message.chat.id}_{message.message_id}"
                if msg_id in self.processed_messages:
                    self.logger.info(f"⏭️ تم معالجة هذه الرسالة مسبقاً")
                    return
                
                self.logger.info(f"🎯 الشرط متوفر - النوع: {msg_type}")
                
                try:
                    # إنشاء زر "غير مجرب" مع بيانات callback فريدة
                    callback_data = f"test_{self.user_id}_{message.message_id}"
                    
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
                        "timestamp": datetime.now().isoformat()
                    }
                    save_button_states(button_states)
                    
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
            if message.chat.id != self.source_channel:
                return
            
            text = message.text or message.caption
            
            if not text:
                return
            
            self.logger.info(f"✏️ نص معدل: {text[:100]}...")
            
            condition_met, msg_type = self.check_condition(text)
            
            if condition_met:
                msg_id = f"{message.chat.id}_{message.message_id}_edited"
                if msg_id in self.processed_messages:
                    return
                
                self.logger.info(f"🎯 التعديل يطابق الشرط - النوع: {msg_type}")
                
                try:
                    # إنشاء زر "غير مجرب" مع بيانات callback فريدة
                    callback_data = f"test_{self.user_id}_{message.message_id}"
                    
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
                        "timestamp": datetime.now().isoformat()
                    }
                    save_button_states(button_states)
                    
                    if msg_type == 'type2':
                        time.sleep(1)
                        bot.send_message(
                            chat_id=self.target_channel,
                            text="📢 الكود جاهز",
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

# قاموس لتخزين البوتات النشطة
active_bots = {}

def load_all_bots():
    """تحميل جميع البوتات النشطة"""
    config = load_config()
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
                print(f"✅ تم تحميل بوت المستخدم: {user_id}")
            except Exception as e:
                print(f"❌ خطأ في تحميل بوت {user_id}: {str(e)}")

# معالجات البوت العامة
@bot.channel_post_handler(func=lambda message: True)
def handle_all_channel_posts(message):
    """توزيع الرسائل على جميع البوتات النشطة"""
    for user_bot in active_bots.values():
        user_bot.handle_channel_post(message)

@bot.edited_channel_post_handler(func=lambda message: True)
def handle_all_edited_posts(message):
    """توزيع التعديلات على جميع البوتات النشطة"""
    for user_bot in active_bots.values():
        user_bot.handle_edited_channel_post(message)

# معالج الضغط على الأزرار
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
                    text="✅ مجرب",
                    callback_data=callback_data  # نفس الـ callback data
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
                    text="✅ تم تحديث الحالة إلى 'مجرب'",
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
                
            except Exception as e:
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

# أوامر البوت
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
                f"• '✅ الرقم بدون جلسة'\n"
                f"• '✅ تـم الـوصـول'\n"
                f"📤 سيتم إرسال كل رسالة مع زر تقييم\n"
                f"🔄 يمكن الضغط على الزر لتحديث الحالة إلى 'مجرب'"
            )
        except:
            pass
        
        bot.reply_to(message,
            f"✅ {validation_message}\n\n"
            f"🎉 **تم إنشاء البوت بنجاح!**\n\n"
            f"📊 **معلومات البوت:**\n"
            f"👤 **المستخدم:** `{user_id}`\n"
            f"📡 **المصدر:** `{source_channel}`\n"
            f"🎯 **الهدف:** `{target_channel}`\n\n"
            f"📁 **الملفات:**\n"
            f"• `logs/user_{user_id}.txt` - السجلات\n"
            f"• `data/user_{user_id}_*.txt` - البيانات\n\n"
            f"⚙️ **الأوامر:**\n"
            f"• `/status` - عرض الحالة\n"
            f"• `/edit` - تعديل الإعدادات\n"
            f"• `/stop` - إيقاف البوت\n\n"
            f"🔄 **ميزة التقييم:**\n"
            f"• كل رسالة يتم إرسالها مع زر (❌ غير مجرب)\n"
            f"• عند الضغط على الزر يتحول إلى (✅ مجرب)\n"
            f"• يتم تسجيل من قام بالتجربة ووقتها\n\n"
            f"🚀 **البوت يعمل الآن ويتم مراقبة القناة المصدر!**",
            parse_mode="Markdown"
        )
        
    except ValueError as e:
        bot.reply_to(message, f"❌ {str(e)}\n\nاستخدم /start للبدء من جديد")
    except Exception as e:
        bot.reply_to(message, f"❌ خطأ في إنشاء البوت: {str(e)}\n\nاستخدم /start للبدء من جديد")

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
            
            bot.reply_to(message,
                f"📊 **حالة البوت:**\n\n"
                f"✅ **البوت نشط**\n"
                f"👤 **المستخدم:** `{user_id}`\n"
                f"📡 **المصدر:** {source_name}\n"
                f"🎯 **الهدف:** {target_name}\n"
                f"📅 **الإنشاء:** {user_config['created_at'][:19]}\n"
                f"🔄 **آخر تحديث:** {user_config['last_updated'][:19]}\n\n"
                f"📊 **إحصائيات التقييم:**\n"
                f"• إجمالي الرسائل: {total_buttons}\n"
                f"• ✅ مجرب: {tested_buttons}\n"
                f"• ❌ غير مجرب: {untested_buttons}\n\n"
                f"📁 **الملفات:**\n"
                f"• `logs/user_{user_id}.txt` - السجلات\n"
                f"• `data/user_{user_id}_*.txt` - البيانات\n\n"
                f"⚙️ **الأوامر:**\n"
                f"• `/edit` - تعديل الإعدادات\n"
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
    
    if user_id in active_bots:
        button_states = load_button_states()
        user_buttons = [b for b in button_states.values() if b["user_id"] == user_id]
        
        if not user_buttons:
            bot.reply_to(message, "📊 لا توجد رسائل مرسلة بعد")
            return
        
        total = len(user_buttons)
        tested = len([b for b in user_buttons if b["status"] == "tested"])
        untested = total - tested
        
        # آخر 5 رسائل مجربة
        tested_list = [b for b in user_buttons if b["status"] == "tested"]
        recent_tested = sorted(tested_list, key=lambda x: x.get("tested_at", ""), reverse=True)[:5]
        
        stats_text = f"📊 **إحصائيات التقييم**\n\n"
        stats_text += f"📈 **الإجمالي:** {total} رسالة\n"
        stats_text += f"✅ **مجرب:** {tested}\n"
        stats_text += f"❌ **غير مجرب:** {untested}\n"
        stats_text += f"📊 **نسبة التجريب:** {(tested/total*100):.1f}%\n\n"
        
        if recent_tested:
            stats_text += "🕒 **آخر 5 تجارب:**\n"
            for r in recent_tested:
                tested_time = r.get("tested_at", "")[11:19] if r.get("tested_at") else "غير معروف"
                tester = r.get("tester_username", "مجهول")
                stats_text += f"• {tested_time} - بواسطة @{tester}\n"
        
        bot.reply_to(message, stats_text, parse_mode="Markdown")
    else:
        bot.reply_to(message, "⚠️ ليس لديك بوت نشط")

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
                f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
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
/stats - عرض إحصائيات التقييم
/edit - تعديل إعدادات القنوات
/stop - إيقاف البوت الخاص بك
/help - عرض هذه الرسالة

📝 **متطلبات القنوات:**

**قناة المصدر:**
✅ البوت يجب أن يكون مشرفاً أو عضواً على الأقل
✅ يجب أن يستطيع البوت قراءة الرسائل
✅ يمكن أن تكون معرف رقمي (-100...) أو نصي (@...)

**قناة الهدف:**
✅ البوت يجب أن يستطيع الكتابة
✅ يمكن أن تكون معرف رقمي (-100...) أو نصي (@...)

🔄 **ميزة التقييم:**
• كل رسالة يتم إرسالها مع زر (❌ غير مجرب) أسفلها
• عند الضغط على الزر يتحول إلى (✅ مجرب)
• يتم تسجيل من قام بالتجربة ووقتها
• لا يمكن تغيير الحالة بعد التجريب
• يمكن عرض الإحصائيات باستخدام /stats

🔄 **عملية التعديل (/edit):**
1. اختر ما تريد تعديله
2. أرسل المعرف الجديد
3. يتم التحقق من الصلاحيات تلقائياً
4. يتم التطبيق بعد التأكيد

📊 **ملاحظات:**
• كل مستخدم له بوت خاص به
• الإعدادات لا تتداخل بين المستخدمين
• يمكن تعديل الإعدادات في أي وقت
• السجلات والبيانات منفصلة لكل مستخدم
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

def main():
    """الدالة الرئيسية"""
    print("="*70)
    print("🤖 TELEBOT MULTI-USER SYSTEM WITH RATING BUTTONS")
    print("="*70)
    print(f"🔑 البوت: @{bot.get_me().username}")
    print("👥 يدعم عدة مستخدمين")
    print("🔍 يتحقق من صحة القنوات تلقائياً")
    print("🔄 يدعم تعديل الإعدادات")
    print("✅ يدعم أزرار التقييم (غير مجرب ➜ مجرب)")
    print("📁 كل مستخدم له ملفاته المنفصلة")
    print("="*70)
    
    # تحميل البوتات النشطة
    load_all_bots()
    print(f"✅ تم تحميل {len(active_bots)} بوت نشط")
    
    print("\n🚀 البوت يعمل الآن!")
    print("👤 أرسل /start لإنشاء بوت جديد")
    print("📊 أرسل /status للتحقق من حالة بوتك")
    print("📈 أرسل /stats لعرض إحصائيات التقييم")
    print("🔄 أرسل /edit لتعديل إعدادات قنواتك")
    print("🛑 أرسل /stop لإيقاف بوتك")
    print("="*70)
    
    # بدء البوت
    try:
        bot.polling(non_stop=True, interval=2)
    except KeyboardInterrupt:
        print("\n⏹️ تم إيقاف البوت")
    except Exception as e:
        print(f"💥 خطأ: {e}")

if __name__ == '__main__':
    main()