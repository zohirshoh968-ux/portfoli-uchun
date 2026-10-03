import asyncio
import json
import logging
import os
import re
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from fastapi import FastAPI, Request

# ---------------------------------------------------------------------
# 1. Sozlamalar — Environment variables (Vercel dashboard orqali olinadi)
# ---------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "8608626990:AAHkuaH4ES9vsPR-EQlMRdWS_Wwdcu_cmj0")
ADMIN_ID = os.getenv("ADMIN_ID", "944890609")
ADMIN_LINK = "https://t.me/zohirshoh_13"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()

# ---------------------------------------------------------------------
# 2. Ma'lumotlar bazasi (Vercel ephemeral disk uchun /tmp ichida saqlanadi)
# ---------------------------------------------------------------------
DB_PATH = "/tmp/data.json"


def default_data() -> dict:
    return {
        "users": {},
        "projects": [],
        "info": "",
        "announcement": None,
        "orders": [],
    }


def load_data() -> dict:
    data = default_data()
    if os.path.exists(DB_PATH):
        try:
            with open(DB_PATH, encoding="utf-8") as f:
                data.update(json.load(f))
        except (json.JSONDecodeError, OSError) as err:
            logging.error("data.json o'qishda xato: %s", err)
    else:
        save_data(data)
    return data


def save_data(d: dict | None = None) -> None:
    try:
        with open(DB_PATH, "w", encoding="utf-8") as f:
            json.dump(d if d is not None else data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error("Faylga yozishda xatolik: %s", e)


data = load_data()
user_steps: dict[int, dict] = {}

# ---------------------------------------------------------------------
# 3. Tugmalar va klaviaturalar
# ---------------------------------------------------------------------
PROJECTS, INFO, QUESTION = "📂 Loyihalar", "ℹ️ Ma'lumot", "❓ Adminga savol"
ORDER, ANNOUNCE, BACK = "🛍️ Buyurtma berish", "📢 E'lonlar", "⬅️ Orqaga"
A_CLIENTS, A_STATS = "👥 Mijozlar", "📊 Statistika"
A_ADD_PROJECT, A_BROADCAST = "➕ Loyiha qo'shish", "📢 E'lon qo'yish"
A_CONTACT, A_ORDERS = "📩 Mijozlarga murojaat", "📦 Buyurtmalar"
A_INFO, A_EXIT = "✏️ Ma'lumotni o'zgartirish", "🏠 Foydalanuvchi menyusi"

ORDER_TYPES = ["Web site", "Telegram bot", "Mobile app"]

MENU_BUTTONS = {
    PROJECTS, INFO, QUESTION, ORDER, ANNOUNCE, BACK,
    A_CLIENTS, A_STATS, A_ADD_PROJECT, A_BROADCAST, A_CONTACT, A_ORDERS, A_INFO, A_EXIT,
    *ORDER_TYPES,
}


def kb(rows: list[list[str]]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t) for t in row] for row in rows],
        resize_keyboard=True,
    )


main_menu = kb([[PROJECTS, INFO], [QUESTION, ORDER], [ANNOUNCE]])
order_menu = kb([[ORDER_TYPES[0]], [ORDER_TYPES[1]], [ORDER_TYPES[2]], [BACK]])
admin_menu = kb([
    [A_CLIENTS, A_STATS],
    [A_ADD_PROJECT, A_BROADCAST],
    [A_CONTACT, A_ORDERS],
    [A_INFO, A_EXIT],
])
contact_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)]],
    resize_keyboard=True,
    one_time_keyboard=True,
)

# ---------------------------------------------------------------------
# 4. Yordamchi funksiyalar
# ---------------------------------------------------------------------
def is_admin(user_id: int) -> bool:
    return str(user_id) == str(ADMIN_ID)


def username_of(user) -> str:
    return f"@{user.username}" if user.username else "yo'q"


def user_card(user) -> str:
    saved = data["users"].get(str(user.id))
    name = saved["name"] if saved else (user.full_name or "—")
    text = f"👤 Ism: {name}\n🔗 Username: {username_of(user)}\n🆔 ID: {user.id}"
    if saved and saved.get("phone"):
        text += f"\n📞 Telefon: {saved['phone']}"
    return text


def reply_button(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ Javob berish", callback_data=f"reply:{chat_id}")]
    ])


async def send_long(chat_id: int, text: str, **kwargs) -> None:
    for i in range(0, len(text), 4000):
        await bot.send_message(chat_id, text[i:i + 4000], **kwargs)


async def send_announcement(chat_id: int, a: dict) -> None:
    caption = a.get("caption")
    t = a["type"]
    if t == "text":
        await bot.send_message(chat_id, a["text"])
    elif t == "photo":
        await bot.send_photo(chat_id, a["file_id"], caption=caption)
    elif t == "video":
        await bot.send_video(chat_id, a["file_id"], caption=caption)
    elif t == "voice":
        await bot.send_voice(chat_id, a["file_id"], caption=caption)
    elif t == "video_note":
        await bot.send_video_note(chat_id, a["file_id"])


def parse_announcement(msg: Message) -> dict | None:
    date = datetime.now().isoformat()
    if msg.photo:
        return {"type": "photo", "file_id": msg.photo[-1].file_id, "caption": msg.caption, "date": date}
    if msg.video:
        return {"type": "video", "file_id": msg.video.file_id, "caption": msg.caption, "date": date}
    if msg.voice:
        return {"type": "voice", "file_id": msg.voice.file_id, "caption": msg.caption, "date": date}
    if msg.video_note:
        return {"type": "video_note", "file_id": msg.video_note.file_id, "date": date}
    if msg.text:
        return {"type": "text", "text": msg.text, "date": date}
    return None


async def broadcast(announcement: dict) -> tuple[int, int]:
    ok = fail = 0
    for user in data["users"].values():
        if user.get("active") is False:
            continue
        try:
            await send_announcement(user["id"], announcement)
            ok += 1
        except TelegramForbiddenError:
            user["active"] = False
            fail += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    save_data()
    return ok, fail

# ---------------------------------------------------------------------
# 5. Handlers
# ---------------------------------------------------------------------
@dp.message(Command("start"))
async def cmd_start(msg: Message):
    chat_id = msg.chat.id
    user_steps.pop(chat_id, None)
    user = data["users"].get(str(chat_id))
    if user:
        user["active"] = True
        save_data()
        return await msg.answer(f"Xush kelibsiz, {user['name']}! 👋", reply_markup=main_menu)

    user_steps[chat_id] = {"step": "ask_name"}
    await msg.answer("Salom! Iltimos, ismingizni kiriting:", reply_markup=ReplyKeyboardRemove())


@dp.message(Command("help"))
async def cmd_help(msg: Message):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Adminga murojaat", url=ADMIN_LINK)]
    ])
    await msg.answer("Yordam uchun adminga murojaat qiling", reply_markup=markup)


@dp.message(Command("admin"))
async def cmd_admin(msg: Message):
    user_steps.pop(msg.chat.id, None)
    if not is_admin(msg.from_user.id):
        return await msg.answer("Agar yana urunsangiz, bloklanasiz!")
    await msg.answer("🔐 Admin paneli", reply_markup=admin_menu)


@dp.callback_query(F.data.startswith("reply:"))
async def cb_reply(q: CallbackQuery):
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    target_id = q.data.split(":", 1)[1]
    user_steps[q.from_user.id] = {"step": "contact_msg", "target_id": target_id}
    await bot.send_message(q.from_user.id, f"ID {target_id} ga yuboriladigan xabarni yozing:")


@dp.message(F.chat.type == "private")
async def on_message(msg: Message):
    chat_id = msg.chat.id
    text = msg.text

    if text and text.startswith("/"):
        return

    try:
        state = user_steps.get(chat_id)

        if state and state["step"] in ("ask_name", "ask_phone"):
            return await handle_registration(msg, state)

        if str(chat_id) not in data["users"] and not is_admin(chat_id):
            return await msg.answer("Iltimos, avval /start buyrug'ini yuboring.")

        if text in MENU_BUTTONS:
            user_steps.pop(chat_id, None)
            return await handle_button(msg)

        if state:
            await handle_step(msg, state)
    except Exception:
        logging.exception("Xatolik")


async def handle_registration(msg: Message, state: dict):
    chat_id = msg.chat.id

    if state["step"] == "ask_name":
        if not msg.text or not msg.text.strip():
            return await msg.answer("Iltimos, ismingizni matn ko'rinishida kiriting:")
        state["name"] = msg.text.strip()
        state["step"] = "ask_phone"
        return await msg.answer(
            "Rahmat! Endi pastdagi tugma orqali telefon raqamingizni yuboring:",
            reply_markup=contact_menu,
        )

    if not msg.contact or (msg.contact.user_id and msg.contact.user_id != msg.from_user.id):
        return await msg.answer("Iltimos, pastdagi tugmani bosing 👇", reply_markup=contact_menu)

    data["users"][str(chat_id)] = {
        "id": chat_id,
        "name": state["name"],
        "username": msg.from_user.username,
        "phone": msg.contact.phone_number,
        "active": True,
        "date": datetime.now().isoformat(),
    }
    save_data()
    user_steps.pop(chat_id, None)

    await msg.answer("✅ Ma'lumotlaringiz saqlandi!", reply_markup=main_menu)
    try:
        await bot.send_message(ADMIN_ID, f"🆕 Yangi foydalanuvchi:\n\n{user_card(msg.from_user)}")
    except Exception:
        pass


async def handle_button(msg: Message):
    chat_id = msg.chat.id
    text = msg.text

    if text == PROJECTS:
        if not data["projects"]:
            return await msg.answer("Hali loyiha qo'shilmagan")
        for p in data["projects"]:
            caption = f"📌 {p['name']}\n\n{p['description']}"[:1024]
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔗 Ko'rish", url=p["link"])]
            ])
            await bot.send_photo(chat_id, p["photo"], caption=caption, reply_markup=markup)
        return

    if text == INFO:
        return await msg.answer(data["info"] or "Ma'lumot qo'shilmagan")

    if text == QUESTION:
        user_steps[chat_id] = {"step": "ask_question"}
        return await msg.answer("Savolingizni yozing:", reply_markup=ReplyKeyboardRemove())

    if text == ORDER:
        return await msg.answer("Qaysi turdagi loyiha kerak?", reply_markup=order_menu)

    if text == ANNOUNCE:
        if not data["announcement"]:
            return await msg.answer("E'lonlar yo'q")
        return await send_announcement(chat_id, data["announcement"])

    if text in (BACK, A_EXIT):
        return await msg.answer("🏠 Asosiy menyu", reply_markup=main_menu)

    if text in ORDER_TYPES:
        user_steps[chat_id] = {"step": "order_details", "order_type": text}
        return await msg.answer(
            f"Qanday {text} yaratmoqchisiz? Shuni batafsil yozing:",
            reply_markup=ReplyKeyboardRemove(),
        )

    if not is_admin(chat_id):
        return

    if text == A_CLIENTS:
        users = list(data["users"].values())
        if not users:
            return await msg.answer("Mijozlar yo'q")
        lines = [
            f"{i}. {u['name']}\n   {'@' + u['username'] if u.get('username') else 'username yo`q'}\n"
            f"   📞 {u['phone']}\n   🆔 {u['id']}"
            for i, u in enumerate(users, 1)
        ]
        return await send_long(chat_id, "👥 Mijozlar:\n\n" + "\n\n".join(lines))

    if text == A_STATS:
        return await msg.answer(
            f"📊 Statistika\n\n👥 Foydalanuvchilar: {len(data['users'])}\n"
            f"📂 Loyihalar: {len(data['projects'])}\n📦 Buyurtmalar: {len(data['orders'])}"
        )

    if text == A_ADD_PROJECT:
        user_steps[chat_id] = {"step": "p_name"}
        return await msg.answer("Loyiha nomini kiriting:")

    if text == A_BROADCAST:
        user_steps[chat_id] = {"step": "broadcast"}
        return await msg.answer("E'lonni yuboring (rasm, video, matn, ovozli xabar yoki dumaloq video):")

    if text == A_CONTACT:
        user_steps[chat_id] = {"step": "contact_id"}
        return await msg.answer("Mijozning ID raqamini kiriting:")

    if text == A_ORDERS:
        if not data["orders"]:
            return await msg.answer("Buyurtmalar yo'q")
        blocks = []
        for i, o in enumerate(data["orders"], 1):
            u = data["users"].get(str(o["user_id"]), {})
            when = datetime.fromisoformat(o["date"]).strftime("%d.%m.%Y %H:%M")
            uname = "@" + u["username"] if u.get("username") else "username yo'q"
            blocks.append(
                f"#{i} — {o['type']}\n👤 {u.get('name', '—')} (ID: {o['user_id']}, {uname})\n"
                f"📞 {u.get('phone', '—')}\n📝 {o['details']}\n🕒 {when}"
            )
        return await send_long(chat_id, "📦 Buyurtmalar:\n\n" + "\n\n— — — — —\n\n".join(blocks))

    if text == A_INFO:
        user_steps[chat_id] = {"step": "edit_info"}
        return await msg.answer('Yangi "Ma\'lumot" matnini yuboring:')


async def handle_step(msg: Message, state: dict):
    chat_id = msg.chat.id
    text = msg.text
    step = state["step"]

    if step == "ask_question":
        if not text:
            return await msg.answer("Iltimos, savolni matn ko'rinishida yozing:")
        await bot.send_message(
            ADMIN_ID,
            f"❓ Yangi savol:\n\n{user_card(msg.from_user)}\n\n💬 {text}",
            reply_markup=reply_button(chat_id),
        )
        user_steps.pop(chat_id, None)
        return await msg.answer("✅ Savolingiz adminga yuborildi.", reply_markup=main_menu)

    if step == "order_details":
        if not text:
            return await msg.answer("Iltimos, matn ko'rinishida yozing:")
        data["orders"].append({
            "id": len(data["orders"]) + 1,
            "user_id": chat_id,
            "type": state["order_type"],
            "details": text,
            "date": datetime.now().isoformat(),
        })
        save_data()
        await bot.send_message(
            ADMIN_ID,
            f"🛍️ Yangi buyurtma: {state['order_type']}\n\n{user_card(msg.from_user)}\n\n📝 {text}",
            reply_markup=reply_button(chat_id),
        )
        user_steps.pop(chat_id, None)
        return await msg.answer("✅ Buyurtmangiz qabul qilindi. Tez orada bog'lanamiz!", reply_markup=main_menu)

    if not is_admin(chat_id):
        return

    if step == "p_name":
        if not text:
            return await msg.answer("Nomni matn ko'rinishida kiriting:")
        state.update(name=text, step="p_photo")
        return await msg.answer("Loyiha rasmini yuboring:")

    if step == "p_photo":
        if not msg.photo:
            return await msg.answer("Iltimos, rasm yuboring:")
        state.update(photo=msg.photo[-1].file_id, step="p_desc")
        return await msg.answer("Loyiha tavsifini kiriting:")

    if step == "p_desc":
        if not text:
            return await msg.answer("Tavsifni matn ko'rinishida kiriting:")
        state.update(description=text, step="p_link")
        return await msg.answer("Loyiha havolasini (link) kiriting:")

    if step == "p_link":
        if not text or not re.match(r"^https?://", text, re.I):
            return await msg.answer("Havola http:// yoki https:// bilan boshlanishi kerak:")
        data["projects"].append({
            "name": state["name"],
            "photo": state["photo"],
            "description": state["description"],
            "link": text,
        })
        save_data()
        user_steps.pop(chat_id, None)
        return await msg.answer("✅ Loyiha qo'shildi!", reply_markup=admin_menu)

    if step == "broadcast":
        announcement = parse_announcement(msg)
        if not announcement:
            return await msg.answer("Bu turdagi xabar qo'llab-quvvatlanmaydi.")
        data["announcement"] = announcement
        save_data()
        user_steps.pop(chat_id, None)
        await msg.answer("⏳ Tarqatilmoqda...")
        ok, fail = await broadcast(announcement)
        return await msg.answer(f"✅ Yuborildi: {ok}\n❌ Xato: {fail}", reply_markup=admin_menu)

    if step == "contact_id":
        if not text or not text.strip().isdigit():
            return await msg.answer("ID faqat raqamlardan iborat bo'lishi kerak:")
        state.update(target_id=text.strip(), step="contact_msg")
        return await msg.answer("Yuboriladigan xabarni yozing:")

    if step == "contact_msg":
        if not text:
            return await msg.answer("Xabarni matn ko'rinishida yozing:")
        try:
            await bot.send_message(state["target_id"], f"📩 Admindan xabar:\n\n{text}")
            await msg.answer("✅ Xabar yuborildi.", reply_markup=admin_menu)
        except Exception:
            await msg.answer("❌ Xabar yuborilmadi (ID noto'g'ri yoki bot bloklangan).", reply_markup=admin_menu)
        user_steps.pop(chat_id, None)
        return

    if step == "edit_info":
        if not text:
            return await msg.answer("Matn yuboring:")
        data["info"] = text
        save_data()
        user_steps.pop(chat_id, None)
        return await msg.answer("✅ Ma'lumot yangilandi.", reply_markup=admin_menu)

# ---------------------------------------------------------------------
# 6. Webhook FastAPI Yo'nalishi
# ---------------------------------------------------------------------
@app.post("/webhook")
async def webhook_handler(request: Request):
    try:
        update_data = await request.json()
        update = Update.model_validate(update_data, context={"bot": bot})
        await dp.feed_update(bot, update)
        return {"status": "ok"}
    except Exception as e:
        logging.error("Webhook xatosi: %s", e)
        return {"status": "error", "message": str(e)}

@app.get("/")
async def root():
    return {"message": "Bot is running via Webhook on Vercel!"}
