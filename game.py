import telebot
from telebot import types
import random
import time
from collections import Counter
import threading
from keep_alive import keep_alive

# ---------- تنظیمات ----------
TOKEN = "7820797572:AAEjFbNe9Tzb9fPtcudAErA7Wm0yzZLd8hs"
ADMIN_CODE = "1233456"

# ---------- اتصال ----------
bot = telebot.TeleBot(TOKEN)

# ---------- متغیرهای حافظه ----------
user_states = {}
admins = set()
player_confirmations = set()
votes = {}
vote_start_time = None
vote_duration = 0
eliminated_players = set()
game_active = False

# دیکشنری‌های جدید برای جایگزینی فایل‌ها
game_settings = {}
users_with_roles = {}
vote_records = []

# لیست نام‌های کاربری که قبلاً استفاده شده‌اند
used_usernames = set()

# ---------- متغیرهای مدیریت تایمر ----------
countdown_active = False
voting_timer_active = False

# ---------- هندلرهای مسدود کردن مدیا ----------
@bot.message_handler(content_types=['photo', 'video', 'voice', 'audio', 'document', 'sticker'])
def handle_blocked_media(message):
    chat_id = message.chat.id
    bot.reply_to(message, "⚠️ این ربات فقط از پیام‌های متنی پشتیبانی می‌کند.")
    if chat_id in user_states and user_states[chat_id] in ['waiting_for_username', 'voting']:
        show_main_menu(message)

# ---------- توابع بازی ----------
def stop_all_timers():
    """متوقف کردن تمام تایمرهای فعال"""
    global countdown_active, voting_timer_active
    countdown_active = False
    voting_timer_active = False

def reset_game():
    global player_confirmations, votes, vote_start_time, eliminated_players, game_active, user_states
    global game_settings, users_with_roles, vote_records, used_usernames
    
    # متوقف کردن تایمرها
    stop_all_timers()
    
    # ریست تمام متغیرهای گلوبال
    player_confirmations = set()
    votes = {}
    vote_start_time = None
    eliminated_players = set()
    game_active = False
    game_settings = {}
    users_with_roles = {}
    vote_records = []
    used_usernames = set()
    
    # ریست وضعیت کاربران (به جز ادمین‌ها)
    users_to_remove = []
    for user_id, state in user_states.items():
        if user_id not in admins and not str(user_id).endswith('_username'):
            users_to_remove.append(user_id)
    
    for user_id in users_to_remove:
        del user_states[user_id]

def reset_game_completely():
    """ریست کامل بازی برای شروع جدید"""
    global player_confirmations, votes, vote_start_time, eliminated_players, game_active, user_states, admins
    global game_settings, users_with_roles, vote_records, used_usernames
    
    # متوقف کردن تایمرها
    stop_all_timers()
    
    player_confirmations = set()
    votes = {}
    vote_start_time = None
    eliminated_players = set()
    game_active = False
    game_settings = {}
    users_with_roles = {}
    vote_records = []
    used_usernames = set()
    
    # حفظ ادمین‌ها اما ریست وضعیت آن‌ها
    admin_users = set(admins)
    user_states.clear()
    admins.clear()
    
    # بازگرداندن ادمین‌ها
    for admin_id in admin_users:
        admins.add(admin_id)
        user_states[admin_id] = 'admin'

def get_total_players():
    return len(users_with_roles)

def get_player_role(username):
    return users_with_roles.get(username)

def get_vote_time():
    return game_settings.get('vote_time', 0)

def get_role_counts():
    citizen_count = 0
    mafia_count = 0
    
    for username, role in users_with_roles.items():
        if username not in eliminated_players:
            if role == 'شهروند':
                citizen_count += 1
            elif role == 'مافیا':
                mafia_count += 1
    return citizen_count, mafia_count

def check_game_end():
    citizen_count, mafia_count = get_role_counts()
    total_remaining = citizen_count + mafia_count
    
    # اگر تمام مافیا حذف شوند، شهروندان برنده می‌شوند
    if mafia_count == 0 and citizen_count > 0:
        return "شهروندان"
    
    # اگر تعداد مافیا بیشتر یا مساوی شهروندان شود، مافیا برنده می‌شود
    if mafia_count >= citizen_count and mafia_count > 0:
        return "مافیا"
    
    # اگر فقط 2 بازیکن باقی مانده باشد و یکی مافیا باشد
    if total_remaining == 2 and mafia_count == 1:
        return "مافیا"
    
    # اگر فقط یک بازیکن باقی مانده باشد
    if total_remaining == 1:
        role = None
        for username in users_with_roles:
            if username not in eliminated_players:
                role = users_with_roles[username]
                break
        return "مافیا" if role == "مافیا" else "شهروندان"
    
    return None

def check_all_voted():
    active_players = set()
    
    for username in users_with_roles.keys():
        if username not in eliminated_players:
            active_players.add(username)
    
    return len(votes) == len(active_players)

def get_vote_results():
    """نمایش نتایج رای‌گیری با فلش برعکس"""
    if not votes:
        return "هیچ رایی ثبت نشده است."
    
    vote_counts = Counter(votes.values())
    result = "📊 **نتایج نهایی رای‌گیری:**\n\n"
    
    # نمایش تعداد آراء هر نفر (مرتب شده)
    sorted_results = vote_counts.most_common()
    for player, count in sorted_results:
        result += f"🎯 **{player}**: {count} رای\n"
    
    # نمایش جزئیات رای‌ها با فلش برعکس
    result += "\n🔀 **جزئیات رای‌ها:**\n"
    
    # گروه‌بندی رای‌ها بر اساس هدف
    votes_by_target = {}
    for voter, target in votes.items():
        if target not in votes_by_target:
            votes_by_target[target] = []
        votes_by_target[target].append(voter)
    
    # نمایش بر اساس بیشترین رای
    for target, voters in sorted(votes_by_target.items(), 
                               key=lambda x: len(x[1]), 
                               reverse=True):
        voters_list = "، ".join(voters)
        result += f"• {target} ⟵ {voters_list}\n"
    
    return result

def start_countdown_timer():
    """شروع شمارش معکوس برای اطلاع رسانی 30 ثانیه پایانی"""
    global vote_duration, countdown_active
    
    def countdown():
        global countdown_active
        countdown_active = True
        remaining_time = vote_duration * 60
        
        while remaining_time > 0 and game_active and countdown_active:
            time.sleep(1)
            remaining_time -= 1
            
            # فقط زمانی که 30 ثانیه یا کمتر مانده اطلاع بده
            if remaining_time <= 30:
                minutes = remaining_time // 60
                seconds = remaining_time % 60
                
                for user_id, state in user_states.items():
                    username = user_states.get(f"{user_id}_username")
                    if username and username not in eliminated_players and state == 'voting':
                        try:
                            time_text = f"⏰ **{minutes}:{seconds:02d}**"
                            
                            bot.send_message(
                                user_id, 
                                f"{time_text}\n\n"
                                f"⚠️ فقط {remaining_time} ثانیه تا پایان رای‌گیری باقی مانده!"
                            )
                        except Exception as e:
                            print(f"خطا در ارسال اطلاع زمان: {e}")
                
                # بعد از ارسال پیام 30 ثانیه، از حلقه خارج شو
                break
        
        countdown_active = False
    
    # متوقف کردن تایمر قبلی
    countdown_active = False
    time.sleep(0.1)  # فرصت برای توقف تایمر قبلی
    
    # شروع تایمر جدید
    countdown_thread = threading.Thread(target=countdown)
    countdown_thread.daemon = True
    countdown_thread.start()

def end_voting():
    global votes, eliminated_players, game_active
    
    # متوقف کردن تایمرها قبل از پایان رای‌گیری
    stop_all_timers()
    
    all_players = set(users_with_roles.keys())
    
    for player in all_players:
        if player not in votes and player not in eliminated_players:
            votes[player] = player
    
    vote_counts = Counter(votes.values())
    
    if vote_counts:
        max_votes = max(vote_counts.values())
        players_with_max_votes = [player for player, count in vote_counts.items() if count == max_votes]
        
        if len(players_with_max_votes) > 1:
            citizen_count, mafia_count = get_role_counts()
            
            # نمایش نتایج نهایی رای‌گیری
            final_results = get_vote_results()
            
            for user_id, state in user_states.items():
                username = user_states.get(f"{user_id}_username")
                if username and state != 'eliminated' and state != 'game_ended':
                    tied_players = "، ".join(players_with_max_votes)
                    bot.send_message(user_id, 
                                   f"⚖️ **تساوی در رای‌گیری!**\n\n"
                                   f"🎯 بازیکنان با بیشترین رای:\n**{tied_players}**\n"
                                   f"📊 تعداد رای هرکدام: **{max_votes}**\n\n"
                                   f"{final_results}\n"
                                   f"👥 آمار فعلی:\n"
                                   f"🏘️ شهروند: **{citizen_count} نفر**\n"
                                   f"🔪 مافیا: **{mafia_count} نفر**\n"
                                   f"🎮 کل بازیکنان: **{citizen_count + mafia_count} نفر**\n\n"
                                   f"⏰ **دور جدید رای‌گیری شروع شد!**\n"
                                   f"🕒 زمان: **{vote_duration} دقیقه**\n\n"
                                   f"لطفاً نام کاربری مورد نظر برای رای را ارسال کنید:")
            
            start_new_voting_round()
            
        else:
            eliminated_player = players_with_max_votes[0]
            eliminated_players.add(eliminated_player)
            eliminated_role = get_player_role(eliminated_player)
            
            # نمایش نتایج نهایی رای‌گیری
            final_results = get_vote_results()
            
            # حذف بازیکن از بازی
            for user_id, state in user_states.items():
                if user_states.get(f"{user_id}_username") == eliminated_player:
                    bot.send_message(user_id, 
                                   "❌ **شما از بازی خارج شدید!**\n\n"
                                   "💡 برای ورود مجدد باید با نام کاربری جدید وارد شوید.")
                    user_states[user_id] = 'eliminated'
                    # حذف نام کاربری از لیست استفاده شده برای اجازه ورود مجدد
                    if eliminated_player in used_usernames:
                        used_usernames.remove(eliminated_player)
                    break
            
            # چک کردن پایان بازی بعد از حذف بازیکن
            winner = check_game_end()
            if winner:
                end_game(winner)
                return eliminated_player
            
            citizen_count, mafia_count = get_role_counts()
            
            # اطلاع‌رسانی به همه بازیکنان فعال
            for user_id, state in user_states.items():
                username = user_states.get(f"{user_id}_username")
                if username and username != eliminated_player and state != 'eliminated' and state != 'game_ended':
                    bot.send_message(user_id, 
                                   f"🎯 **دور جدید شروع شد!**\n\n"
                                   f"🔴 بازیکن حذف شده: **{eliminated_player}** ({eliminated_role})\n\n"
                                   f"{final_results}\n"
                                   f"👥 آمار فعلی:\n"
                                   f"🏘️ شهروند: **{citizen_count} نفر**\n"
                                   f"🔪 مافیا: **{mafia_count} نفر**\n"
                                   f"🎮 کل بازیکنان: **{citizen_count + mafia_count} نفر**\n\n"
                                   f"⏰ زمان رای‌گیری: **{vote_duration} دقیقه**\n\n"
                                   f"لطفاً نام کاربری مورد نظر برای رای را ارسال کنید:")
            
            start_new_voting_round()
            return eliminated_player
    
    return None

def end_game(winner):
    global game_active
    game_active = False
    
    # متوقف کردن تمام تایمرها
    stop_all_timers()
    
    citizen_count, mafia_count = get_role_counts()
    total_players = citizen_count + mafia_count
    
    # نمایش نقش تمام بازیکنان در پایان بازی
    roles_info = "🎭 **نقش تمام بازیکنان:**\n\n"
    for username, role in users_with_roles.items():
        status = "🔴 حذف شده" if username in eliminated_players else "🟢 فعال"
        roles_info += f"• **{username}**: {role} ({status})\n"
    
    if winner == "شهروندان":
        message = ("🎉 **شهروندان برنده شدند!** 🎉\n\n"
                  "🏘️ تمام مافیای ها حذف شدند و شهر در امان ماند!")
    else:
        message = ("🔪 **مافیا برنده شد!** 🔪\n\n"
                  "🌃 مافیای ها کنترل شهر را به دست گرفتند!")
    
    message += f"\n\n📊 **آمار نهایی:**\n🏘️ شهروند: **{citizen_count} نفر**\n🔪 مافیا: **{mafia_count} نفر**\n🎮 کل بازیکنان فعال: **{total_players} نفر**"
    message += f"\n\n{roles_info}"
    
    for user_id, state in user_states.items():
        username = user_states.get(f"{user_id}_username")
        if username:
            bot.send_message(user_id, message)
            user_states[user_id] = 'game_ended'
    
    # نمایش پیام نهایی به ادمین
    for admin_id in admins:
        try:
            bot.send_message(admin_id, 
                           f"🏁 **بازی به پایان رسید!**\n\n"
                           f"🏆 برنده: **{winner}**\n\n"
                           f"{message}")
        except:
            pass

def voting_timer():
    """تایمر اصلی رای‌گیری"""
    global voting_timer_active
    voting_timer_active = True
    
    time.sleep(vote_duration * 60)
    
    if game_active and voting_timer_active:
        eliminated_player = end_voting()
        if eliminated_player:
            print(f"بازیکن {eliminated_player} حذف شد")
    
    voting_timer_active = False

def start_new_voting_round():
    global votes, vote_start_time
    
    # متوقف کردن تایمرهای قبلی
    stop_all_timers()
    time.sleep(0.1)  # فرصت برای توقف تایمرهای قبلی
    
    votes = {}
    vote_start_time = time.time()
    
    # شروع تایمر اصلی رای‌گیری
    timer_thread = threading.Thread(target=voting_timer)
    timer_thread.daemon = True
    timer_thread.start()
    
    # شروع شمارش معکوس برای اطلاع رسانی 30 ثانیه پایانی
    start_countdown_timer()
    
    for user_id, state in user_states.items():
        username = user_states.get(f"{user_id}_username")
        if username and username not in eliminated_players and state != 'eliminated' and state != 'game_ended':
            user_states[user_id] = 'voting'
            bot.send_message(user_id, 
                           f"🎯 **رای‌گیری شروع شد!**\n\n"
                           f"⏰ زمان رای‌گیری: **{vote_duration} دقیقه**\n\n"
                           f"💡 پس از پایان زمان، نتایج رای‌گیری اعلام خواهد شد.\n\n"
                           f"لطفاً نام کاربری مورد نظر برای رای را ارسال کنید:",
                           parse_mode='Markdown')

def end_voting_early():
    """پایان دادن زودهنگام به رای‌گیری"""
    time.sleep(1)
    if game_active:
        eliminated_player = end_voting()
        if eliminated_player:
            print(f"بازیکن {eliminated_player} حذف شد (رای‌گیری زودتر پایان یافت)")

# ---------- شروع ----------
def show_main_menu(message):
    chat_id = message.chat.id
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🎮 ورود به بازی", "👨‍💼 پنل ادمین")
    bot.send_message(
        chat_id,
        "🤖 **به بازی مافیا خوش آمدید!**\n\n"
        "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
        reply_markup=markup,
        parse_mode='Markdown'
    )
    bot.register_next_step_handler_by_chat_id(chat_id, handle_main_menu_choice)

@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = message.chat.id
    bot.clear_step_handler_by_chat_id(chat_id)
    time.sleep(0.5)
    show_main_menu(message)

def handle_main_menu_choice(message):
    chat_id = message.chat.id
    bot.clear_step_handler_by_chat_id(chat_id)
    
    if message.content_type != 'text':
        handle_blocked_media(message)
        return show_main_menu(message)
        
    text = message.text.strip()
    
    if text == "🎮 ورود به بازی":
        user_states[chat_id] = 'waiting_for_username'
        bot.send_message(chat_id, 
                        "🎮 **ورود به بازی**\n\n"
                        "🔑 لطفاً نام کاربری خود را وارد کنید:")
    elif text == "👨‍💼 پنل ادمین":
        user_states[chat_id] = 'waiting_for_code'
        bot.send_message(chat_id, "👨‍💼 برای ورود به پنل ادمین، کد را وارد کنید:")
    else:
        bot.send_message(chat_id, "❌ گزینه معتبر نیست.")
        show_main_menu(message)

# ---------- بررسی کد ادمین ----------
@bot.message_handler(func=lambda message: user_states.get(message.from_user.id) == 'waiting_for_code')
def check_admin_code(message):
    user_id = message.from_user.id
    bot.clear_step_handler_by_chat_id(user_id)
    
    if message.content_type != 'text':
        handle_blocked_media(message)
        return show_main_menu(message)
        
    if message.text == ADMIN_CODE:
        admins.add(user_id)
        user_states[user_id] = 'admin'
        show_admin_panel(message)
    else:
        bot.send_message(user_id, "❌ کد نامعتبر است.")
        show_main_menu(message)

# ---------- بررسی نام کاربری ----------
@bot.message_handler(func=lambda message: user_states.get(message.from_user.id) == 'waiting_for_username')
def check_username(message):
    user_id = message.from_user.id
    bot.clear_step_handler_by_chat_id(user_id)
    
    if message.content_type != 'text':
        handle_blocked_media(message)
        return show_main_menu(message)
        
    username = message.text.strip()
    
    # بررسی اینکه نام کاربری قبلاً استفاده شده
    if username in used_usernames:
        bot.send_message(user_id, "❌ **این نام کاربری قبلاً استفاده شده است!**\n\nلطفاً نام کاربری دیگری انتخاب کنید:")
        return
    
    if username in eliminated_players:
        bot.send_message(user_id, "❌ این نام کاربری حذف شده است. لطفاً نام کاربری دیگری انتخاب کنید.")
        return
    
    role = get_player_role(username)
    if role:
        # علامت گذاری نام کاربری به عنوان استفاده شده
        used_usernames.add(username)
        
        # ارسال پیام نقش و ذخیره message_id برای حذف بعدی
        role_message = bot.send_message(user_id, 
                                      f"🎭 **نقش شما: {role}**\n\n"
                                      "⏳ این پیام در 5 ثانیه حذف خواهد شد...")
        
        # ایجاد ترد برای حذف پیام بعد از 5 ثانیه
        delete_thread = threading.Thread(target=delete_role_message, args=(user_id, role_message.message_id))
        delete_thread.daemon = True
        delete_thread.start()
        
        user_states[user_id] = 'player_confirmed'
        user_states[f"{user_id}_username"] = username
        user_states[f"{user_id}_role"] = role
        
        # ثبت خودکار تایید کاربر
        if username not in player_confirmations:
            player_confirmations.add(username)
            total_players = get_total_players()
            confirmed_count = len(player_confirmations)
            
            # ارسال پیام تایید آمادگی بعد از حذف پیام نقش
            time.sleep(5)
            bot.send_message(user_id, 
                           f"✅ **آمادگی شما به طور خودکار ثبت شد!**\n\n"
                           f"📊 تأیید شده‌ها: **{confirmed_count}/{total_players}**\n\n"
                           f"⏳ منتظر تأیید سایر بازیکنان باشید...")
            
            # اگر همه تایید کردند، بازی شروع شود
            if confirmed_count == total_players:
                start_voting()
    else:
        bot.send_message(user_id, "❌ نام کاربری نامعتبر است. لطفاً دوباره تلاش کنید.")
        show_main_menu(message)

def delete_role_message(chat_id, message_id):
    """حذف پیام نقش بعد از 5 ثانیه"""
    time.sleep(5)
    try:
        bot.delete_message(chat_id, message_id)
    except Exception as e:
        print(f"خطا در حذف پیام: {e}")

def start_voting():
    global vote_start_time, game_active
    vote_start_time = time.time()
    game_active = True
    
    # متوقف کردن تایمرهای قبلی (در صورت وجود)
    stop_all_timers()
    time.sleep(0.1)
    
    timer_thread = threading.Thread(target=voting_timer)
    timer_thread.daemon = True
    timer_thread.start()
    
    # شروع تایمر برای اطلاع رسانی 30 ثانیه پایانی
    start_countdown_timer()
    
    for user_id, state in user_states.items():
        if state == 'player_confirmed':
            username = user_states.get(f"{user_id}_username")
            if username:
                bot.send_message(user_id, 
                               f"🎯 **بازی شروع شد!**\n\n"
                               f"⏰ زمان رای‌گیری: **{vote_duration} دقیقه**\n\n"
                               f"💡 پس از پایان زمان، نتایج رای‌گیری اعلام خواهد شد.\n\n"
                               f"لطفاً نام کاربری مورد نظر برای رای را ارسال کنید:",
                               parse_mode='Markdown')
                user_states[user_id] = 'voting'

# ---------- دریافت رای ----------
@bot.message_handler(func=lambda message: user_states.get(message.from_user.id) == 'voting')
def receive_vote(message):
    user_id = message.from_user.id
    bot.clear_step_handler_by_chat_id(user_id)
    
    if message.content_type != 'text':
        handle_blocked_media(message)
        return
    
    voter_username = user_states.get(f"{user_id}_username")
    target_username = message.text.strip()
    
    if not game_active:
        bot.send_message(user_id, "⏹️ **بازی به پایان رسیده!**")
        return
    
    if time.time() - vote_start_time > vote_duration * 60:
        bot.send_message(user_id, "⏰ **زمان رای‌گیری به پایان رسیده!**")
        return
    
    if voter_username in votes:
        bot.send_message(user_id, "❌ **شما قبلاً رای داده‌اید!**")
        return
    
    if not get_player_role(target_username):
        bot.send_message(user_id, "❌ **نام کاربری نامعتبر است!**")
        return
    
    if target_username in eliminated_players:
        bot.send_message(user_id, "❌ **این بازیکن قبلاً حذف شده است!**")
        return
    
    votes[voter_username] = target_username
    
    # ذخیره رای در لیست به جای فایل
    vote_records.append(f"{voter_username} -> {target_username}")
    
    # فقط تأیید رای بدون نمایش نتایج
    bot.send_message(user_id, f"✅ **رای شما برای {target_username} ثبت شد!**")
    
    if check_all_voted():
        for user_id, state in user_states.items():
            if state == 'voting':
                bot.send_message(user_id, "🎯 **همه بازیکنان رای دادند! رای‌گیری زودتر پایان یافت.**")
        
        threading.Thread(target=end_voting_early, daemon=True).start()

# ---------- پنل ادمین ----------
def show_admin_panel(message):
    chat_id = message.chat.id
    bot.clear_step_handler_by_chat_id(chat_id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add('➕ شروع بازی جدید')
    markup.add('🔄 ریست بازی', '📊 وضعیت بازی')
    markup.add('🏠 بازگشت به منوی اصلی')
    bot.send_message(chat_id, 
                    "👨‍💼 **پنل ادمین**\n\n"
                    "گزینه مورد نظر را انتخاب کنید:",
                    reply_markup=markup,
                    parse_mode='Markdown')
    bot.register_next_step_handler_by_chat_id(chat_id, handle_admin_choice)

def handle_admin_choice(message):
    chat_id = message.chat.id
    bot.clear_step_handler_by_chat_id(chat_id)
    
    if message.content_type != 'text':
        handle_blocked_media(message)
        return show_admin_panel(message)

    text = message.text.strip()
    
    if text == '➕ شروع بازی جدید':
        user_states[chat_id] = 'admin_enter_usernames'
        user_states[f"{chat_id}_usernames"] = []
        bot.send_message(chat_id, 
                        "📝 **شروع بازی جدید**\n\n"
                        "لطفاً نام کاربری بازیکنان را یکی یکی وارد کنید.\n"
                        "⏹️ پس از وارد کردن همه نام‌ها، کلمه 'پایان' را ارسال کنید.\n\n"
                        "🔸 نام کاربری اول را وارد کنید:",
                        parse_mode='Markdown')
    elif text == '🔄 ریست بازی':
        reset_game_completely()
        bot.send_message(chat_id, 
                        "✅ **بازی با موفقیت ریست شد!**\n\n"
                        "🗑️ تمام اطلاعات پاک شد.\n\n"
                        "🔄 برای شروع جدید از منوی ادمین استفاده کنید.",
                        parse_mode='Markdown')
        show_admin_panel(message)
    elif text == '📊 وضعیت بازی':
        if game_active:
            citizen_count, mafia_count = get_role_counts()
            total_confirmed = len(player_confirmations)
            total_players = get_total_players()
            
            status_msg = (
                f"🎮 **وضعیت بازی**\n\n"
                f"🟢 بازی فعال\n"
                f"👥 بازیکنان: **{total_players}**\n"
                f"✅ تأیید شده: **{total_confirmed}**\n"
                f"🏘️ شهروند: **{citizen_count}**\n"
                f"🔪 مافیا: **{mafia_count}**\n"
                f"⏰ زمان رای: **{vote_duration} دقیقه**\n"
                f"🗳️ رای‌های ثبت شده: **{len(votes)}/{total_players - len(eliminated_players)}**"
            )
        else:
            status_msg = "🔴 **هیچ بازی فعالی وجود ندارد**"
        
        bot.send_message(chat_id, status_msg, parse_mode='Markdown')
        show_admin_panel(message)
    elif text == '🏠 بازگشت به منوی اصلی':
        show_main_menu(message)
    else:
        bot.send_message(chat_id, "❌ گزینه معتبر نیست.")
        show_admin_panel(message)

# ---------- ثبت نام کاربری‌ها توسط ادمین ----------
@bot.message_handler(func=lambda message: user_states.get(message.from_user.id) == 'admin_enter_usernames')
def get_usernames(message):
    user_id = message.from_user.id
    bot.clear_step_handler_by_chat_id(user_id)
    
    if message.content_type != 'text':
        handle_blocked_media(message)
        return show_admin_panel(message)
    
    if message.text.lower() == 'پایان':
        usernames = user_states.get(f"{user_id}_usernames", [])
        if len(usernames) < 2:
            bot.send_message(user_id, "❌ حداقل ۲ بازیکن نیاز است. لطفاً نام کاربری‌های بیشتری وارد کنید:")
            return
        
        user_states[user_id] = 'admin_question1'
        user_states[f"{user_id}_total_players"] = len(usernames)
        bot.send_message(user_id, 
                        f"✅ **{len(usernames)} نام کاربری ثبت شد.**\n\n"
                        f"🏘️ تعداد بازیکنان شهروند را وارد کنید (حداکثر {len(usernames)-1}):",
                        parse_mode='Markdown')
        return
    
    username = message.text.strip()
    
    if not username:
        bot.send_message(user_id, "❌ نام کاربری نمی‌تواند خالی باشد. لطفاً مجدداً وارد کنید:")
        return
    
    if f"{user_id}_usernames" not in user_states:
        user_states[f"{user_id}_usernames"] = []
    
    if username in user_states[f"{user_id}_usernames"]:
        bot.send_message(user_id, "❌ این نام کاربری قبلاً وارد شده. لطفاً نام کاربری دیگری وارد کنید:")
        return
    
    user_states[f"{user_id}_usernames"].append(username)
    count = len(user_states[f"{user_id}_usernames"])
    
    bot.send_message(user_id, 
                    f"✅ نام کاربری **{username}** ثبت شد.\n"
                    f"📊 تعداد تاکنون: **{count}**\n\n"
                    "🔸 نام کاربری بعدی را وارد کنید یا 'پایان' را ارسال کنید:",
                    parse_mode='Markdown')

@bot.message_handler(func=lambda message: user_states.get(message.from_user.id) == 'admin_question1')
def get_citizen_count(message):
    user_id = message.from_user.id
    bot.clear_step_handler_by_chat_id(user_id)
    
    if message.content_type != 'text':
        handle_blocked_media(message)
        return show_admin_panel(message)
        
    if not message.text.isdigit():
        bot.send_message(user_id, "❌ لطفا یک عدد وارد کنید:")
        return
    
    total_players = user_states.get(f"{user_id}_total_players")
    citizen_count = int(message.text)
    
    if citizen_count < 1:
        bot.send_message(user_id, "❌ حداقل ۱ شهروند نیاز است. لطفاً مجدداً وارد کنید:")
        return
    
    if citizen_count >= total_players:
        bot.send_message(user_id, f"❌ تعداد شهروندان باید کمتر از کل بازیکنان ({total_players}) باشد. لطفاً مجدداً وارد کنید:")
        return
    
    user_states[user_id] = 'admin_question2'
    user_states[f"{user_id}_citizen"] = citizen_count
    
    mafia_max = total_players - citizen_count
    bot.send_message(user_id, 
                    f"🔪 تعداد بازیکنان مافیا را وارد کنید (حداکثر {mafia_max}):")

@bot.message_handler(func=lambda message: user_states.get(message.from_user.id) == 'admin_question2')
def get_mafia_count(message):
    user_id = message.from_user.id
    bot.clear_step_handler_by_chat_id(user_id)
    
    if message.content_type != 'text':
        handle_blocked_media(message)
        return show_admin_panel(message)
        
    if not message.text.isdigit():
        bot.send_message(user_id, "❌ لطفا یک عدد وارد کنید:")
        return
    
    total_players = user_states.get(f"{user_id}_total_players")
    citizen_count = user_states.get(f"{user_id}_citizen")
    mafia_count = int(message.text)
    mafia_max = total_players - citizen_count
    
    if mafia_count < 1:
        bot.send_message(user_id, "❌ حداقل ۱ مافیا نیاز است. لطفاً مجدداً وارد کنید:")
        return
    
    if mafia_count > mafia_max:
        bot.send_message(user_id, f"❌ تعداد مافیا نمی‌تواند بیشتر از {mafia_max} باشد. لطفاً مجدداً وارد کنید:")
        return
    
    user_states[user_id] = 'admin_question3'
    user_states[f"{user_id}_mafia"] = mafia_count
    
    bot.send_message(user_id, "⏰ زمان دورهای رای گیری (دقیقه) را وارد کنید:")

@bot.message_handler(func=lambda message: user_states.get(message.from_user.id) == 'admin_question3')
def get_vote_time_admin(message):
    user_id = message.from_user.id
    bot.clear_step_handler_by_chat_id(user_id)
    
    if message.content_type != 'text':
        handle_blocked_media(message)
        return show_admin_panel(message)
        
    if message.text.isdigit():
        citizen_count = user_states.get(f"{user_id}_citizen")
        mafia_count = user_states.get(f"{user_id}_mafia")
        total_players = user_states.get(f"{user_id}_total_players")
        usernames = user_states.get(f"{user_id}_usernames")
        vote_time = message.text
        
        global vote_duration, game_active
        vote_duration = int(vote_time)
        game_active = True
        
        roles = ['شهروند'] * citizen_count + ['مافیا'] * mafia_count
        random.shuffle(roles)
        
        # ذخیره در دیکشنری به جای فایل
        for username, role in zip(usernames, roles):
            users_with_roles[username] = role
        
        # ذخیره تنظیمات در دیکشنری
        game_settings['citizen_count'] = citizen_count
        game_settings['mafia_count'] = mafia_count
        game_settings['vote_time'] = int(vote_time)
        
        response = ("✅ **تنظیمات ذخیره شد**\n\n"
                   f"📊 تعداد بازیکنان: **{total_players}**\n"
                   f"🏘️ شهروند: **{citizen_count}**\n"
                   f"🔪 مافیا: **{mafia_count}**\n"
                   f"⏰ زمان رای‌گیری: **{vote_time} دقیقه**\n\n"
                   f"👤 یوزرهای ثبت شده:\n**" + "\n".join(usernames) + "**")
        
        bot.send_message(user_id, response, parse_mode='Markdown')
        show_admin_panel(message)
        
        user_states[user_id] = 'admin'
        del user_states[f"{user_id}_citizen"]
        del user_states[f"{user_id}_mafia"]
        del user_states[f"{user_id}_total_players"]
        del user_states[f"{user_id}_usernames"]
        
    else:
        bot.send_message(user_id, "❌ لطفا یک عدد وارد کنید:")

# ---------- اجرای ربات ----------
if __name__ == '__main__':
    keep_alive()
    print("🤖 ربات بازی مافیا در حال اجراست...")
    try:
        bot.infinity_polling()
    except Exception as e:
        print(f"❌ خطا: {e}")
        print("🔄 تلاش مجدد...")
        time.sleep(5)
        bot.infinity_polling()