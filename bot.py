# -*- coding: utf-8 -*-
import logging
import sqlite3
from datetime import date, datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

import config

AMOUNT = 500_000
REMINDER_DAYS = [10, 5, 3, 1, 0]
DB_PATH = "fund.db"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            telegram_id INTEGER UNIQUE NOT NULL,
            birth_date TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS contributions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payer_id INTEGER NOT NULL,
            birthday_member_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            paid INTEGER NOT NULL DEFAULT 0,
            paid_at TEXT,
            UNIQUE(payer_id, birthday_member_id, year)
        )
        """
    )
    conn.commit()
    conn.close()


def add_member(full_name: str, telegram_id: int, birth_date: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO members (full_name, telegram_id, birth_date) VALUES (?, ?, ?)",
        (full_name, telegram_id, birth_date),
    )
    conn.commit()
    conn.close()


def get_members():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM members ORDER BY id").fetchall()
    conn.close()
    return rows


def get_member_by_telegram_id(telegram_id: int):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM members WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()
    return row


def create_contribution_if_missing(payer_id, birthday_member_id, year):
    conn = get_conn()
    conn.execute(
        """
        INSERT OR IGNORE INTO contributions
            (payer_id, birthday_member_id, year, amount, paid)
        VALUES (?, ?, ?, ?, 0)
        """,
        (payer_id, birthday_member_id, year, AMOUNT),
    )
    conn.commit()
    conn.close()


def get_unpaid_contribution(payer_id, birthday_member_id, year):
    conn = get_conn()
    row = conn.execute(
        """
        SELECT * FROM contributions
        WHERE payer_id=? AND birthday_member_id=? AND year=? AND paid=0
        """,
        (payer_id, birthday_member_id, year),
    ).fetchone()
    conn.close()
    return row


def mark_paid(contribution_id: int):
    conn = get_conn()
    conn.execute(
        "UPDATE contributions SET paid=1, paid_at=? WHERE id=?",
        (datetime.now().isoformat(), contribution_id),
    )
    conn.commit()
    conn.close()


def get_status_for_birthday(birthday_member_id: int, year: int):
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT c.*, m.full_name FROM contributions c
        JOIN members m ON m.id = c.payer_id
        WHERE c.birthday_member_id=? AND c.year=?
        ORDER BY m.full_name
        """,
        (birthday_member_id, year),
    ).fetchall()
    conn.close()
    return rows


def next_birthday(birth_date_str: str, today: date) -> date:
    bd = datetime.strptime(birth_date_str, "%Y-%m-%d").date()
    this_year = bd.replace(year=today.year)
    if this_year >= today:
        return this_year
    return bd.replace(year=today.year + 1)


def is_admin(telegram_id: int) -> bool:
    return telegram_id in config.ADMIN_IDS


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Assalomu alaykum! Bu — oilaviy tug'ilgan kun jamg'armasi boti.\n\n"
        "Buyruqlar:\n"
        "/azolar — a'zolar ro'yxati\n"
        "/tugilgankunlar — yaqin tug'ilgan kunlar\n"
        "/holat <ism> — kim to'lagan/to'lamaganini ko'rish\n\n"
        "Admin uchun:\n"
        "/add <Ism Familiya> <telegram_id> <YYYY-MM-DD>"
    )


async def list_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    members = get_members()
    if not members:
        await update.message.reply_text("Hozircha a'zolar qo'shilmagan.")
        return
    text = "👨‍👩‍👧‍👦 *A'zolar ro'yxati:*\n\n"
    for m in members:
        bd = datetime.strptime(m["birth_date"], "%Y-%m-%d").date()
        text += f"• {m['full_name']} — {bd.strftime('%d.%m.%Y')}\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def upcoming_birthdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today()
    members = get_members()
    items = []
    for m in members:
        nb = next_birthday(m["birth_date"], today)
        days_left = (nb - today).days
        items.append((days_left, m["full_name"], nb))
    items.sort()
    text = "🎂 *Yaqin tug'ilgan kunlar:*\n\n"
    for days_left, name, nb in items[:8]:
        text += f"• {name} — {nb.strftime('%d.%m.%Y')} ({days_left} kun qoldi)\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def add_member_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return
    try:
        args = context.args
        birth_date = args[-1]
        telegram_id = int(args[-2])
        full_name = " ".join(args[:-2])
        datetime.strptime(birth_date, "%Y-%m-%d")
        add_member(full_name, telegram_id, birth_date)
        await update.message.reply_text(
            f"✅ Qo'shildi: {full_name} ({birth_date})"
        )
    except Exception as e:
        await update.message.reply_text(
            "❌ Format noto'g'ri. Namuna:\n"
            "/add Aziz Valiyev 123456789 1995-04-12\n\n"
            f"Xatolik: {e}"
        )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    members = get_members()
    if not context.args:
        await update.message.reply_text(
            "Ism yozing, masalan: /holat Aziz"
        )
        return
    query_name = " ".join(context.args).lower()
    target = None
    for m in members:
        if query_name in m["full_name"].lower():
            target = m
            break
    if not target:
        await update.message.reply_text("Bunday a'zo topilmadi.")
        return

    today = date.today()
    nb = next_birthday(target["birth_date"], today)
    year = nb.year
    rows = get_status_for_birthday(target["id"], year)
    if not rows:
        await update.message.reply_text(
            f"{target['full_name']} uchun hali kontributsiyalar yaratilmagan "
            f"(eslatma {REMINDER_DAYS[0]} kun qolganda avtomatik yaratiladi)."
        )
        return

    text = f"💰 *{target['full_name']}* tug'ilgan kuni ({nb.strftime('%d.%m.%Y')}) uchun holat:\n\n"
    total_paid = 0
    for r in rows:
        icon = "✅" if r["paid"] else "❌"
        text += f"{icon} {r['full_name']} — {r['amount']:,} so'm\n"
        if r["paid"]:
            total_paid += r["amount"]
    text += f"\nJami yig'ildi: {total_paid:,} / {len(rows) * AMOUNT:,} so'm"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def paid_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, contribution_id = query.data.split(":")
    mark_paid(int(contribution_id))
    await query.edit_message_text(
        text=query.message.text + "\n\n✅ To'lov tasdiqlandi. Rahmat!",
    )


async def daily_check(context: ContextTypes.DEFAULT_TYPE):
    today = date.today()
    members = get_members()

    for birthday_member in members:
        nb = next_birthday(birthday_member["birth_date"], today)
        days_left = (nb - today).days
        year = nb.year

        if days_left not in REMINDER_DAYS:
            continue

        if days_left == max(REMINDER_DAYS):
            for payer in members:
                if payer["id"] == birthday_member["id"]:
                    continue
                create_contribution_if_missing(payer["id"], birthday_member["id"], year)

        for payer in members:
            if payer["id"] == birthday_member["id"]:
                continue
            contrib = get_unpaid_contribution(payer["id"], birthday_member["id"], year)
            if not contrib:
                continue

            if days_left == 0:
                text = (
                    f"🎉 Bugun *{birthday_member['full_name']}*ning tug'ilgan kuni!\n"
                    f"Hali {AMOUNT:,} so'm to'lovingizni amalga oshirmadingiz."
                )
            else:
                text = (
                    f"🔔 Eslatma: *{birthday_member['full_name']}*ning tug'ilgan kunigacha "
                    f"{days_left} kun qoldi ({nb.strftime('%d.%m.%Y')}).\n"
                    f"Iltimos, {AMOUNT:,} so'm jamg'armaga o'tkazing."
                )

            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("✅ To'ladim", callback_data=f"paid:{contrib['id']}")]]
            )
            try:
                await context.bot.send_message(
                    chat_id=payer["telegram_id"],
                    text=text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard,
                )
            except Exception as e:
                logger.warning("Xabar yuborilmadi (%s): %s", payer["full_name"], e)


def main():
    init_db()

    app = Application.builder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("azolar", list_members))
    app.add_handler(CommandHandler("tugilgankunlar", upcoming_birthdays))
    app.add_handler(CommandHandler("add", add_member_cmd))
    app.add_handler(CommandHandler("holat", status_cmd))
    app.add_handler(CallbackQueryHandler(paid_button_callback, pattern=r"^paid:"))

    app.job_queue.run_daily(
        daily_check,
        time=config.DAILY_CHECK_TIME,
        name="daily_birthday_check",
    )

    logger.info("Bot ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()
