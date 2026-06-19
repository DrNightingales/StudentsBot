from aiogram.types import InlineKeyboardButton, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from students_crm.students_bot.homework_formatting import STATUS_OPTIONS


def _build_status_filter_keyboard(selected_codes: set[str]) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for code, label in STATUS_OPTIONS.items():
        prefix = '✅ ' if code in selected_codes else '☐ '
        builder.button(text=f'{prefix}{label}', callback_data=f'hw_status_toggle:{code}')
    builder.button(text='Показать задания', callback_data='hw_status_apply')
    builder.adjust(2, 2, 1)
    return builder


def _skip_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text='Пропустить')]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _done_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text='Готово')]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _skip_done_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text='Готово'), KeyboardButton(text='Пропустить')]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _attachments_keyboard(question_type: str | None, attachments) -> ReplyKeyboardMarkup:
    has_attachments = bool(attachments)
    if question_type == 'open':
        return _done_keyboard() if has_attachments else _skip_keyboard()
    return _skip_done_keyboard()


def _build_question_list_keyboard(assignment_id: int, progress_items) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for item in progress_items:
        icon = '🟩' if item.attempted else '🟦'
        builder.button(
            text=f'{icon} {item.order_index}',
            callback_data=f'hw_question:{assignment_id}:{item.question_id}',
        )
    builder.adjust(5)
    builder.row(
        InlineKeyboardButton(
            text='✅ Сдать задание',
            callback_data=f'hw_submit:{assignment_id}',
        )
    )
    return builder


def _build_back_to_questions_keyboard(assignment_id: int) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(
        text='⬅️ К списку вопросов (без сохранения)',
        callback_data=f'hw_question_back:{assignment_id}',
    )
    builder.adjust(1)
    return builder


def _build_submit_keyboard(assignment_id: int) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ Сдать задание', callback_data=f'hw_submit:{assignment_id}')
    builder.adjust(1)
    return builder


def _build_mcq_keyboard(
    assignment_id: int,
    question_id: int,
    options,
    selected_ids: set[int],
    include_back: bool = False,
) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for option in options:
        prefix = '✅ ' if option.id in selected_ids else '☐ '
        builder.button(
            text=f'{prefix}{option.option_text}',
            callback_data=f'hw_mcq_toggle:{assignment_id}:{question_id}:{option.id}',
        )
    builder.button(text='✅ Ответить', callback_data=f'hw_mcq_submit:{assignment_id}:{question_id}')
    if include_back:
        builder.button(
            text='⬅️ К списку вопросов (без сохранения)',
            callback_data=f'hw_question_back:{assignment_id}',
        )
    builder.adjust(1)
    return builder


def _build_admin_mcq_keyboard(options, selected_ids: set[int]) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for option in options:
        prefix = '✅ ' if option.id in selected_ids else '☐ '
        builder.button(
            text=f'{prefix}{option.option_text}',
            callback_data=f'draft_mcq_toggle:{option.id}',
        )
    builder.button(text='Готово', callback_data='draft_mcq_submit')
    builder.adjust(1)
    return builder
