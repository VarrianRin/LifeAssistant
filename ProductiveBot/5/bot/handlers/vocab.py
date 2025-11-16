# bot/handlers/vocab.py
import base64
import csv
import io
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

from aiogram import Router, F
from aiogram.types import Message, PhotoSize
from aiogram.fsm.context import FSMContext

from openai import OpenAI
from PIL import Image

router = Router()

CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "data", "vocab.csv")
CSV_PATH = os.path.abspath(CSV_PATH)

# Память последних записей per-user (in-memory; перезапустится — обнулится).
_last_by_user = {}

@dataclass
class VocabEntry:
    phrase: str
    context: str
    explain_en_phrase: str
    explain_en_context: str
    explain_ru: str
    created_at: str

def _ensure_csv_header():
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    if not os.path.exists(CSV_PATH) or os.stat(CSV_PATH).st_size == 0:
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "phrase",
                "context",
                "explain_en_phrase",
                "explain_en_context",
                "explain_ru",
                "created_at"
            ])

def _append_csv(entry: VocabEntry):
    _ensure_csv_header()
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            entry.phrase,
            entry.context,
            entry.explain_en_phrase,
            entry.explain_en_context,
            entry.explain_ru,
            entry.created_at
        ])

def _update_last_ru(uid: int, ru_text: str):
    # Дозапись русского объяснения в CSV: просто добавим новую строку с заполненным explain_ru,
    # чтобы не плодить сложную логику inplace-редакции CSV.
    last: Optional[VocabEntry] = _last_by_user.get(uid)
    if not last:
        return False
    updated = VocabEntry(
        phrase=last.phrase,
        context=last.context,
        explain_en_phrase=last.explain_en_phrase,
        explain_en_context=last.explain_en_context,
        explain_ru=ru_text,
        created_at=datetime.utcnow().isoformat()
    )
    _append_csv(updated)
    _last_by_user[uid] = updated
    return True

def _openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in bot/.env")
    return OpenAI(api_key=api_key)

def _b64_image_from_photo_bytes(img_bytes: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(img_bytes).decode("utf-8")

async def _download_photo_as_jpeg(message: Message) -> bytes:
    # Берём максимально большое фото
    photo: PhotoSize = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    file_bytes = await message.bot.download_file(file.file_path)
    raw = file_bytes.read()
    # Нормализуем в JPEG (на всякий случай)
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()

async def _extract_from_image_with_gpt(img_bytes: bytes) -> Tuple[str, str]:
    """
    Возвращает (phrase, context), используя GPT-4.1 (мультимодальный ввод).
    Предполагаем, что пользователь обвёл слово/фразу и рядом есть предложение контекста.
    """
    client = _openai_client()
    b64 = _b64_image_from_photo_bytes(img_bytes)

    prompt = (
        "You are an OCR+linguistics assistant. "
        "Given the photo of English text with a hand-highlighted word/phrase, "
        "1) extract EXACT highlighted word/phrase as `phrase` "
        "2) extract the **full sentence** that contains it as `context`.\n"
        "Return STRICT JSON with keys: phrase, context. No extra text."
    )

    resp = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": "Be concise. Answer in JSON."},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": b64}},
            ]}
        ],
        temperature=0.1,
    )
    txt = resp.choices[0].message.content.strip()
    # Простейший парс JSON (без внешних зависимостей)
    import json
    try:
        data = json.loads(txt)
        phrase = data.get("phrase", "").strip()
        context = data.get("context", "").strip()
        if not phrase or not context:
            raise ValueError("empty fields")
        return phrase, context
    except Exception:
        # fallback: возвращаем всё как пустое, верхний уровень обработает
        return "", ""

def _explain_in_english(phrase: str, context: str) -> Tuple[str, str]:
    client = _openai_client()
    sys = "You are an English tutor. Explain in simple, precise English."
    user = (
        f"PHRASE: {phrase}\n"
        f"CONTEXT SENTENCE: {context}\n\n"
        "Tasks:\n"
        "1) Explain the phrase meaning IN THIS CONTEXT (2–4 clear sentences).\n"
        "2) Briefly explain the whole sentence/context (1–2 sentences).\n"
        "Format:\n"
        "PHRASE_EXPLANATION:\n"
        "CONTEXT_EXPLANATION:\n"
    )
    resp = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "system", "content": sys},
                  {"role": "user", "content": user}],
        temperature=0.2,
    )
    txt = resp.choices[0].message.content.strip()
    # Разбор по маркерам
    m1 = re.search(r"PHRASE_EXPLANATION:\s*(.+?)(?:\nCONTEXT_EXPLANATION:|$)", txt, re.S)
    m2 = re.search(r"CONTEXT_EXPLANATION:\s*(.+)$", txt, re.S)
    exp_phrase = (m1.group(1).strip() if m1 else txt)[:2000]
    exp_context = (m2.group(1).strip() if m2 else "")[:2000]
    return exp_phrase, exp_context

def _explain_in_russian(phrase: str, context: str) -> str:
    client = _openai_client()
    sys = "Ты преподаватель английского. Объясняй по-русски, чётко и по делу."
    user = (
        f"Фраза: {phrase}\n"
        f"Предложение (контекст): {context}\n\n"
        "Дай понятное объяснение значения фразы И смысла предложения, "
        "с примерами (по возможности), коротко (4–6 предложений)."
    )
    resp = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "system", "content": sys},
                  {"role": "user", "content": user}],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()

def _parse_text_input(text: str) -> Tuple[str, str]:
    """
    Позволяет пихнуть текст без фото. Форматы:
      - "phrase | full context sentence"
      - просто предложение: попытаемся выделить первую **кавычками** фразу “...”
    """
    if "|" in text:
        parts = [p.strip() for p in text.split("|", 1)]
        if len(parts) == 2:
            return parts[0], parts[1]
    m = re.search(r"[\"“”‘’'](.+?)[\"“”‘’']", text)
    phrase = m.group(1).strip() if m else ""
    context = text.strip()
    return phrase, context

@router.message(F.text.casefold() == "не понял")
async def handle_not_understood(message: Message, state: FSMContext):
    uid = message.from_user.id
    last: Optional[VocabEntry] = _last_by_user.get(uid)
    if not last:
        await message.answer("Пока нет последнего элемента. Отправь фото/текст с фразой.")
        return
    ru = _explain_in_russian(last.phrase, last.context)
    _update_last_ru(uid, ru)
    await message.answer(ru)

@router.message(F.photo)
async def handle_photo(message: Message, state: FSMContext):
    try:
        img = await _download_photo_as_jpeg(message)
        phrase, context = await _extract_from_image_with_gpt(img)
        if not phrase or not context:
            await message.answer("Не смог извлечь фразу/контекст. Попробуй ближе кадрировать или добавить текстом.")
            return
        exp_phrase, exp_context = _explain_in_english(phrase, context)
        entry = VocabEntry(
            phrase=phrase,
            context=context,
            explain_en_phrase=exp_phrase,
            explain_en_context=exp_context,
            explain_ru="",
            created_at=datetime.utcnow().isoformat(),
        )
        _append_csv(entry)
        _last_by_user[message.from_user.id] = entry

        await message.answer(
            f"**Phrase:** {phrase}\n"
            f"**Context:** {context}\n\n"
            f"**EN (phrase):** {exp_phrase}\n"
            f"**EN (context):** {exp_context}\n\n"
            f"_Напиши «Не понял» — объясню по-русски и сохраню._",
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer(f"Ошибка обработки фото: {e}")

@router.message(F.text)
async def handle_text(message: Message, state: FSMContext):
    text = message.text.strip()
    phrase, context = _parse_text_input(text)
    if not context:
        await message.answer("Пришли фото с выделением или текст формата: phrase | full sentence.")
        return
    if not phrase:
        # если пользователь не выделил — попробуем объяснить ключевые слова всё равно
        phrase = phrase or "—"

    exp_phrase, exp_context = _explain_in_english(phrase, context)
    entry = VocabEntry(
        phrase=phrase,
        context=context,
        explain_en_phrase=exp_phrase,
        explain_en_context=exp_context,
        explain_ru="",
        created_at=datetime.utcnow().isoformat(),
    )
    _append_csv(entry)
    _last_by_user[message.from_user.id] = entry

    await message.answer(
        f"**Phrase:** {phrase}\n"
        f"**Context:** {context}\n\n"
        f"**EN (phrase):** {exp_phrase}\n"
        f"**EN (context):** {exp_context}\n\n"
        f"_Напиши «Не понял» — объясню по-русски и сохраню._",
        parse_mode="Markdown"
    )
