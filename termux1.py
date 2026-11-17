import asyncio
import os
import random
from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError

# ==========================================
# НАСТРОЙКИ
# ==========================================
API_ID = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"
SESSION_NAME = "check_session"
BOT_USERNAME = "@gminesbot"     # Username бота

TARGET_USERNAME = "@sasha124974"   # куда присылать результаты
CHECKS_PER_FILE = 100              # чеков в одном файле
TOTAL_CHECKS = 100                 # сколько всего создать
DELAY_BETWEEN = 5                  # пауза между чеками, сек
OUT_DIR = "checks"                 # папка для файлов
# ==========================================


class FloodGuard:
    """Единая точка ожидания — Telegram сам скажет, сколько ждать."""

    @staticmethod
    async def wait(seconds: float, reason: str = ""):
        if seconds <= 0:
            return
        tail = f" ({reason})" if reason else ""
        print(f"    ⏳ пауза {int(seconds)} с{tail}")
        await asyncio.sleep(seconds)


def extract_link(msg) -> str | None:
    """Достаёт ссылку из кнопки или текста сообщения."""
    if msg is None:
        return None

    if msg.buttons:
        for row in msg.buttons:
            for btn in row:
                url = getattr(btn, "url", None)
                if url and "t.me" in url:
                    return url

    if msg.text:
        for word in msg.text.split():
            if "http" in word and "t.me" in word:
                return word.strip(".,()[]{}<>\"'")

    return None


def choose_check_amount() -> int:
    """Выбирает сумму по заданным вероятностям."""
    return random.choices(
        population=[33333, 66666, 99999],
        weights=[85, 9, 6],
        k=1,
    )[0]


async def create_check(client, bot, number: int) -> str | None:
    """Один проход: /check → «Создать чек» → случайная сумма → 1 → ссылка."""
    try:
        async with client.conversation(bot, timeout=25) as conv:
            await conv.send_message("/check")
            await asyncio.sleep(2)

            msgs = await client.get_messages(bot, limit=3)
            clicked = False

            for msg in msgs:
                if not msg.buttons:
                    continue
                for row in msg.buttons:
                    for btn in row:
                        text = (btn.text or "").lower()
                        if "создать" in text and "чек" in text:
                            await btn.click()
                            clicked = True
                            break
                    if clicked:
                        break
                if clicked:
                    break

            if not clicked:
                print(f"    ❌ кнопка «Создать чек» не найдена")
                return None

            await asyncio.sleep(2)

            last = await client.get_messages(bot, limit=1)
            reply_id = last[0].id if last else None
            amount = choose_check_amount()
            print(f"    💰 Сумма чека: {amount}")
            await conv.send_message(str(amount), reply_to=reply_id)

            await asyncio.sleep(3)

            last = await client.get_messages(bot, limit=1)
            reply_id = last[0].id if last else None
            await conv.send_message("1", reply_to=reply_id)

            await asyncio.sleep(3)

            final_msg = await conv.get_response(timeout=20)

    except FloodWaitError as e:
        await FloodGuard.wait(e.seconds + 3, "flood")
        print(f"    🔁 повтор после флуда")
        if number < 3:  # не зацикливаемся
            return await create_check(client, bot, number + 1)
        return None

    except asyncio.TimeoutError:
        print(f"    ❌ бот не ответил вовремя")
        return None

    except RPCError as e:
        print(f"    ❌ ошибка Telegram: {e}")
        return None

    return extract_link(final_msg)


async def send_links(client, target, links: list[str], file_no: int):
    """Отправляет пачку ссылок текстом (порциями) и файлом."""
    chunk: list[str] = []
    part = 1

    for link in links:
        chunk.append(link)
        # 4096 — лимит сообщения; держим запас
        if sum(len(x) + 1 for x in chunk) > 3500:
            body = "\n".join(chunk)
            await client.send_message(target, f"📄 Файл {file_no}, часть {part}\n{body}")
            await FloodGuard.wait(1.5)
            chunk = []
            part += 1

    if chunk:
        body = "\n".join(chunk)
        await client.send_message(target, f"📄 Файл {file_no}, часть {part}\n{body}")
        await FloodGuard.wait(1.5)


async def flush_batch(client, target, batch: list[str], file_no: int) -> str:
    """Пишет файл на диск и отправляет его получателю."""
    os.makedirs(OUT_DIR, exist_ok=True)
    filename = os.path.join(OUT_DIR, f"checks_{file_no:03d}.txt")

    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(batch) + "\n")

    print(f"\n[+] Файл готов: {filename} — {len(batch)} шт.")

    caption = f"📄 <b>Файл {file_no}</b>\nЧеков: {len(batch)}"
    try:
        await client.send_file(target, filename, caption=caption, parse_mode="html")
        print(f"[+] Файл {file_no} отправлен на {TARGET_USERNAME}")
    except FloodWaitError as e:
        await FloodGuard.wait(e.seconds + 3, "flood при отправке файла")
        await client.send_file(target, filename, caption=caption, parse_mode="html")

    await send_links(client, target, batch, file_no)

    return filename


async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()
    print("[+] Авторизация успешна!")

    try:
        # Сначала разрешаем username в сущность Telegram и сохраняем её в кеше сессии.
        bot = await client.get_entity(BOT_USERNAME)
        print(f"[+] Бот найден: {BOT_USERNAME}")
    except Exception as e:
        print(f"[!] Не удалось найти бота {BOT_USERNAME}: {e}")
        print("    Открой диалог с ботом в Telegram и попробуй снова.")
        await client.disconnect()
        return

    try:
        target = await client.get_entity(TARGET_USERNAME)
        print(f"[+] Получатель найден: {TARGET_USERNAME}")
    except Exception as e:
        print(f"[!] Не удалось найти {TARGET_USERNAME}: {e}")
        print("    Проверь, что с этого аккаунта можно написать получателю.")
        await client.disconnect()
        return

    os.makedirs(OUT_DIR, exist_ok=True)

    print(f"\n[*] Создаю {TOTAL_CHECKS} чеков, по {CHECKS_PER_FILE} в файле")
    print(f"[*] Пауза между чеками: {DELAY_BETWEEN} с\n")

    batch: list[str] = []
    total_ok = 0
    total_fail = 0
    file_no = 1
    started = asyncio.get_event_loop().time()

    for i in range(1, TOTAL_CHECKS + 1):
        print(f"[{i}/{TOTAL_CHECKS}] создаю чек…")
        link = await create_check(client, bot, 1)

        if link:
            batch.append(link)
            total_ok += 1
            print(f"    ✅ {link}")
        else:
            total_fail += 1
            print(f"    ❌ не получилось")

        if len(batch) >= CHECKS_PER_FILE:
            await flush_batch(client, target, batch, file_no)
            batch = []
            file_no += 1

        if i < TOTAL_CHECKS:
            await FloodGuard.wait(DELAY_BETWEEN)

    # остаток, если число не кратно 100
    if batch:
        await flush_batch(client, target, batch, file_no)

    elapsed = int(asyncio.get_event_loop().time() - started)

    summary = (
        f"✅ <b>Готово</b>\n"
        f"Создано: <b>{total_ok}</b>\n"
        f"Ошибок: <b>{total_fail}</b>\n"
        f"Файлов: <b>{file_no if batch else file_no - 1}</b>\n"
        f"Время: <b>{elapsed // 60} мин {elapsed % 60} с</b>"
    )
    print("\n" + "=" * 50)
    print(summary.replace("<b>", "").replace("</b>", ""))
    print("=" * 50)

    try:
        await client.send_message(target, summary, parse_mode="html")
    except FloodWaitError as e:
        await FloodGuard.wait(e.seconds + 3, "flood в конце")
        await client.send_message(target, summary, parse_mode="html")

    await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] Скрипт остановлен пользователем.")
    except Exception as e:
        print(f"\n[!] Произошла ошибка: {e}")
