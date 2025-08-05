TASK_ANALYSIS_PROMPT = """
Верните **JSON-массив** объектов, где каждый объект имеет поля:
- name: Короткое русское название задачи/активности/мероприятия
- sphere_text: Русское название сферы жизни (work, personal, health, learning и т. д.)
- sphere_page_id: id страницы-сферы (см. опции ниже; если подходящего блока нет — это поле НЕ добавлять)
- type:  
  • «ChatGPTактивность» — если элемент или тип явно не указан (дефолтное значение типа);  
  • «ChatGPTтаск» — если вначале упомянуты слова «задача», «task», «таск»;  
  • «ChatGPTмероприятие» — если вначале упомянуто слово «мероприятие».
- project: название проекта или `null`
- chatGPT_comment:
    * Для «ChatGPTактивность» — строка `"—"` (анализ не требуется).  
    * Для «ChatGPTтаск» — аналитика + конкретные шаги помощи. Структура комментария: 1. СДЕЛАНО: (да/нет в зависимости от того, есть ли в пункте 3. ПРЕДЛОЖЕНИЕ какой-то вариант или нет (то есть прочерк) )  2. ПРОМПТ: (Как промпт-инженер придумай промпт для chatGPT, который поможет решить задачу и оставь в нём плейсхолдеры под контекст который необходимо с промптом передать). 3. ПРЕДЛОЖЕНИЕ (Если задача простая («придумать текст») — то возьми промпт из предыдущего пункта, додумай контекст и сразу предложи готовое решение. Если комплексная задача или контекста не хватает, то оставь прочерк '-').  
    * Для «ChatGPTмероприятие» — рекомендации по подготовке (чек-лист, возможные материалы, список вопросов)

Task description: {task_text}
Time received: {timestamp}

Учитывайте контекст и приоритет. Если даты не указаны — выведите разумные (см. Rules).

### Sphere options
{sphere_block}

**Rules**
* Несколько элементов — несколько объектов в массиве.
* Каждый объект должен быть независим и завершён.
* Выбирайте сферу вдумчиво: сопоставляйте смысл описания с `Sphere options`; при сомнении возьмите ближайшую.
* **name** и **chatGPT_comment** должны быть на русском.
* Итог —валидный JSON-массив **без** кодовых блоков (```).
* Если элемент один — всё равно возвращайте массив из одного объекта.
"""

THOUGHT_ANALYSIS_PROMPT = """
Вы — личный мыслительный ассистент. Классифицируйте мысли ниже
по сфере жизни и дайте короткое осмысленное название.

Верните JSON-массив объектов:

- name: Короткое русское название
- sphere_page_id: id страницы-сферы (см. опции ниже; если подходящего блока нет — это поле НЕ добавлять)
- comment: раскрытие мысли / пояснение (1-2 предложения)

### Sphere options
{sphere_block}

Текст мыслей:
{thoughts}

Current time: {timestamp}

**Rules**
* Несколько элементов — несколько объектов в массиве.
* Каждый объект должен быть независим и завершён.
* Выбирайте сферу вдумчиво: сопоставляйте смысл описания с `Sphere options`; при сомнении возьмите ближайшую.
* **name** и **chatGPT_comment** должны быть на русском.
* Итог —валидный JSON-массив **без** кодовых блоков (```).
* Если элемент один — всё равно возвращайте массив из одного объекта.
"""


NOTION_MAPPING = {
    "name": "Name",
    "sphere": "Sphere",
    "start_date": "Start Date",
    "end_date": "End Date",
    "type": "type",
    "project": "Project",
    "chatGPT_comment": "ChatGPT"
}

TODAY_DASHBOARD_PROMPT = """Analyze the following dashboard message and fill in the GPT placeholders with personalized content. The message contains a user's daily schedule and habits.

Message:
{message}

Guidelines:
1. The summary should be concise but informative
2. The motto should be uplifting and relevant to the day's schedule
3. Habit times should be practical and consider the existing schedule
4. Relaxation activities should be diverse and consider the user's schedule
5. All times should be in Russian (e.g., "утром", "после обеда", "вечером")
6. Activities should be in Russian and be specific but not too long
7. Return several times to rest based on schedule - it is very important

Return only the text for message in telegram (without header like "Message in telegram")""" 