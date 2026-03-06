"""
YsuShtok Bot — Telegram бот для игры «Что? Где? Когда?»
Источник: gotquestions.online (React SPA — нужен Selenium)

Установка:
  pip install aiogram requests selenium webdriver-manager beautifulsoup4 deep-translator

Нужен установленный Google Chrome или Chromium.
"""

import asyncio
import random
import re
import time
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

TG_TOKEN     = "8294427825:AAEc1aZdUNoqlRgZj01DtAT0ryBtvMvhKlQ"
MAX_ATTEMPTS = 8

bot = Bot(token=TG_TOKEN)
dp  = Dispatcher()


def translate_to_armenian(text: str) -> str:
    try:
        from deep_translator import GoogleTranslator
        result = GoogleTranslator(source="ru", target="hy").translate(text)
        return result or "—"
    except ImportError:
        return "⚠️ Установи: pip install deep-translator"
    except Exception as e:
        print(f"[TRANSLATE] Ошибка: {e}")
        return "—"


def estimate_difficulty(question: str, answer: str) -> int:
    q_len   = len(question)
    a_len   = len(answer)
    n_words = len(question.lower().split())
    q_lower = question.lower()
    hard_markers = ["теорема","формула","латынь","древн","философ","парадокс",
                    "феномен","эффект","принцип","закон","термин","символ",
                    "этимолог","геральд","архитект","астроном","биолог","химик",
                    "математик","физик","лингвист"]
    easy_markers = ["цвет","животн","столиц","страна","город","еда","имя",
                    "какой","сколько","назов","кто такой"]
    score = 5
    if q_len > 300:   score += 2
    elif q_len > 180: score += 1
    elif q_len < 80:  score -= 1
    if a_len <= 10:   score -= 1
    elif a_len > 60:  score += 1
    for m in hard_markers:
        if m in q_lower: score += 1; break
    for m in easy_markers:
        if m in q_lower: score -= 1; break
    if n_words > 50:   score += 1
    elif n_words < 15: score -= 1
    return max(1, min(10, score))


_META_MARKERS = re.compile(
    r"(?:"
    r"\d{4}\s+(?:тур|тура|туре)\s*\d*"
    r"|\bтур\s+\d+"
    r"|\d{4}-\d{2}"
    r"|блиц|кубок|лига|чемпионат|олимпиад"
    r"|(?:янв|фев|мар|апр|май|июн|июл|авг|сен|окт|ноя|дек)\.\s*\d{4}"
    r")",
    re.IGNORECASE
)


def _strip_meta_prefix(text: str) -> str:
    lines = text.splitlines()
    if len(lines) > 1:
        result_lines = []
        found = False
        for line in lines:
            s = line.strip()
            if not s:
                continue
            is_meta = bool(_META_MARKERS.search(s)) and "?" not in s
            if not found:
                if is_meta:
                    continue
                else:
                    found = True
            result_lines.append(s)
        result = " ".join(result_lines).strip()
        if result and len(result) > 10:
            return result

    best_end = max((m.end() for m in _META_MARKERS.finditer(text)), default=0)
    if best_end > 0:
        rest = text[best_end:]
        rest = re.sub(r"^[\s·•–—\d]+", "", rest)
        rest = re.sub(r"^[А-ЯA-Z][а-яёa-z]+-?[а-яёa-z]*\s+[А-ЯA-Z][а-яёa-z]+\s+", "", rest)
        if len(rest) > 15:
            return rest.strip()
    return text


def clean_question(raw: str) -> str:
    text  = raw.strip()
    q_pos = text.find("?")
    if q_pos == -1:
        return _strip_meta_prefix(text)
    before = text[:q_pos]
    start  = 0
    for sep in ["\n", ". ", ".\t"]:
        pos = before.rfind(sep)
        if pos != -1 and pos + len(sep) > start:
            start = pos + len(sep)
    candidate = _strip_meta_prefix(text[start:].strip())
    candidate = re.sub(r'^\d+\.\s*', '', candidate).strip()
    candidate = re.split(r'(?i)\s*ответ\s*:', candidate)[0].strip()
    return candidate if len(candidate) > 15 else text


def clean_answer(raw: str) -> str:
    text = raw.strip()
    if _META_MARKERS.search(text) or re.search(r"(?i)вопрос\s+\d+|блиц|кубок|лига|тур\s+\d+", text):
        return "—"
    text = re.sub(r"(?i)^ответ[\s:]+", "", text).strip()
    return text or "—"


_BUILD_ID: str | None = None


def get_build_id() -> str | None:
    global _BUILD_ID
    if _BUILD_ID:
        return _BUILD_ID
    try:
        resp = requests.get("https://gotquestions.online/", timeout=8, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        for pattern in [r'"buildId"\s*:\s*"([^"]+)"', r'/_next/static/([^/]+)/_buildManifest']:
            m = re.search(pattern, resp.text)
            if m:
                _BUILD_ID = m.group(1)
                return _BUILD_ID
    except Exception as e:
        print(f"[INIT] Ошибка: {e}")
    return None


def _flatten(d, result=None):
    if result is None:
        result = {}
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, (dict, list)):
                _flatten(v, result)
            elif v and isinstance(v, str) and len(v) > 1:
                result[k.lower()] = v
    elif isinstance(d, list):
        for item in d:
            _flatten(item, result)
    return result


def fetch_via_nextjs_api(q_id: int) -> dict | None:
    build_id = get_build_id()
    if not build_id:
        return None
    url = f"https://gotquestions.online/_next/data/{build_id}/question/{q_id}.json"
    try:
        resp = requests.get(url, timeout=8, headers={
            "User-Agent": "Mozilla/5.0", "x-nextjs-data": "1",
            "Referer": f"https://gotquestions.online/question/{q_id}",
        })
        if resp.status_code != 200:
            return None
        flat    = _flatten(resp.json())
        q       = flat.get("question") or flat.get("text") or flat.get("body") or ""
        a       = (flat.get("answer") or flat.get("answer_text") or
                   flat.get("correct_answer") or flat.get("correct") or "")
        cat     = flat.get("category") or flat.get("category_name") or "Без категории"
        zachot  = flat.get("zachot") or flat.get("accept") or flat.get("accepted") or ""
        comment = flat.get("comment") or flat.get("commentary") or ""
        source  = flat.get("source") or flat.get("package") or ""
        q = clean_question(q)
        a = clean_answer(a) if a else "—"
        if q and len(q) > 15 and "?" in q:
            return {"id": q_id, "url": f"https://gotquestions.online/question/{q_id}",
                    "question": q, "answer": a, "category": cat,
                    "source": source, "zachot": zachot, "comment": comment}
    except Exception as e:
        print(f"[NEXT] Ошибка: {e}")
    return None


def fetch_via_selenium(q_id: int) -> dict | None:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from webdriver_manager.chrome import ChromeDriverManager
        from bs4 import BeautifulSoup
    except ImportError as e:
        print(f"[SELENIUM] Не установлено: {e}")
        return None

    NAV_GARBAGE = {
        "поиск","пакеты","случайный пакет","люди","таймер","о сайте",
        "хотите печенья","отклонить","принять","мы ценим вашу конфиденциальность",
        "bug_report","light_mode","menu","search","quiz","casino","group","timer","help_center",
    }
    ICON_WORDS = {
        "menu","search","quiz","casino","group","timer","help_center",
        "light_mode","bug_report","bookmark_border","share",
        "thumb_up","thumb_down","expand_less","expand_more",
    }

    url  = f"https://gotquestions.online/question/{q_id}"
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

    driver = None
    try:
        service = Service(ChromeDriverManager().install())
        driver  = webdriver.Chrome(service=service, options=opts)
        driver.get(url)

        wait = WebDriverWait(driver, 10)
        try:
            btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(text(),'Принять') or contains(text(),'принять')]")
            ))
            btn.click()
            time.sleep(0.5)
        except Exception:
            pass

        time.sleep(2.5)

        # Кликаем "Показать ответ"
        try:
            answer_btns = driver.find_elements(By.XPATH,
                "//*[not(ancestor::nav) and not(ancestor::header)]"
                "[contains(translate(normalize-space(text()),"
                "'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ',"
                "'абвгдеёжзийклмнопрстуфхцчшщъыьэюя'),'показать ответ')"
                " or contains(translate(normalize-space(text()),"
                "'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ',"
                "'абвгдеёжзийклмнопрстуфхцчшщъыьэюя'),'скрыть ответ')]"
            )
            if answer_btns:
                driver.execute_script("arguments[0].click();", answer_btns[0])
                print(f"[SELENIUM] Нажата кнопка ответа: {answer_btns[0].text[:40]!r}")
                time.sleep(1.5)
            else:
                height = driver.execute_script("return document.body.scrollHeight")
                for el in driver.find_elements(By.XPATH,
                        "//div[@role='button'] | //span[@role='button'] | //button"):
                    try:
                        y   = el.location.get("y", 0)
                        txt = el.text.strip().lower()
                        if y > height * 0.25 and txt and "menu" not in txt and "поиск" not in txt:
                            driver.execute_script("arguments[0].click();", el)
                    except Exception:
                        pass
                time.sleep(1.5)
        except Exception as e:
            print(f"[SELENIUM] Ошибка клика: {e}")

        soup = BeautifulSoup(driver.page_source, "html.parser")
        for tag in soup.find_all(["nav", "header", "footer", "button"]):
            tag.decompose()
        for tag in soup.find_all(class_=re.compile(r"nav|menu|sidebar|header|footer|cookie|banner", re.I)):
            tag.decompose()

        texts = []
        seen  = set()
        for tag in soup.find_all(["p", "h1", "h2", "h3", "li", "span", "div"]):
            t = tag.get_text(" ", strip=True)
            if len(t) < 10 or len(t) > 1000 or t in seen:
                continue
            t_lower = t.lower()
            if any(g in t_lower for g in NAV_GARBAGE):
                continue
            if set(t_lower.split()).issubset(ICON_WORDS):
                continue
            seen.add(t)
            texts.append(t)

        print(f"[SELENIUM] ID={q_id}, блоков: {len(texts)}")
        for i, t in enumerate(texts[:20]):
            print(f"  [{i}] {t[:120]}")

        q_text = a_text = zachot_text = comment_text = ""
        LABEL_RE = re.compile(r"(?i)(?:^|\s)(ответ|зачёт|зачет|комментарий|автор|источник)\s*:")
        content_texts = []

        for t in texts:
            if LABEL_RE.search(t):
                parts = re.split(r"(?i)(?=(?:^|\s)(?:ответ|зачёт|зачет|комментарий|автор|источник)\s*:)", t)
                for part in parts:
                    part = part.strip()
                    if not part:
                        continue
                    if re.match(r"(?i)^ответ\s*:", part):
                        if not a_text:
                            val = re.sub(r"(?i)^ответ\s*:\s*", "", part).strip().rstrip(".")
                            val = re.split(r"(?i)\s+(?:зачёт|зачет|комментарий|автор)\s*:", val)[0].strip()
                            if val:
                                a_text = val
                    elif re.match(r"(?i)^зач[её]т\s*:", part):
                        if not zachot_text:
                            zachot_text = re.sub(r"(?i)^зач[её]т\s*:\s*", "", part).strip()
                    elif re.match(r"(?i)^комментарий\s*:", part):
                        if not comment_text:
                            val = re.sub(r"(?i)^комментарий\s*:\s*", "", part).strip()
                            val = re.split(r"(?i)\s*источник", val)[0].strip()
                            comment_text = val
                    elif re.match(r"(?i)^(?:автор|источник)\s*:", part):
                        pass
                    else:
                        if len(part) > 15:
                            content_texts.append(part)
            else:
                content_texts.append(t)

        for t in content_texts:
            cleaned = clean_question(t)
            if "?" in cleaned and len(cleaned) > 25 and not _META_MARKERS.match(cleaned):
                q_text = cleaned
                break

        if not q_text:
            candidates = [clean_question(t) for t in content_texts
                          if len(clean_question(t)) > 40 and not _META_MARKERS.match(clean_question(t))]
            if candidates:
                q_text = max(candidates, key=len)

        if q_text:
            return {"id": q_id, "url": url,
                    "question": q_text, "answer": a_text or "—",
                    "category": "Без категории", "source": "",
                    "zachot": zachot_text, "comment": comment_text}

    except Exception as e:
        print(f"[SELENIUM] Ошибка: {e}")
    finally:
        if driver:
            driver.quit()
    return None


def get_question(q_id: int) -> dict | None:
    data = fetch_via_nextjs_api(q_id)
    if data:
        print(f"[GET] ✅ Next.js API → ID={q_id}")
        return data
    data = fetch_via_selenium(q_id)
    if data:
        print(f"[GET] ✅ Selenium → ID={q_id}")
        return data
    return None


def find_question(diff_min: int, diff_max: int) -> dict | None:
    ids    = [random.randint(1, 50000) for _ in range(MAX_ATTEMPTS)]
    last_q = None
    for q_id in ids:
        q_data = get_question(q_id)
        if not q_data:
            continue
        diff = estimate_difficulty(q_data["question"], q_data["answer"])
        q_data["difficulty"] = diff
        last_q = q_data
        print(f"[FIND] ID={q_id} сложность={diff}, нужно {diff_min}-{diff_max}")
        # Пропускаем вопросы с раздаточным материалом
        q_lower = q_data["question"].lower()
        if any(x in q_lower for x in ["раздаточн", "на рисунке", "на фото", "на картинк",
                                        "перед вами", "посмотрите на", "внимание, рисунок",
                                        "см. рисунок", "см. фото"]):
            print(f"[FIND] ⏭ ID={q_id} — раздаточный материал, пропускаем")
            continue

        if diff_min <= diff <= diff_max:
            print("[FIND] ✅ Подходит, переводим...")
            q_data["translation"] = translate_to_armenian(q_data["question"])
            return q_data
        time.sleep(0.2)
    if last_q:
        last_q["translation"] = translate_to_armenian(last_q["question"])
    return last_q


def bar(diff) -> str:
    try:
        d = max(1, min(10, int(diff)))
        return f"{'█'*d}{'░'*(10-d)} {d}/10"
    except Exception:
        return "?"


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 <b>YsuShtok Bot</b> 🎯\n\n"
        "Հարցեր «Ի՞նչ, որտե՞ղ, ե՞րբ» խաղի համար\n"
        "<a href='https://gotquestions.online'>gotquestions.online</a>\n"
        "Ֆիլտրացում ըստ բարդության + թարգմանություն հայերեն 🇦🇲\n\n"
        "📌 <b>Հրամաններ՝</b>\n"
        "/question — միջին բարդություն (4–7)\n"
        "/easy — հեշտ (1–3)\n"
        "/hard — բարդ (8–10)",
        parse_mode="HTML", disable_web_page_preview=True,
    )


@dp.message(Command("question"))
async def handle_question(message: types.Message):
    await _send(message, 4, 7, "средней сложности")


@dp.message(Command("easy"))
async def handle_easy(message: types.Message):
    await _send(message, 1, 3, "лёгкий")


@dp.message(Command("hard"))
async def handle_hard(message: types.Message):
    await _send(message, 8, 10, "сложный")


async def _send(message: types.Message, diff_min: int, diff_max: int, label: str):
    wait = await message.answer(f"🔍 Ищу <b>{label}</b> вопрос…", parse_mode="HTML")

    loop   = asyncio.get_event_loop()
    q_data = await loop.run_in_executor(None, lambda: find_question(diff_min, diff_max))

    try:
        await bot.delete_message(message.chat.id, wait.message_id)
    except Exception:
        pass

    if not q_data:
        await message.answer(
            "❌ Не удалось получить вопрос.\n\n"
            "Убедись что установлены:\n"
            "<code>pip install selenium webdriver-manager deep-translator</code>\n"
            "И установлен Google Chrome.",
            parse_mode="HTML"
        )
        return

    diff  = q_data.get("difficulty", "?")
    trans = q_data.get("translation", "—")

    card = (
        f"🔗 <a href='{q_data['url']}'>Հարց #{q_data['id']}</a>\n"
        f"\n"
        f"<b>{q_data['question']}</b>\n\n"
        f"🇦🇲 <b>Հայերեն՝</b>\n<i>{trans}</i>\n\n"
        f"📊 <b>Բարդություն՝</b> {bar(diff)}"
    )

    if q_data.get("answer") and q_data["answer"] != "—":
        ans_hy = translate_to_armenian(q_data["answer"])
        card += f"\n\n✅ <b>Պատասխան՝</b> <tg-spoiler>{ans_hy}</tg-spoiler>"

    if q_data.get("zachot"):
        zachot_hy = translate_to_armenian(q_data["zachot"])
        card += f"\n☑️ <b>Հաշվվում է՝</b> <tg-spoiler>{zachot_hy}</tg-spoiler>"

    if q_data.get("comment"):
        comment_hy = translate_to_armenian(q_data["comment"])
        card += f"\n\n💬 <b>Մեկնաբանություն՝</b> <tg-spoiler>{comment_hy}</tg-spoiler>"

    await message.answer(card, parse_mode="HTML", disable_web_page_preview=True)
    print(f"[BOT] ✅ Отправлен ID={q_data['id']} сложность={diff}")


async def main():
    print("🚀 YsuShtok Bot запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())