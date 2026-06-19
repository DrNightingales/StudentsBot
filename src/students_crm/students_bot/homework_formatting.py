from datetime import datetime


STATUS_OPTIONS = {
    'not_solved': 'Не решено',
    'review': 'На проверке',
    'correct': 'Пройдено',
    'incorrect': 'Провалено',
}
ANSWERING_MODE_LABELS = {'FREE': 'Свободный порядок', 'FIXED': 'Фиксированный порядок'}
QUESTION_TYPE_LABELS = {
    'open': 'Вопрос с развернутым ответом',
    'short': 'Задание с кратким ответом',
    'mcq': 'Задание со множественным выбором',
}


def _parse_deadline(text: str) -> str | None:
    cleaned = text.strip()
    if cleaned.endswith('Z'):
        cleaned = f'{cleaned[:-1]}+00:00'
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    return parsed.isoformat(timespec='seconds')


def _format_deadline(value: str | None) -> str:
    if not value:
        return '—'
    cleaned = value.strip()
    if cleaned.endswith('Z'):
        cleaned = f'{cleaned[:-1]}+00:00'
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return value
    weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
    weekday = weekdays[parsed.weekday()]
    return f'До {parsed:%H:%M %d.%m.%y} ({weekday})'


def _result_label(item) -> str:
    if not item.attempted:
        return 'Нет ответа'
    if item.question_type == 'open':
        return 'На проверке'
    points = item.points or 1
    if item.score is not None and 0.0 < item.score < points:
        return 'Частично верно'
    if item.is_correct == 1:
        return 'Верно'
    if item.is_correct == 0:
        return 'Неверно'
    return 'Результат неизвестен'


def _attempt_result_label(question, attempt) -> str:
    if question.question_type == 'open':
        return 'На проверке'
    points = question.points or 1
    if attempt.score is not None and 0.0 < attempt.score < points:
        return 'Частично верно'
    if attempt.is_correct == 1:
        return 'Верно'
    if attempt.is_correct == 0:
        return 'Неверно'
    return 'Результат неизвестен'


def _normalize_answer(text: str | None) -> str:
    return (text or '').strip().lower()


def _calculate_mcq_score(selected: set[int], correct: set[int], points: float) -> float:
    if not correct or points <= 0:
        return 0.0
    score = (len(selected & correct) - len(selected - correct)) * (points / len(correct))
    return max(0.0, score)
