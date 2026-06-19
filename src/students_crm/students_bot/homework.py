from datetime import datetime, timedelta
from html import escape

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardRemove,
    InlineKeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from students_crm.utils.constants import ADMIN_ID, DEBUG
from students_crm.students_bot.homework_formatting import (
    ANSWERING_MODE_LABELS,
    QUESTION_TYPE_LABELS,
    STATUS_OPTIONS,
    _attempt_result_label,
    _calculate_mcq_score,
    _format_deadline,
    _normalize_answer,
    _parse_deadline,
    _result_label,
)
from students_crm.students_bot.homework_keyboards import (
    _attachments_keyboard,
    _build_admin_mcq_keyboard,
    _build_back_to_questions_keyboard,
    _build_mcq_keyboard,
    _build_question_list_keyboard,
    _build_status_filter_keyboard,
    _build_submit_keyboard,
    _done_keyboard,
    _skip_keyboard,
)
from students_crm.students_bot.homework_states import (
    ADMIN_STATES,
    STUDENT_ASSIGNMENT_STATE,
    STUDENT_QUESTION_STATES,
    AdminAssignStates,
    AdminCreateStates,
    StudentAnswerStates,
)
from students_crm.db.routines import (
    add_homework_question,
    assign_template_to_student,
    create_homework_template,
    delete_homework_question,
    delete_homework_template,
    get_assignment_question_counts,
    get_assignment_max_attempt_index,
    get_assignment_view,
    get_attempt_count,
    get_homework_question,
    get_homework_template,
    get_latest_attempt_for_question,
    get_latest_draft_template,
    get_next_unanswered_question,
    get_registered_students,
    list_attempt_attachments,
    list_attempt_option_texts,
    list_homework_question_attachments,
    list_homework_question_options,
    list_homework_questions,
    list_homework_templates,
    list_assignment_question_progress,
    list_assignment_max_attempts,
    list_student_assignments_by_statuses,
    publish_homework_template,
    record_assignment_attempt,
    replace_homework_question_attachments,
    replace_homework_question_options,
    set_assignment_status,
    set_homework_question_correct_options,
    update_homework_question_answer,
    update_homework_question_points,
    update_homework_question_text,
    update_homework_template_fields,
)

router = Router()

SKIP_WORDS = {'skip', 'пропустить', '-'}
MAX_QUESTION_ATTACHMENTS = 1
MAX_STUDENT_ATTACHMENTS = 10
MAX_OPTIONS = 10
ASSIGNMENTS_PAGE_SIZE = 10
UI_MESSAGE_IDS: dict[int, list[int]] = {}
MAX_TRACKED_MESSAGES = 200


def _is_skip_message(text: str | None) -> bool:
    if not text:
        return False
    return text.strip().lower() in SKIP_WORDS


async def _track_message(state: FSMContext, message: Message | None) -> None:
    if not message:
        return
    data = await state.get_data()
    tracked = data.get('ui_message_ids', [])
    chat_id = message.chat.id
    if message.message_id not in tracked:
        tracked.append(message.message_id)
    await state.update_data(ui_message_ids=tracked)
    chat_tracked = UI_MESSAGE_IDS.setdefault(chat_id, [])
    if message.message_id not in chat_tracked:
        chat_tracked.append(message.message_id)
        if len(chat_tracked) > MAX_TRACKED_MESSAGES:
            del chat_tracked[:-MAX_TRACKED_MESSAGES]


async def _clear_tracked_messages(message: Message | None, state: FSMContext) -> None:
    if not message:
        return
    data = await state.get_data()
    chat_id = message.chat.id
    tracked = list(dict.fromkeys(data.get('ui_message_ids', []) + UI_MESSAGE_IDS.get(chat_id, [])))
    if not tracked:
        return
    for message_id in tracked:
        try:
            await message.bot.delete_message(chat_id, message_id)
        except Exception:
            continue
    await state.update_data(ui_message_ids=[])
    UI_MESSAGE_IDS[chat_id] = []


async def _send_tracked(message: Message, state: FSMContext, *args, **kwargs) -> Message:
    sent = await message.answer(*args, **kwargs)
    await _track_message(state, sent)
    return sent


async def _send_tracked_photo(message: Message, state: FSMContext, file_id: str, **kwargs) -> Message:
    sent = await message.answer_photo(file_id, **kwargs)
    await _track_message(state, sent)
    return sent


async def _send_tracked_document(message: Message, state: FSMContext, file_id: str, **kwargs) -> Message:
    sent = await message.answer_document(file_id, **kwargs)
    await _track_message(state, sent)
    return sent


def _extract_attachments(message: Message, limit: int = MAX_STUDENT_ATTACHMENTS) -> list[tuple[str, str]]:
    attachments: list[tuple[str, str]] = []
    if message.photo:
        attachments.append((message.photo[-1].file_id, 'photo'))
    if message.document:
        attachments.append((message.document.file_id, 'document'))
    return attachments[:limit]


async def _send_free_order_question_list(
    message: Message,
    assignment_id: int,
    student_tg_id: int,
    note: str | None = None,
    state: FSMContext | None = None,
    clear_previous: bool = True,
) -> None:
    progress = await list_assignment_question_progress(assignment_id, student_tg_id)
    if not progress:
        if state is not None:
            if clear_previous:
                await _clear_tracked_messages(message, state)
            await _send_tracked(message, state, 'В задании нет вопросов.')
        else:
            await message.answer('В задании нет вопросов.')
        return
    if state is not None:
        if clear_previous:
            await _clear_tracked_messages(message, state)
        await state.update_data(active_assignment_id=assignment_id)
        await state.set_state(StudentAnswerStates.in_assignment)
    legend = '🟦 - нет ответа\n🟩 - есть ответ'
    text = f'Выберите вопрос:\n{legend}'
    if note:
        text = f'{text}\n{note}'
    keyboard = _build_question_list_keyboard(assignment_id, progress)
    if state is not None:
        await _send_tracked(message, state, text, reply_markup=keyboard.as_markup())
    else:
        await message.answer(text, reply_markup=keyboard.as_markup())


async def _send_attempt_preview(
    message: Message,
    state: FSMContext,
    assignment,
    question,
    attempt,
    show_result: bool,
) -> None:
    await _clear_tracked_messages(message, state)
    attachments = await list_attempt_attachments(attempt.id)
    lines = [
        f'Вопрос #{question.order_index}: {escape(question.text)}',
        'Ваш предыдущий ответ:',
    ]
    if question.question_type == 'mcq':
        option_texts = await list_attempt_option_texts(attempt.id)
        if option_texts:
            options_label = ', '.join(escape(text) for text in option_texts)
            lines.append(f'Выбранные варианты: {options_label}')
        else:
            lines.append('Выбранные варианты: —')
    else:
        answer_label = escape(attempt.answer_text) if attempt.answer_text else '—'
        lines.append(f'Ответ: {answer_label}')
    lines.append(f'Вложения: {len(attachments)}' if attachments else 'Вложения: —')
    if show_result:
        lines.append(f'Результат: {_attempt_result_label(question, attempt)}')
    await _send_tracked(message, state, '\n'.join(lines), parse_mode='HTML')
    if attachments:
        await _send_attachments(message, attachments, state=state)
    builder = InlineKeyboardBuilder()
    builder.button(
        text='Редактировать',
        callback_data=f'hw_question_edit:{assignment.id}:{question.id}',
    )
    builder.button(text='Отменить', callback_data=f'hw_question_cancel:{assignment.id}')
    builder.adjust(2)
    await _send_tracked(message, state, 'Выберите действие:', reply_markup=builder.as_markup())


def _is_student_busy_state(state_name: str | None) -> bool:
    return state_name in STUDENT_QUESTION_STATES or state_name == STUDENT_ASSIGNMENT_STATE


async def _notify_student_busy(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    assignment_id = data.get('active_assignment_id')
    if assignment_id:
        await _send_tracked(
            message,
            state,
            'Сначала завершите текущее задание. Можно сдать его.',
            reply_markup=_build_submit_keyboard(assignment_id).as_markup(),
        )
    else:
        await _send_tracked(message, state, 'Сначала завершите текущий шаг.')


async def _notify_admin_busy(message: Message, state: FSMContext) -> None:
    state_name = await state.get_state()
    data = await state.get_data()
    if data.get('draft_id'):
        await _send_control_panel(message, state, note='Сначала завершите текущий режим.')
        return
    if _is_student_busy_state(state_name):
        await _notify_student_busy(message, state)
        return
    await _send_tracked(message, state, 'Сначала завершите текущий режим.')


async def _is_admin_busy(state: FSMContext) -> bool:
    state_name = await state.get_state()
    data = await state.get_data()
    if state_name in ADMIN_STATES:
        return True
    if _is_student_busy_state(state_name):
        return True
    if data.get('draft_id') is not None:
        return True
    if data.get('delete_template_id') is not None:
        return True
    return False


async def _get_remaining_attempts(
    assignment,
    student_tg_id: int,
    *,
    max_used: int | None = None,
) -> int | None:
    if assignment.max_attempts is None:
        return None
    if max_used is None:
        max_used = await get_assignment_max_attempt_index(assignment.id, student_tg_id)
    return max(0, assignment.max_attempts - max_used)


async def _assignment_attempts_line(
    assignment,
    student_tg_id: int,
    *,
    max_used: int | None = None,
) -> str:
    if assignment.max_attempts is None:
        if assignment.status == STATUS_OPTIONS['not_solved']:
            return 'Попытки: не ограничено'
        return 'Осталось попыток: не ограничено'
    if assignment.status == STATUS_OPTIONS['not_solved']:
        return f'Попытки: {assignment.max_attempts}'
    remaining = await _get_remaining_attempts(
        assignment,
        student_tg_id,
        max_used=max_used,
    )
    return f'Осталось попыток: {remaining}'


async def _send_assignment_list(
    message: Message,
    student_tg_id: int,
    statuses: list[str],
    page: int = 0,
    state: FSMContext | None = None,
) -> None:
    page_size = ASSIGNMENTS_PAGE_SIZE
    offset = page * page_size
    assignments = await list_student_assignments_by_statuses(
        student_tg_id,
        statuses,
        limit=page_size + 1,
        offset=offset,
    )
    if not assignments:
        empty_message = 'Больше заданий нет.' if page > 0 else 'Нет заданий с выбранным статусом.'
        if state is not None:
            await _clear_tracked_messages(message, state)
            await _send_tracked(message, state, empty_message)
        else:
            await message.answer(empty_message)
        return
    has_next = len(assignments) > page_size
    page_items = assignments[:page_size]
    if not page_items:
        if state is not None:
            await _clear_tracked_messages(message, state)
            await _send_tracked(message, state, 'Больше заданий нет.')
        else:
            await message.answer('Больше заданий нет.')
        return

    assignment_ids = [assignment.id for assignment in page_items]
    max_attempts_by_assignment = await list_assignment_max_attempts(student_tg_id, assignment_ids)
    lines: list[str] = []
    builder = InlineKeyboardBuilder()
    for idx, assignment in enumerate(page_items, start=1):
        max_used = max_attempts_by_assignment.get(assignment.id, 0)
        attempts_line = await _assignment_attempts_line(
            assignment,
            student_tg_id,
            max_used=max_used,
        )
        description = assignment.text or '—'
        soft_deadline = _format_deadline(assignment.soft_deadline)
        hard_deadline = _format_deadline(assignment.hard_deadline)
        lines.append(
            '\n'.join(
                [
                    f'{idx}. <b>{escape(assignment.title)}</b>',
                    f'Описание: {escape(description)}',
                    f'Дедлайн: мягкий {soft_deadline}, жесткий {hard_deadline}',
                    attempts_line,
                ]
            )
        )
        builder.row(
            InlineKeyboardButton(
                text=f'Открыть {idx}',
                callback_data=f'hw_assignment:{assignment.id}',
            )
        )

    if has_next:
        builder.row(
            InlineKeyboardButton(
                text='Далее ▶️',
                callback_data=f'hw_assignments_page:{page + 1}',
            )
        )

    if state is not None:
        await _clear_tracked_messages(message, state)
        await _send_tracked(
            message,
            state,
            '\n\n'.join(lines),
            reply_markup=builder.as_markup(),
            parse_mode='HTML',
        )
    else:
        await message.answer('\n\n'.join(lines), reply_markup=builder.as_markup(), parse_mode='HTML')


async def _submit_assignment(
    message: Message,
    state: FSMContext,
    assignment_id: int,
    student_tg_id: int,
) -> None:
    await _clear_tracked_messages(message, state)
    assignment = await get_assignment_view(assignment_id, student_tg_id)
    if not assignment:
        await _send_tracked(message, state, 'Задание не найдено.')
        return
    progress = await list_assignment_question_progress(assignment_id, student_tg_id)
    if not progress:
        await _send_tracked(message, state, 'В задании нет вопросов.')
        return
    if assignment.status not in (STATUS_OPTIONS['correct'], STATUS_OPTIONS['incorrect']):
        await set_assignment_status(assignment_id, STATUS_OPTIONS['review'])
    lines = [f'Вопрос {item.order_index}: {_result_label(item)}' for item in progress]
    await _send_tracked(message, state, 'Результаты по заданиям:\n' + '\n'.join(lines))
    await _send_tracked(message, state, 'Задание отправлено на проверку.')
    await state.clear()


async def _send_assignment_report(
    message: Message,
    assignment,
    student_tg_id: int,
    state: FSMContext | None = None,
) -> None:
    progress = await list_assignment_question_progress(assignment.id, student_tg_id)
    if not progress:
        if state is not None:
            await _clear_tracked_messages(message, state)
            await _send_tracked(message, state, 'В задании нет вопросов.')
        else:
            await message.answer('В задании нет вопросов.')
        return
    lines = [f'Вопрос {item.order_index}: {_result_label(item)}' for item in progress]
    if state is not None:
        await _clear_tracked_messages(message, state)
        await _send_tracked(message, state, 'Результаты по вопросам:\n' + '\n'.join(lines))
    else:
        await message.answer('Результаты по вопросам:\n' + '\n'.join(lines))
    attempts_line = await _assignment_attempts_line(assignment, student_tg_id)
    remaining = await _get_remaining_attempts(assignment, student_tg_id)
    if remaining is None or remaining > 0:
        builder = InlineKeyboardBuilder()
        builder.button(text='Новая попытка', callback_data=f'hw_retry:{assignment.id}')
        builder.adjust(1)
        if state is not None:
            await _send_tracked(
                message,
                state,
                f'{attempts_line}\nХотите попробовать снова?',
                reply_markup=builder.as_markup(),
            )
        else:
            await message.answer(f'{attempts_line}\nХотите попробовать снова?', reply_markup=builder.as_markup())
        return
    if state is not None:
        await _send_tracked(message, state, attempts_line)
    else:
        await message.answer(attempts_line)


async def _send_assignment_retry_prompt(
    message: Message,
    assignment,
    student_tg_id: int,
    state: FSMContext | None = None,
) -> None:
    progress = await list_assignment_question_progress(assignment.id, student_tg_id)
    if not progress:
        if state is not None:
            await _clear_tracked_messages(message, state)
            await _send_tracked(message, state, 'В задании нет вопросов.')
        else:
            await message.answer('В задании нет вопросов.')
        return
    lines = [f'Вопрос {item.order_index}: {_result_label(item)}' for item in progress]
    attempts_line = await _assignment_attempts_line(assignment, student_tg_id)
    summary = 'Прошлая попытка:\n' + '\n'.join(lines)
    if state is not None:
        await _clear_tracked_messages(message, state)
        await _send_tracked(message, state, f'{summary}\n{attempts_line}')
    else:
        await message.answer(f'{summary}\n{attempts_line}')
    builder = InlineKeyboardBuilder()
    builder.button(text='Редактировать', callback_data=f'hw_retry_edit:{assignment.id}')
    builder.button(text='Отменить', callback_data=f'hw_retry_cancel:{assignment.id}')
    builder.adjust(2)
    if state is not None:
        await _send_tracked(message, state, 'Хотите начать новую попытку?', reply_markup=builder.as_markup())
    else:
        await message.answer('Хотите начать новую попытку?', reply_markup=builder.as_markup())


async def _send_attachments(message: Message, attachments, state: FSMContext | None = None) -> None:
    for attachment in attachments:
        if attachment.file_type == 'photo':
            if state:
                await _send_tracked_photo(message, state, attachment.file_id)
            else:
                await message.answer_photo(attachment.file_id)
        else:
            if state:
                await _send_tracked_document(message, state, attachment.file_id)
            else:
                await message.answer_document(attachment.file_id)


async def _send_control_panel(message: Message, state: FSMContext, note: str | None = None) -> None:
    await _clear_tracked_messages(message, state)
    data = await state.get_data()
    draft_id = data.get('draft_id')
    current_question_id = data.get('current_question_id')
    if not draft_id:
        await _send_tracked(message, state, 'Черновик не найден. Используйте /assignments.')
        return

    template = await get_homework_template(draft_id)
    if not template:
        await _send_tracked(message, state, 'Черновик не найден. Используйте /assignments.')
        return

    questions = await list_homework_questions(draft_id)
    current_label = 'нет'
    if questions:
        if not current_question_id or all(q.id != current_question_id for q in questions):
            current_question_id = questions[0].id
            await state.update_data(current_question_id=current_question_id)
        for question in questions:
            if question.id == current_question_id:
                type_label = QUESTION_TYPE_LABELS.get(question.question_type, question.question_type)
                current_label = f'#{question.order_index} ({type_label})'
                break

    header_label = 'Задание' if template.is_published else 'Черновик'
    summary = [
        f'{header_label}: {template.title}',
        f'Режим: {ANSWERING_MODE_LABELS.get(template.answering_mode, template.answering_mode)}',
        f'Попытки: {template.max_attempts}',
        f'Вопросов: {len(questions)}',
        f'Текущий вопрос: {current_label}',
    ]
    if note:
        summary.append(note)

    builder = InlineKeyboardBuilder()
    builder.button(text='➕ Добавить вопрос', callback_data='draft:add')
    builder.button(text='⬅️ Предыдущий', callback_data='draft:prev')
    builder.button(text='➡️ Следующий', callback_data='draft:next')
    builder.button(text='✏️ Редактировать', callback_data='draft:edit')
    builder.button(text='🗑 Удалить', callback_data='draft:delete')
    builder.button(text='📋 Список вопросов', callback_data='draft:list')
    publish_label = '✅ Опубликовано' if template.is_published else '✅ Опубликовать'
    builder.button(text=publish_label, callback_data='draft:publish')
    builder.button(text='❌ Выйти', callback_data='draft:exit')
    builder.adjust(2)
    await _send_tracked(message, state, '\n'.join(summary), reply_markup=builder.as_markup())


@router.message(Command('assignments'))
async def command_assignments_handler(message: Message, state: FSMContext) -> None:
    if not message.from_user or message.from_user.id != ADMIN_ID:
        await _track_message(state, message)
        await _send_tracked(message, state, 'Эта команда доступна только администратору.')
        return

    if await _is_admin_busy(state):
        await _notify_admin_busy(message, state)
        return

    await _track_message(state, message)
    await _clear_tracked_messages(message, state)
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text='📝 Создать задание', callback_data='admin_menu:create')
    builder.button(text='✏️ Редактировать задание', callback_data='admin_menu:edit')
    builder.button(text='🗑 Удалить задание', callback_data='admin_menu:delete')
    builder.button(text='📌 Назначить студенту', callback_data='admin_menu:assign')
    builder.adjust(1)
    await _send_tracked(message, state, 'Меню заданий:', reply_markup=builder.as_markup())


@router.callback_query(F.data == 'admin_menu:create')
async def admin_menu_create(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    if await _is_admin_busy(state):
        await _notify_admin_busy(callback.message, state)
        await callback.answer()
        return

    draft = await get_latest_draft_template(callback.from_user.id)
    if draft:
        await _clear_tracked_messages(callback.message, state)
        builder = InlineKeyboardBuilder()
        builder.button(text=f'Продолжить "{draft.title}"', callback_data=f'draft_continue:{draft.id}')
        builder.button(text='Создать новое', callback_data='draft_new')
        builder.adjust(1)
        await _send_tracked(
            callback.message,
            state,
            'Найден черновик. Что делаем?',
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        return

    await state.set_state(AdminCreateStates.waiting_for_title)
    await _clear_tracked_messages(callback.message, state)
    await _send_tracked(callback.message, state, 'Введите название задания.')
    await callback.answer()


@router.callback_query(F.data == 'admin_menu:edit')
async def admin_menu_edit(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    if await _is_admin_busy(state):
        await _notify_admin_busy(callback.message, state)
        await callback.answer()
        return

    await state.clear()
    templates = await list_homework_templates(published_only=False, created_by_tg_id=callback.from_user.id)
    if not templates:
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(callback.message, state, 'Заданий для редактирования не найдено.')
        await callback.answer()
        return
    builder = InlineKeyboardBuilder()
    for template in templates:
        status_prefix = '✅' if template.is_published else '📝'
        builder.button(text=f'{status_prefix} {template.title}', callback_data=f'edit_template:{template.id}')
    builder.adjust(1)
    await _clear_tracked_messages(callback.message, state)
    await _send_tracked(
        callback.message,
        state,
        'Выберите задание для редактирования:',
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == 'admin_menu:delete')
async def admin_menu_delete(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    if await _is_admin_busy(state):
        await _notify_admin_busy(callback.message, state)
        await callback.answer()
        return

    await state.clear()
    templates = await list_homework_templates(published_only=False, created_by_tg_id=callback.from_user.id)
    if not templates:
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(callback.message, state, 'Заданий для удаления не найдено.')
        await callback.answer()
        return
    builder = InlineKeyboardBuilder()
    for template in templates:
        status_prefix = '✅' if template.is_published else '📝'
        builder.button(text=f'{status_prefix} {template.title}', callback_data=f'delete_template:{template.id}')
    builder.adjust(1)
    await _clear_tracked_messages(callback.message, state)
    await _send_tracked(
        callback.message,
        state,
        'Выберите задание для удаления:',
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith('delete_template:'))
async def admin_delete_template_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    template_id = int(callback.data.split(':', 1)[1])
    template = await get_homework_template(template_id)
    if not template:
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(callback.message, state, 'Задание не найдено.')
        await callback.answer()
        return
    await state.update_data(delete_template_id=template_id)
    builder = InlineKeyboardBuilder()
    builder.button(text='🗑 Удалить', callback_data='delete_template_confirm')
    builder.button(text='Отмена', callback_data='delete_template_cancel')
    builder.adjust(2)
    await _clear_tracked_messages(callback.message, state)
    await _send_tracked(
        callback.message,
        state,
        f'Удалить задание "{template.title}"? Будут удалены все назначения и ответы студентов.',
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == 'delete_template_cancel')
async def admin_delete_template_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    await state.clear()
    await _clear_tracked_messages(callback.message, state)
    await _send_tracked(callback.message, state, 'Удаление отменено.')
    await callback.answer()


@router.callback_query(F.data == 'delete_template_confirm')
async def admin_delete_template_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    data = await state.get_data()
    template_id = data.get('delete_template_id')
    if not template_id:
        await _send_tracked(callback.message, state, 'Задание не найдено.')
        await callback.answer()
        return
    result = await delete_homework_template(int(template_id))
    if not result:
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(callback.message, state, f'Не удалось удалить задание: {result.message}')
        await callback.answer()
        return
    await state.clear()
    await _clear_tracked_messages(callback.message, state)
    await _send_tracked(callback.message, state, 'Задание удалено.')
    await callback.answer()


@router.callback_query(F.data.startswith('edit_template:'))
async def admin_edit_template_select(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    template_id = int(callback.data.split(':', 1)[1])
    template = await get_homework_template(template_id)
    if not template:
        await _send_tracked(callback.message, state, 'Задание не найдено.')
        await callback.answer()
        return
    questions = await list_homework_questions(template_id)
    current_question_id = questions[0].id if questions else None
    await state.clear()
    await state.update_data(draft_id=template_id, current_question_id=current_question_id)
    await _send_control_panel(callback.message, state, note='Задание открыто для редактирования.')
    await callback.answer()


@router.callback_query(F.data.startswith('draft_continue:'))
async def admin_continue_draft(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    draft_id = int(callback.data.split(':', 1)[1])
    questions = await list_homework_questions(draft_id)
    current_question_id = questions[0].id if questions else None
    await state.clear()
    await state.update_data(draft_id=draft_id, current_question_id=current_question_id)
    await _send_control_panel(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == 'draft_new')
async def admin_start_new_draft(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    await state.clear()
    await state.set_state(AdminCreateStates.waiting_for_title)
    await _clear_tracked_messages(callback.message, state)
    await _send_tracked(callback.message, state, 'Введите название задания.')
    await callback.answer()


@router.message(AdminCreateStates.waiting_for_title, F.from_user.id == ADMIN_ID)
async def admin_draft_title_handler(message: Message, state: FSMContext) -> None:
    await _track_message(state, message)
    title = (message.text or '').strip()
    if not title:
        await _send_tracked(message, state, 'Пожалуйста, отправьте название задания.')
        return

    result = await create_homework_template(
        title=title,
        description=None,
        answering_mode='FREE',
        max_attempts=3,
        created_by_tg_id=message.from_user.id,
    )
    if not result:
        await _send_tracked(message, state, f'Не удалось создать черновик: {result.message}')
        return
    await state.update_data(draft_id=result.data, current_question_id=None)
    await state.set_state(AdminCreateStates.waiting_for_description)
    await _clear_tracked_messages(message, state)
    await _send_tracked(
        message,
        state,
        'Добавьте описание задания или нажмите "Пропустить".',
        reply_markup=_skip_keyboard(),
    )


@router.message(AdminCreateStates.waiting_for_description, F.from_user.id == ADMIN_ID)
async def admin_draft_description_handler(message: Message, state: FSMContext) -> None:
    await _track_message(state, message)
    description = None
    if not _is_skip_message(message.text):
        description = (message.text or '').strip()
        if not description:
            description = None

    data = await state.get_data()
    draft_id = data.get('draft_id')
    if not draft_id:
        await _send_tracked(message, state, 'Черновик не найден. Используйте /assignments.')
        await state.clear()
        return

    await update_homework_template_fields(draft_id, description=description)
    builder = InlineKeyboardBuilder()
    builder.button(text='Свободный порядок', callback_data='draft_mode:FREE')
    builder.button(text='Фиксированный порядок', callback_data='draft_mode:FIXED')
    builder.adjust(1)
    await _clear_tracked_messages(message, state)
    await _send_tracked(message, state, 'Выберите режим ответов:', reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith('draft_mode:'))
async def admin_draft_mode_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    mode = callback.data.split(':', 1)[1]
    data = await state.get_data()
    draft_id = data.get('draft_id')
    if not draft_id:
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(callback.message, state, 'Черновик не найден. Используйте /assignments.')
        await state.clear()
        await callback.answer()
        return

    await update_homework_template_fields(draft_id, answering_mode=mode)
    await state.set_state(AdminCreateStates.waiting_for_attempts)
    await _clear_tracked_messages(callback.message, state)
    await _send_tracked(
        callback.message,
        state,
        'Укажите число попыток (по умолчанию 3) или нажмите "Пропустить".',
        reply_markup=_skip_keyboard(),
    )
    await callback.answer()


@router.message(AdminCreateStates.waiting_for_attempts, F.from_user.id == ADMIN_ID)
async def admin_draft_attempts_handler(message: Message, state: FSMContext) -> None:
    await _track_message(state, message)
    attempts = 3
    if not _is_skip_message(message.text):
        try:
            attempts = int((message.text or '').strip())
        except ValueError:
            await _send_tracked(
                message,
                state,
                'Введите число попыток или нажмите "Пропустить".',
                reply_markup=_skip_keyboard(),
            )
            return
        if attempts < 1:
            await _send_tracked(message, state, 'Количество попыток должно быть не меньше 1.')
            return

    data = await state.get_data()
    draft_id = data.get('draft_id')
    if not draft_id:
        await _send_tracked(message, state, 'Черновик не найден. Используйте /assignments.')
        await state.clear()
        return

    await update_homework_template_fields(draft_id, max_attempts=attempts)
    await state.set_state(None)
    await _send_control_panel(message, state)


@router.callback_query(F.data == 'draft:add')
async def admin_add_question_start(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    builder = InlineKeyboardBuilder()
    for q_type, label in QUESTION_TYPE_LABELS.items():
        builder.button(text=label, callback_data=f'draft_qtype:{q_type}')
    builder.adjust(1)
    await _clear_tracked_messages(callback.message, state)
    await _send_tracked(
        callback.message,
        state,
        'Выберите тип вопроса:',
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith('draft_qtype:'))
async def admin_question_type_selected(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    question_type = callback.data.split(':', 1)[1]
    await state.update_data(question_type=question_type)
    await state.set_state(AdminCreateStates.waiting_for_question_text)
    await _clear_tracked_messages(callback.message, state)
    await _send_tracked(callback.message, state, 'Введите текст вопроса.')
    await callback.answer()


@router.message(AdminCreateStates.waiting_for_question_text, F.from_user.id == ADMIN_ID)
async def admin_question_text_handler(message: Message, state: FSMContext) -> None:
    await _track_message(state, message)
    data = await state.get_data()
    draft_id = data.get('draft_id')
    question_type = data.get('question_type')
    text = (message.text or message.caption or '').strip()
    attachments = _extract_attachments(message, MAX_QUESTION_ATTACHMENTS)
    if not draft_id:
        await _send_tracked(message, state, 'Черновик не найден. Используйте /assignments.')
        await state.clear()
        return
    if not question_type:
        await _send_tracked(message, state, 'Сначала выберите тип вопроса.')
        return
    if not text:
        await _send_tracked(
            message,
            state,
            'Пожалуйста, отправьте текст вопроса (можно в подписи к файлу).',
        )
        return

    result = await add_homework_question(
        template_id=draft_id,
        question_type=question_type,
        text=text,
        points=1.0,
    )
    if not result:
        await _send_tracked(message, state, f'Не удалось добавить вопрос: {result.message}')
        return
    if attachments:
        await state.update_data(question_id=result.data, pending_attachments=attachments)
        await _finalize_question_attachments(message, state)
        return
    await state.update_data(question_id=result.data, pending_attachments=[])
    await state.set_state(AdminCreateStates.waiting_for_question_attachments)
    if question_type == 'open':
        prompt = (
            'Отправьте одно вложение (фото/документ) или нажмите "Пропустить".'
        )
    else:
        prompt = (
            'Отправьте одно вложение (фото/документ) или нажмите "Пропустить".'
        )
    await _clear_tracked_messages(message, state)
    await _send_tracked(
        message,
        state,
        prompt,
        reply_markup=_attachments_keyboard(question_type, []),
    )


@router.message(AdminCreateStates.waiting_for_question_attachments, F.from_user.id == ADMIN_ID)
async def admin_question_attachments_handler(message: Message, state: FSMContext) -> None:
    await _track_message(state, message)
    data = await state.get_data()
    question_id = data.get('question_id')
    question_type = data.get('question_type')
    attachments = data.get('pending_attachments', [])

    new_attachments = _extract_attachments(message, MAX_QUESTION_ATTACHMENTS)
    if new_attachments:
        if attachments:
            await _send_tracked(
                message,
                state,
                'Можно добавить только одно вложение. Нажмите "Готово".',
                reply_markup=_attachments_keyboard(question_type, attachments),
            )
            return
        attachments.extend(new_attachments)
        await state.update_data(pending_attachments=attachments)
        await _send_tracked(
            message,
            state,
            'Вложение добавлено. Нажмите "Готово".',
            reply_markup=_attachments_keyboard(question_type, attachments),
        )
        return

    if not _is_skip_message(message.text) and (message.text or '').strip().lower() != 'готово':
        if question_type == 'open' and not attachments:
            prompt = 'Отправьте одно вложение или нажмите "Пропустить".'
        elif question_type == 'open':
            prompt = 'Отправьте одно вложение или нажмите "Готово".'
        else:
            prompt = 'Отправьте одно вложение или нажмите "Пропустить".'
        await _send_tracked(
            message,
            state,
            prompt,
            reply_markup=_attachments_keyboard(question_type, attachments),
        )
        return

    await _finalize_question_attachments(message, state)


async def _finalize_question_attachments(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    question_id = data.get('question_id')
    question_type = data.get('question_type')
    attachments = data.get('pending_attachments', [])

    if question_id is None or question_type is None:
        await _clear_tracked_messages(message, state)
        await _send_tracked(message, state, 'Не удалось сохранить вопрос. Используйте /assignments.')
        await state.clear()
        return

    if attachments:
        await replace_homework_question_attachments(question_id, attachments)

    if question_type == 'short':
        await _clear_tracked_messages(message, state)
        await state.set_state(AdminCreateStates.waiting_for_short_answer)
        await _send_tracked(message, state, 'Введите правильный ответ.')
        return

    if question_type == 'mcq':
        await _clear_tracked_messages(message, state)
        await state.set_state(AdminCreateStates.waiting_for_mcq_option)
        await state.update_data(mcq_options=[], editing_question=False)
        await _send_tracked(
            message,
            state,
            'Введите вариант ответа (или нажмите "Готово", когда закончите).',
            reply_markup=_done_keyboard(),
        )
        return

    if question_type == 'open':
        await _clear_tracked_messages(message, state)
        await state.set_state(AdminCreateStates.waiting_for_question_points)
        await _send_tracked(
            message,
            state,
            'Сколько баллов за вопрос? (по умолчанию 1) или нажмите "Пропустить".',
            reply_markup=_skip_keyboard(),
        )
        return

    await state.update_data(current_question_id=question_id)
    await state.set_state(None)
    await _send_control_panel(message, state, note='Вопрос добавлен.')


@router.message(AdminCreateStates.waiting_for_question_points, F.from_user.id == ADMIN_ID)
async def admin_question_points_handler(message: Message, state: FSMContext) -> None:
    await _track_message(state, message)
    points = 1.0
    if not _is_skip_message(message.text):
        raw = (message.text or '').strip().replace(',', '.')
        try:
            points = float(raw)
        except ValueError:
            await _send_tracked(
                message,
                state,
                'Введите число баллов или нажмите "Пропустить".',
                reply_markup=_skip_keyboard(),
            )
            return
        if points <= 0:
            await _send_tracked(message, state, 'Баллы должны быть больше 0.', reply_markup=_skip_keyboard())
            return

    data = await state.get_data()
    question_id = data.get('question_id')
    if not question_id:
        await _send_tracked(message, state, 'Вопрос не найден. Используйте /assignments.')
        await state.clear()
        return

    await update_homework_question_points(question_id, points)
    await state.update_data(current_question_id=question_id)
    await state.set_state(None)
    await _send_control_panel(message, state, note='Вопрос добавлен.')


@router.message(AdminCreateStates.waiting_for_short_answer, F.from_user.id == ADMIN_ID)
async def admin_question_short_answer_handler(message: Message, state: FSMContext) -> None:
    await _track_message(state, message)
    answer = (message.text or '').strip()
    if not answer:
        await _send_tracked(message, state, 'Пожалуйста, отправьте правильный ответ.')
        return

    data = await state.get_data()
    question_id = data.get('question_id')
    if not question_id:
        await _send_tracked(message, state, 'Вопрос не найден. Используйте /assignments.')
        await state.clear()
        return

    await update_homework_question_answer(question_id, answer)
    await state.update_data(current_question_id=question_id)
    await state.set_state(None)
    await _send_control_panel(message, state, note='Вопрос добавлен.')


@router.message(AdminCreateStates.waiting_for_mcq_option, F.from_user.id == ADMIN_ID)
async def admin_question_mcq_option_handler(message: Message, state: FSMContext) -> None:
    await _track_message(state, message)
    data = await state.get_data()
    options = data.get('mcq_options', [])
    question_id = data.get('question_id')
    if not question_id:
        await _send_tracked(message, state, 'Вопрос не найден. Используйте /assignments.')
        await state.clear()
        return

    text = (message.text or '').strip()
    if text.lower() == 'готово':
        if len(options) < 2:
            await _send_tracked(message, state, 'Нужно минимум 2 варианта ответа.')
            return
        await replace_homework_question_options(question_id, options)
        stored_options = await list_homework_question_options(question_id)
        await state.update_data(mcq_correct_ids=[])
        await state.set_state(AdminCreateStates.waiting_for_mcq_correct)
        keyboard = _build_admin_mcq_keyboard(stored_options, set())
        await _clear_tracked_messages(message, state)
        await _send_tracked(message, state, 'Отметьте правильные варианты:', reply_markup=keyboard.as_markup())
        return

    if not text:
        await _send_tracked(
            message,
            state,
            'Введите текст варианта ответа или нажмите "Готово".',
            reply_markup=_done_keyboard(),
        )
        return

    if len(options) >= MAX_OPTIONS:
        await _send_tracked(
            message,
            state,
            f'Достигнут лимит вариантов ({MAX_OPTIONS}). Нажмите "Готово".',
            reply_markup=_done_keyboard(),
        )
        return

    options.append(text)
    await state.update_data(mcq_options=options)
    await _send_tracked(
        message,
        state,
        f'Вариант добавлен ({len(options)}). Можно добавить еще или нажмите "Готово".',
        reply_markup=_done_keyboard(),
    )


@router.callback_query(AdminCreateStates.waiting_for_mcq_correct, F.data.startswith('draft_mcq_toggle:'))
async def admin_mcq_toggle_correct(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    option_id = int(callback.data.split(':', 1)[1])
    data = await state.get_data()
    selected = set(data.get('mcq_correct_ids', []))
    if option_id in selected:
        selected.remove(option_id)
    else:
        selected.add(option_id)
    await state.update_data(mcq_correct_ids=list(selected))
    options = await list_homework_question_options(data.get('question_id'))
    keyboard = _build_admin_mcq_keyboard(options, selected)
    await callback.message.edit_reply_markup(reply_markup=keyboard.as_markup())
    await callback.answer()


@router.callback_query(AdminCreateStates.waiting_for_mcq_correct, F.data == 'draft_mcq_submit')
async def admin_mcq_submit_correct(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    data = await state.get_data()
    question_id = data.get('question_id')
    selected = list(data.get('mcq_correct_ids', []))
    if not selected:
        await callback.answer('Выберите хотя бы один правильный вариант.', show_alert=True)
        return
    await set_homework_question_correct_options(question_id, selected)
    await state.update_data(current_question_id=question_id)
    await state.set_state(None)
    await _send_control_panel(callback.message, state, note='Вопрос добавлен.')
    await callback.answer()


@router.callback_query(F.data == 'draft:prev')
async def admin_prev_question(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    data = await state.get_data()
    draft_id = data.get('draft_id')
    current_question_id = data.get('current_question_id')
    questions = await list_homework_questions(draft_id)
    if not questions:
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(callback.message, state, 'Вопросов нет.')
        await callback.answer()
        return
    if current_question_id is None:
        await state.update_data(current_question_id=questions[0].id)
    else:
        indices = {q.id: idx for idx, q in enumerate(questions)}
        idx = indices.get(current_question_id, 0)
        new_idx = max(0, idx - 1)
        await state.update_data(current_question_id=questions[new_idx].id)
    await _send_control_panel(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == 'draft:next')
async def admin_next_question(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    data = await state.get_data()
    draft_id = data.get('draft_id')
    current_question_id = data.get('current_question_id')
    questions = await list_homework_questions(draft_id)
    if not questions:
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(callback.message, state, 'Вопросов нет.')
        await callback.answer()
        return
    if current_question_id is None:
        await state.update_data(current_question_id=questions[0].id)
    else:
        indices = {q.id: idx for idx, q in enumerate(questions)}
        idx = indices.get(current_question_id, 0)
        new_idx = min(len(questions) - 1, idx + 1)
        await state.update_data(current_question_id=questions[new_idx].id)
    await _send_control_panel(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == 'draft:list')
async def admin_list_questions(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    data = await state.get_data()
    draft_id = data.get('draft_id')
    questions = await list_homework_questions(draft_id)
    if not questions:
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(callback.message, state, 'Вопросов нет.')
        await callback.answer()
        return
    lines = [
        f'{q.order_index}. {q.text[:80]}'
        for q in questions
    ]
    builder = InlineKeyboardBuilder()
    for q in questions:
        builder.button(text=str(q.order_index), callback_data=f'draft_select:{q.id}')
    builder.adjust(5)
    await _clear_tracked_messages(callback.message, state)
    await _send_tracked(callback.message, state, '\n'.join(lines), reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith('draft_select:'))
async def admin_select_question(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    question_id = int(callback.data.split(':', 1)[1])
    await state.update_data(current_question_id=question_id)
    await _send_control_panel(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == 'draft:edit')
async def admin_edit_question_menu(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    data = await state.get_data()
    question_id = data.get('current_question_id')
    if not question_id:
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(callback.message, state, 'Сначала выберите вопрос.')
        await callback.answer()
        return
    question = await get_homework_question(question_id)
    if not question:
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(callback.message, state, 'Вопрос не найден.')
        await callback.answer()
        return
    builder = InlineKeyboardBuilder()
    builder.button(text='Текст', callback_data='draft_edit:text')
    builder.button(text='Вложения', callback_data='draft_edit:attachments')
    builder.button(text='Баллы', callback_data='draft_edit:points')
    if question.question_type == 'short':
        builder.button(text='Правильный ответ', callback_data='draft_edit:correct')
    if question.question_type == 'mcq':
        builder.button(text='Варианты', callback_data='draft_edit:options')
    builder.adjust(2)
    await _clear_tracked_messages(callback.message, state)
    await _send_tracked(callback.message, state, 'Что редактируем?', reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith('draft_edit:'))
async def admin_edit_question(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    action = callback.data.split(':', 1)[1]
    data = await state.get_data()
    question_id = data.get('current_question_id')
    if not question_id:
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(callback.message, state, 'Сначала выберите вопрос.')
        await callback.answer()
        return
    await state.update_data(edit_question_id=question_id, pending_attachments=[])
    if action == 'text':
        await state.set_state(AdminCreateStates.waiting_for_edit_text)
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(callback.message, state, 'Введите новый текст вопроса.')
    elif action == 'attachments':
        question = await get_homework_question(question_id)
        question_type = question.question_type if question else None
        await state.update_data(edit_question_type=question_type)
        await state.set_state(AdminCreateStates.waiting_for_edit_attachments)
        if question_type == 'open':
            prompt = (
                'Отправьте новое вложение (одно) или нажмите "Пропустить" (удалить вложения).'
            )
        else:
            prompt = (
                'Отправьте новое вложение (одно) или нажмите "Пропустить" (удалить вложения).'
            )
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(
            callback.message,
            state,
            prompt,
            reply_markup=_attachments_keyboard(question_type, []),
        )
    elif action == 'points':
        await state.set_state(AdminCreateStates.waiting_for_edit_points)
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(callback.message, state, 'Введите новое число баллов.')
    elif action == 'correct':
        await state.set_state(AdminCreateStates.waiting_for_edit_short_answer)
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(callback.message, state, 'Введите новый правильный ответ.')
    elif action == 'options':
        await state.set_state(AdminCreateStates.waiting_for_mcq_option)
        await state.update_data(mcq_options=[], editing_question=True, question_id=question_id)
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(
            callback.message,
            state,
            'Введите варианты ответа заново (старые будут заменены). '
            'Когда закончите, нажмите "Готово".',
            reply_markup=_done_keyboard(),
        )
    await callback.answer()


@router.message(AdminCreateStates.waiting_for_edit_text, F.from_user.id == ADMIN_ID)
async def admin_edit_question_text_handler(message: Message, state: FSMContext) -> None:
    await _track_message(state, message)
    text = (message.text or '').strip()
    if not text:
        await _send_tracked(message, state, 'Введите текст вопроса.')
        return
    data = await state.get_data()
    question_id = data.get('edit_question_id')
    await update_homework_question_text(question_id, text)
    await state.set_state(None)
    await _send_control_panel(message, state, note='Вопрос обновлен.')


@router.message(AdminCreateStates.waiting_for_edit_short_answer, F.from_user.id == ADMIN_ID)
async def admin_edit_question_answer_handler(message: Message, state: FSMContext) -> None:
    await _track_message(state, message)
    answer = (message.text or '').strip()
    if not answer:
        await _send_tracked(message, state, 'Введите правильный ответ.')
        return
    data = await state.get_data()
    question_id = data.get('edit_question_id')
    await update_homework_question_answer(question_id, answer)
    await state.set_state(None)
    await _send_control_panel(message, state, note='Правильный ответ обновлен.')


@router.message(AdminCreateStates.waiting_for_edit_points, F.from_user.id == ADMIN_ID)
async def admin_edit_question_points_handler(message: Message, state: FSMContext) -> None:
    await _track_message(state, message)
    raw = (message.text or '').strip().replace(',', '.')
    try:
        points = float(raw)
    except ValueError:
        await _send_tracked(message, state, 'Введите число баллов.')
        return
    if points <= 0:
        await _send_tracked(message, state, 'Баллы должны быть больше 0.')
        return
    data = await state.get_data()
    question_id = data.get('edit_question_id')
    await update_homework_question_points(question_id, points)
    await state.set_state(None)
    await _send_control_panel(message, state, note='Баллы обновлены.')


@router.message(AdminCreateStates.waiting_for_edit_attachments, F.from_user.id == ADMIN_ID)
async def admin_edit_question_attachments_handler(message: Message, state: FSMContext) -> None:
    await _track_message(state, message)
    data = await state.get_data()
    question_id = data.get('edit_question_id')
    attachments = data.get('pending_attachments', [])
    question_type = data.get('edit_question_type')

    new_attachments = _extract_attachments(message, MAX_QUESTION_ATTACHMENTS)
    if new_attachments:
        if attachments:
            await _send_tracked(
                message,
                state,
                'Можно добавить только одно вложение. Нажмите "Готово".',
                reply_markup=_attachments_keyboard(question_type, attachments),
            )
            return
        attachments.extend(new_attachments)
        await state.update_data(pending_attachments=attachments)
        await _send_tracked(
            message,
            state,
            'Вложение добавлено. Нажмите "Готово".',
            reply_markup=_attachments_keyboard(question_type, attachments),
        )
        return

    if _is_skip_message(message.text):
        await replace_homework_question_attachments(question_id, [])
        await state.set_state(None)
        await _send_control_panel(message, state, note='Вложения удалены.')
        return

    if (message.text or '').strip().lower() == 'готово':
        await replace_homework_question_attachments(question_id, attachments)
        await state.set_state(None)
        await _send_control_panel(message, state, note='Вложения обновлены.')
        return

    if question_type == 'open' and not attachments:
        prompt = 'Отправьте одно вложение или нажмите "Пропустить".'
    elif question_type == 'open':
        prompt = 'Отправьте одно вложение или нажмите "Готово".'
    else:
        prompt = 'Отправьте одно вложение или нажмите "Пропустить".'
    await _send_tracked(message, state, prompt, reply_markup=_attachments_keyboard(question_type, attachments))


@router.callback_query(F.data == 'draft:delete')
async def admin_delete_question(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    data = await state.get_data()
    question_id = data.get('current_question_id')
    if not question_id:
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(callback.message, state, 'Сначала выберите вопрос.')
        await callback.answer()
        return
    await delete_homework_question(question_id)
    questions = await list_homework_questions(data.get('draft_id'))
    new_current = questions[0].id if questions else None
    await state.update_data(current_question_id=new_current)
    await _send_control_panel(callback.message, state, note='Вопрос удален.')
    await callback.answer()


@router.callback_query(F.data == 'draft:publish')
async def admin_publish_assignment(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    data = await state.get_data()
    draft_id = data.get('draft_id')
    if not draft_id:
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(callback.message, state, 'Задание не найдено.')
        await callback.answer()
        return
    template = await get_homework_template(draft_id)
    if template and template.is_published:
        await callback.answer('Задание уже опубликовано.')
        return
    questions = await list_homework_questions(draft_id)
    if not questions:
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(callback.message, state, 'Нужно добавить хотя бы один вопрос.')
        await callback.answer()
        return
    await publish_homework_template(draft_id)
    await state.clear()
    await _clear_tracked_messages(callback.message, state)
    await _send_tracked(callback.message, state, 'Задание опубликовано.')
    await callback.answer()


@router.callback_query(F.data == 'draft:exit')
async def admin_exit_assignment(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    await state.clear()
    await _clear_tracked_messages(callback.message, state)
    await _send_tracked(callback.message, state, 'Режим создания завершен. Черновик сохранен.')
    await callback.answer()


@router.callback_query(F.data == 'admin_menu:assign')
async def admin_menu_assign(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    if await _is_admin_busy(state):
        await _notify_admin_busy(callback.message, state)
        await callback.answer()
        return

    await state.clear()
    students = await get_registered_students()
    if not students:
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(callback.message, state, 'Зарегистрированные студенты не найдены.')
        await callback.answer()
        return
    builder = InlineKeyboardBuilder()
    for student in students:
        label = student.username
        if student.tg_username:
            label = f'{student.username} (@{student.tg_username})'
        builder.button(text=label, callback_data=f'assign_student:{student.tg_id}')
    builder.adjust(1)
    await _clear_tracked_messages(callback.message, state)
    await _send_tracked(callback.message, state, 'Выберите студента:', reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith('assign_student:'))
async def admin_select_student(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    student_tg_id = int(callback.data.split(':', 1)[1])
    templates = await list_homework_templates(published_only=True)
    if not templates:
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(callback.message, state, 'Опубликованных заданий нет.')
        await callback.answer()
        return
    builder = InlineKeyboardBuilder()
    for template in templates:
        builder.button(text=template.title, callback_data=f'assign_template:{student_tg_id}:{template.id}')
    builder.adjust(1)
    await _clear_tracked_messages(callback.message, state)
    await _send_tracked(
        callback.message,
        state,
        'Выберите задание для назначения:',
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith('assign_template:'))
async def admin_select_template(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    _, student_id, template_id = callback.data.split(':')
    template = await get_homework_template(int(template_id))
    if not template:
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(callback.message, state, 'Задание не найдено.')
        await callback.answer()
        return
    await state.update_data(
        assign_student_id=int(student_id),
        assign_template_id=template.id,
        assign_title=template.title,
    )
    await state.set_state(AdminAssignStates.waiting_for_assign_soft_deadline)
    await _clear_tracked_messages(callback.message, state)
    await _send_tracked(
        callback.message,
        state,
        'Введите мягкий дедлайн (YYYY-MM-DD HH:MM) или нажмите "Пропустить".',
        reply_markup=_skip_keyboard(),
    )
    await callback.answer()


@router.message(AdminAssignStates.waiting_for_assign_soft_deadline, F.from_user.id == ADMIN_ID)
async def admin_assign_soft_deadline_handler(message: Message, state: FSMContext) -> None:
    await _track_message(state, message)
    if _is_skip_message(message.text):
        soft_deadline = (datetime.utcnow() + timedelta(days=6)).isoformat(timespec='seconds')
    else:
        soft_deadline = _parse_deadline(message.text or '')
        if not soft_deadline:
            await _send_tracked(
                message,
                state,
                'Не удалось распознать дату. Формат: YYYY-MM-DD HH:MM или нажмите "Пропустить".',
                reply_markup=_skip_keyboard(),
            )
            return
    await state.update_data(assign_soft_deadline=soft_deadline)
    await state.set_state(AdminAssignStates.waiting_for_assign_hard_deadline)
    await _clear_tracked_messages(message, state)
    await _send_tracked(
        message,
        state,
        'Введите жесткий дедлайн (YYYY-MM-DD HH:MM) или нажмите "Пропустить".',
        reply_markup=_skip_keyboard(),
    )


@router.message(AdminAssignStates.waiting_for_assign_hard_deadline, F.from_user.id == ADMIN_ID)
async def admin_assign_hard_deadline_handler(message: Message, state: FSMContext) -> None:
    await _track_message(state, message)
    if _is_skip_message(message.text):
        hard_deadline = (datetime.utcnow() + timedelta(days=7)).isoformat(timespec='seconds')
    else:
        hard_deadline = _parse_deadline(message.text or '')
        if not hard_deadline:
            await _send_tracked(
                message,
                state,
                'Не удалось распознать дату. Формат: YYYY-MM-DD HH:MM или нажмите "Пропустить".',
                reply_markup=_skip_keyboard(),
            )
            return
    data = await state.get_data()
    result = await assign_template_to_student(
        template_id=data.get('assign_template_id'),
        student_tg_id=data.get('assign_student_id'),
        title=data.get('assign_title'),
        soft_deadline=data.get('assign_soft_deadline'),
        hard_deadline=hard_deadline,
    )
    if not result:
        await _send_tracked(message, state, f'Не удалось назначить задание: {result.message}')
        return
    await state.clear()
    await _clear_tracked_messages(message, state)
    await _send_tracked(message, state, 'Задание назначено.')


@router.message(Command('homework'))
async def command_homework_handler(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    if message.from_user.id == ADMIN_ID and not DEBUG:
        await _track_message(state, message)
        await _send_tracked(message, state, 'Используйте /assignments для управления заданиями.')
        return
    if message.from_user.id == ADMIN_ID and await _is_admin_busy(state):
        await _notify_admin_busy(message, state)
        return
    state_name = await state.get_state()
    if _is_student_busy_state(state_name):
        await _notify_student_busy(message, state)
        return
    await _track_message(state, message)
    await _clear_tracked_messages(message, state)
    await state.clear()
    await state.update_data(status_filter_codes=['not_solved'])
    keyboard = _build_status_filter_keyboard({'not_solved'})
    await _send_tracked(
        message,
        state,
        'Выберите один или несколько статусов, затем нажмите "Показать задания".',
        reply_markup=keyboard.as_markup(),
    )


@router.callback_query(F.data.startswith('hw_status_toggle:'))
async def homework_status_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    state_name = await state.get_state()
    if _is_student_busy_state(state_name):
        await _notify_student_busy(callback.message, state)
        await callback.answer()
        return
    status_code = callback.data.split(':', 1)[1]
    if status_code not in STATUS_OPTIONS:
        await callback.answer()
        return
    data = await state.get_data()
    selected_codes = set(data.get('status_filter_codes') or [])
    if status_code in selected_codes:
        selected_codes.remove(status_code)
    else:
        selected_codes.add(status_code)
    await state.update_data(status_filter_codes=list(selected_codes))
    if callback.message:
        keyboard = _build_status_filter_keyboard(selected_codes)
        await callback.message.edit_reply_markup(reply_markup=keyboard.as_markup())
    await callback.answer()


@router.callback_query(F.data == 'hw_status_apply')
async def homework_status_apply(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user:
        await callback.answer()
        return
    state_name = await state.get_state()
    if _is_student_busy_state(state_name):
        await _notify_student_busy(callback.message, state)
        await callback.answer()
        return
    data = await state.get_data()
    selected_codes = [code for code in (data.get('status_filter_codes') or []) if code in STATUS_OPTIONS]
    if not selected_codes:
        await callback.answer('Выберите хотя бы один статус.', show_alert=True)
        return
    statuses = [STATUS_OPTIONS[code] for code in selected_codes]
    await state.update_data(status_filter_codes=selected_codes)
    await _send_assignment_list(callback.message, callback.from_user.id, statuses, page=0, state=state)
    await callback.answer()


@router.callback_query(F.data.startswith('hw_assignments_page:'))
async def homework_assignments_page(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user:
        await callback.answer()
        return
    state_name = await state.get_state()
    if _is_student_busy_state(state_name):
        await _notify_student_busy(callback.message, state)
        await callback.answer()
        return
    page = int(callback.data.split(':', 1)[1])
    data = await state.get_data()
    selected_codes = [code for code in (data.get('status_filter_codes') or []) if code in STATUS_OPTIONS]
    if not selected_codes:
        await _send_tracked(callback.message, state, 'Сначала выберите статус задания.')
        await callback.answer()
        return
    statuses = [STATUS_OPTIONS[code] for code in selected_codes]
    await _send_assignment_list(callback.message, callback.from_user.id, statuses, page=page, state=state)
    await callback.answer()


@router.callback_query(F.data.startswith('hw_assignment:'))
async def homework_assignment_selected(callback: CallbackQuery, state: FSMContext) -> None:
    assignment_id = int(callback.data.split(':', 1)[1])
    state_name = await state.get_state()
    data = await state.get_data()
    active_assignment_id = data.get('active_assignment_id')
    if state_name in STUDENT_QUESTION_STATES:
        await _notify_student_busy(callback.message, state)
        await callback.answer()
        return
    if state_name == STUDENT_ASSIGNMENT_STATE and active_assignment_id and active_assignment_id != assignment_id:
        await _notify_student_busy(callback.message, state)
        await callback.answer()
        return
    assignment = await get_assignment_view(assignment_id, callback.from_user.id)
    if not assignment:
        await _send_tracked(callback.message, state, 'Задание не найдено.')
        await callback.answer()
        return
    if assignment.status != STATUS_OPTIONS['not_solved']:
        await state.clear()
        await _send_assignment_report(callback.message, assignment, callback.from_user.id, state=state)
        await callback.answer()
        return
    if not assignment.template_id:
        await _send_tracked(
            callback.message,
            state,
            'Формат задания устарел и не поддерживается.',
        )
        await callback.answer()
        return

    await state.update_data(active_assignment_id=assignment_id)
    await state.set_state(StudentAnswerStates.in_assignment)
    if assignment.answering_mode == 'FIXED':
        question = await get_next_unanswered_question(assignment_id, callback.from_user.id)
        if not question:
            await _clear_tracked_messages(callback.message, state)
            await _send_tracked(callback.message, state, 'Все вопросы уже отвечены.')
            await callback.answer()
            return
        await _present_question(callback.message, state, assignment, question, callback.from_user.id)
        await callback.answer()
        return

    await _send_free_order_question_list(callback.message, assignment_id, callback.from_user.id, state=state)
    await callback.answer()


@router.callback_query(F.data.startswith('hw_submit:'))
async def homework_submit_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    assignment_id = int(callback.data.split(':', 1)[1])
    if not callback.from_user:
        await callback.answer()
        return
    state_name = await state.get_state()
    data = await state.get_data()
    active_assignment_id = data.get('active_assignment_id')
    if _is_student_busy_state(state_name) and active_assignment_id and active_assignment_id != assignment_id:
        await _notify_student_busy(callback.message, state)
        await callback.answer()
        return
    assignment = await get_assignment_view(assignment_id, callback.from_user.id)
    if not assignment:
        await _send_tracked(callback.message, state, 'Задание не найдено.')
        await callback.answer()
        return
    total, answered = await get_assignment_question_counts(assignment_id, callback.from_user.id)
    if answered < total:
        builder = InlineKeyboardBuilder()
        builder.button(text='Сдать', callback_data=f'hw_submit_confirm:{assignment_id}')
        builder.button(text='Вернуться', callback_data=f'hw_submit_cancel:{assignment_id}')
        builder.adjust(2)
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(
            callback.message,
            state,
            f'Вы ответили на {answered} из {total} вопросов. Сдать задание?',
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        return
    await _submit_assignment(callback.message, state, assignment_id, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith('hw_submit_confirm:'))
async def homework_submit_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    assignment_id = int(callback.data.split(':', 1)[1])
    if not callback.from_user:
        await callback.answer()
        return
    await _submit_assignment(callback.message, state, assignment_id, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith('hw_submit_cancel:'))
async def homework_submit_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    assignment_id = int(callback.data.split(':', 1)[1])
    if not callback.from_user:
        await callback.answer()
        return
    await _send_free_order_question_list(callback.message, assignment_id, callback.from_user.id, state=state)
    await callback.answer()


@router.callback_query(F.data.startswith('hw_retry:'))
async def homework_retry_assignment(callback: CallbackQuery, state: FSMContext) -> None:
    assignment_id = int(callback.data.split(':', 1)[1])
    if not callback.from_user:
        await callback.answer()
        return
    state_name = await state.get_state()
    data = await state.get_data()
    active_assignment_id = data.get('active_assignment_id')
    if _is_student_busy_state(state_name) and active_assignment_id and active_assignment_id != assignment_id:
        await _notify_student_busy(callback.message, state)
        await callback.answer()
        return
    assignment = await get_assignment_view(assignment_id, callback.from_user.id)
    if not assignment:
        await _send_tracked(callback.message, state, 'Задание не найдено.')
        await callback.answer()
        return
    remaining = await _get_remaining_attempts(assignment, callback.from_user.id)
    if assignment.max_attempts is not None and (remaining is not None and remaining <= 0):
        await _send_tracked(callback.message, state, 'Попытки закончились.')
        await callback.answer()
        return
    await _send_assignment_retry_prompt(callback.message, assignment, callback.from_user.id, state=state)
    await callback.answer()


@router.callback_query(F.data.startswith('hw_retry_edit:'))
async def homework_retry_edit(callback: CallbackQuery, state: FSMContext) -> None:
    assignment_id = int(callback.data.split(':', 1)[1])
    if not callback.from_user:
        await callback.answer()
        return
    state_name = await state.get_state()
    data = await state.get_data()
    active_assignment_id = data.get('active_assignment_id')
    if _is_student_busy_state(state_name) and active_assignment_id and active_assignment_id != assignment_id:
        await _notify_student_busy(callback.message, state)
        await callback.answer()
        return
    assignment = await get_assignment_view(assignment_id, callback.from_user.id)
    if not assignment:
        await _send_tracked(callback.message, state, 'Задание не найдено.')
        await callback.answer()
        return
    remaining = await _get_remaining_attempts(assignment, callback.from_user.id)
    if assignment.max_attempts is not None and (remaining is not None and remaining <= 0):
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(callback.message, state, 'Попытки закончились.')
        await callback.answer()
        return
    await set_assignment_status(assignment_id, STATUS_OPTIONS['not_solved'])
    await _clear_tracked_messages(callback.message, state)
    await _send_tracked(callback.message, state, 'Новая попытка начата.')
    if assignment.answering_mode == 'FIXED':
        await _send_tracked(
            callback.message,
            state,
            'Фиксированный порядок пока не поддерживается для новой попытки.',
        )
        await callback.answer()
        return
    await _send_free_order_question_list(
        callback.message,
        assignment_id,
        callback.from_user.id,
        state=state,
        clear_previous=False,
    )
    await callback.answer()


@router.callback_query(F.data.startswith('hw_retry_cancel:'))
async def homework_retry_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    assignment_id = int(callback.data.split(':', 1)[1])
    if not callback.from_user:
        await callback.answer()
        return
    assignment = await get_assignment_view(assignment_id, callback.from_user.id)
    if not assignment:
        await _send_tracked(callback.message, state, 'Задание не найдено.')
        await callback.answer()
        return
    await _send_assignment_report(callback.message, assignment, callback.from_user.id, state=state)
    await callback.answer()


@router.callback_query(F.data.startswith('hw_question:'))
async def homework_question_selected(callback: CallbackQuery, state: FSMContext) -> None:
    _, assignment_id, question_id = callback.data.split(':')
    state_name = await state.get_state()
    data = await state.get_data()
    if state_name in STUDENT_QUESTION_STATES:
        await _notify_student_busy(callback.message, state)
        await callback.answer()
        return
    if state_name != STUDENT_ASSIGNMENT_STATE:
        await _send_tracked(callback.message, state, 'Сначала откройте задание.')
        await callback.answer()
        return
    active_assignment_id = data.get('active_assignment_id')
    if active_assignment_id and int(assignment_id) != int(active_assignment_id):
        await _notify_student_busy(callback.message, state)
        await callback.answer()
        return
    assignment = await get_assignment_view(int(assignment_id), callback.from_user.id)
    if not assignment:
        await _send_tracked(callback.message, state, 'Задание не найдено.')
        await callback.answer()
        return
    question = await get_homework_question(int(question_id))
    if not question or question.assignment_id != assignment.template_id:
        await _send_tracked(callback.message, state, 'Вопрос не найден.')
        await callback.answer()
        return
    attempt = await get_latest_attempt_for_question(int(assignment_id), question.id, callback.from_user.id)
    if attempt:
        show_result = assignment.status != STATUS_OPTIONS['not_solved']
        await _send_attempt_preview(callback.message, state, assignment, question, attempt, show_result=show_result)
        await callback.answer()
        return
    await _present_question(callback.message, state, assignment, question, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith('hw_question_edit:'))
async def homework_question_edit(callback: CallbackQuery, state: FSMContext) -> None:
    _, assignment_id, question_id = callback.data.split(':')
    if not callback.from_user:
        await callback.answer()
        return
    state_name = await state.get_state()
    data = await state.get_data()
    if state_name in STUDENT_QUESTION_STATES:
        await _notify_student_busy(callback.message, state)
        await callback.answer()
        return
    if state_name != STUDENT_ASSIGNMENT_STATE:
        await _send_tracked(callback.message, state, 'Сначала откройте задание.')
        await callback.answer()
        return
    active_assignment_id = data.get('active_assignment_id')
    if active_assignment_id and int(assignment_id) != int(active_assignment_id):
        await _notify_student_busy(callback.message, state)
        await callback.answer()
        return
    assignment = await get_assignment_view(int(assignment_id), callback.from_user.id)
    if not assignment:
        await _send_tracked(callback.message, state, 'Задание не найдено.')
        await callback.answer()
        return
    question = await get_homework_question(int(question_id))
    if not question or question.assignment_id != assignment.template_id:
        await _send_tracked(callback.message, state, 'Вопрос не найден.')
        await callback.answer()
        return
    await state.update_data(active_assignment_id=int(assignment_id))
    await _present_question(callback.message, state, assignment, question, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith('hw_question_cancel:'))
async def homework_question_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    assignment_id = int(callback.data.split(':', 1)[1])
    if not callback.from_user:
        await callback.answer()
        return
    assignment = await get_assignment_view(assignment_id, callback.from_user.id)
    if not assignment:
        await _send_tracked(callback.message, state, 'Задание не найдено.')
        await callback.answer()
        return
    await state.update_data(active_assignment_id=assignment_id)
    await state.set_state(StudentAnswerStates.in_assignment)
    if assignment.answering_mode == 'FIXED':
        await _post_answer_flow(callback.message, state, assignment_id, callback.from_user.id, assignment.answering_mode)
        await callback.answer()
        return
    await _send_free_order_question_list(callback.message, assignment_id, callback.from_user.id, state=state)
    await callback.answer()


@router.callback_query(F.data.startswith('hw_question_back:'))
async def homework_question_back(callback: CallbackQuery, state: FSMContext) -> None:
    assignment_id = int(callback.data.split(':', 1)[1])
    if not callback.from_user:
        await callback.answer()
        return
    data = await state.get_data()
    active_assignment_id = data.get('active_assignment_id')
    if active_assignment_id and active_assignment_id != assignment_id:
        await _notify_student_busy(callback.message, state)
        await callback.answer()
        return
    assignment = await get_assignment_view(assignment_id, callback.from_user.id)
    if not assignment:
        await _send_tracked(callback.message, state, 'Задание не найдено.')
        await callback.answer()
        return
    if assignment.answering_mode == 'FIXED':
        await _send_tracked(
            callback.message,
            state,
            'Фиксированный порядок: список вопросов недоступен.',
        )
        await callback.answer()
        return
    await state.update_data(active_assignment_id=assignment_id)
    await state.set_state(StudentAnswerStates.in_assignment)
    await _clear_tracked_messages(callback.message, state)
    await _send_tracked(
        callback.message,
        state,
        'Возвращаю к списку вопросов.',
        reply_markup=ReplyKeyboardRemove(),
    )
    await _send_free_order_question_list(
        callback.message,
        assignment_id,
        callback.from_user.id,
        state=state,
        clear_previous=False,
    )
    await callback.answer()


async def _present_question(
    message: Message,
    state: FSMContext,
    assignment,
    question,
    user_id: int,
) -> None:
    await _clear_tracked_messages(message, state)
    prompt = f'Вопрос #{question.order_index}:\n{question.text}'
    if question.question_type == 'mcq':
        options = await list_homework_question_options(question.id)
        await state.update_data(
            mcq_selected=[],
            mcq_question_id=question.id,
            mcq_assignment_id=assignment.id,
            mcq_owner_id=user_id,
            mcq_answering_mode=assignment.answering_mode,
        )
        await state.set_state(StudentAnswerStates.waiting_for_mcq_selection)
        keyboard = _build_mcq_keyboard(
            assignment.id,
            question.id,
            options,
            set(),
            include_back=assignment.answering_mode == 'FREE',
        )
        attachments = await list_homework_question_attachments(question.id)
        if attachments:
            await _send_tracked(message, state, prompt)
            attachment = attachments[0]
            if attachment.file_type == 'photo':
                await _send_tracked_photo(
                    message,
                    state,
                    attachment.file_id,
                    reply_markup=keyboard.as_markup(),
                )
            else:
                await _send_tracked_document(
                    message,
                    state,
                    attachment.file_id,
                    reply_markup=keyboard.as_markup(),
                )
        else:
            await _send_tracked(message, state, prompt, reply_markup=keyboard.as_markup())
        return

    await state.update_data(
        answer_assignment_id=assignment.id,
        answer_question_id=question.id,
        answer_question_type=question.question_type,
        answer_answering_mode=assignment.answering_mode,
    )
    await _send_tracked(message, state, prompt)
    attachments = await list_homework_question_attachments(question.id)
    if attachments:
        await _send_attachments(message, attachments, state=state)
    if question.question_type == 'short':
        await state.set_state(StudentAnswerStates.waiting_for_text_answer)
        if assignment.answering_mode == 'FREE':
            await _send_tracked(
                message,
                state,
                'Введите краткий ответ.',
                reply_markup=_build_back_to_questions_keyboard(assignment.id).as_markup(),
            )
        else:
            await _send_tracked(message, state, 'Введите краткий ответ.')
        return

    await state.update_data(open_answer_text=None, open_attachments=[])
    await state.set_state(StudentAnswerStates.waiting_for_open_text)
    if assignment.answering_mode == 'FREE':
        await _send_tracked(
            message,
            state,
            'Можно вернуться к списку вопросов.',
            reply_markup=_build_back_to_questions_keyboard(assignment.id).as_markup(),
        )
    await _send_tracked(
        message,
        state,
        'Отправьте ответ сообщением или нажмите "Пропустить". Можно приложить до 10 файлов или фото.',
        reply_markup=_skip_keyboard(),
    )
    return


@router.callback_query(StudentAnswerStates.waiting_for_mcq_selection, F.data.startswith('hw_mcq_toggle:'))
async def homework_mcq_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if callback.from_user.id != data.get('mcq_owner_id'):
        await callback.answer()
        return
    _, assignment_id, question_id, option_id = callback.data.split(':')
    if int(question_id) != data.get('mcq_question_id'):
        await callback.answer()
        return
    selected = set(data.get('mcq_selected', []))
    option_id = int(option_id)
    if option_id in selected:
        selected.remove(option_id)
    else:
        selected.add(option_id)
    await state.update_data(mcq_selected=list(selected))
    options = await list_homework_question_options(int(question_id))
    keyboard = _build_mcq_keyboard(
        int(assignment_id),
        int(question_id),
        options,
        selected,
        include_back=data.get('mcq_answering_mode') == 'FREE',
    )
    await callback.message.edit_reply_markup(reply_markup=keyboard.as_markup())
    await callback.answer()


@router.callback_query(StudentAnswerStates.waiting_for_mcq_selection, F.data.startswith('hw_mcq_submit:'))
async def homework_mcq_submit(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if callback.from_user.id != data.get('mcq_owner_id'):
        await callback.answer()
        return
    _, assignment_id, question_id = callback.data.split(':')
    assignment_id = int(assignment_id)
    question_id = int(question_id)
    selected = set(data.get('mcq_selected', []))
    if not selected:
        await callback.answer('Выберите хотя бы один вариант.', show_alert=True)
        return

    assignment = await get_assignment_view(assignment_id, callback.from_user.id)
    if not assignment:
        await _send_tracked(callback.message, state, 'Задание не найдено.')
        await callback.answer()
        return
    attempt_count = await get_attempt_count(assignment_id, question_id, callback.from_user.id)
    if assignment.max_attempts is not None and attempt_count >= assignment.max_attempts:
        await _clear_tracked_messages(callback.message, state)
        await _send_tracked(callback.message, state, 'Лимит попыток исчерпан.')
        await state.set_state(StudentAnswerStates.in_assignment)
        await _post_answer_flow(
            callback.message,
            state,
            assignment_id,
            callback.from_user.id,
            assignment.answering_mode,
            clear_previous=False,
        )
        await callback.answer()
        return

    question = await get_homework_question(question_id)
    points = question.points if question else 1.0
    options = await list_homework_question_options(question_id)
    correct_ids = {opt.id for opt in options if opt.is_correct}
    score = _calculate_mcq_score(selected, correct_ids, points)
    is_correct = 1 if score >= points and points > 0 else 0
    await record_assignment_attempt(
        assignment_id=assignment_id,
        question_id=question_id,
        student_tg_id=callback.from_user.id,
        attempt_index=attempt_count + 1,
        answer_text=None,
        is_correct=is_correct,
        score=score,
        selected_option_ids=list(selected),
    )
    await state.update_data(mcq_selected=[])
    await state.set_state(StudentAnswerStates.in_assignment)
    await _clear_tracked_messages(callback.message, state)
    await _send_tracked(callback.message, state, 'Ответ сохранен.')
    await _post_answer_flow(
        callback.message,
        state,
        assignment_id,
        callback.from_user.id,
        assignment.answering_mode,
        clear_previous=False,
    )
    await callback.answer()


async def _finalize_open_answer(
    message: Message,
    state: FSMContext,
    assignment_id: int,
    question_id: int,
    answering_mode: str,
    answer_text: str | None,
    attachments: list[tuple[str, str]],
    attempt_index: int | None = None,
) -> None:
    attempt_count = attempt_index
    if attempt_count is None:
        attempt_count = await get_attempt_count(assignment_id, question_id, message.from_user.id)
        attempt_count += 1
    await record_assignment_attempt(
        assignment_id=assignment_id,
        question_id=question_id,
        student_tg_id=message.from_user.id,
        attempt_index=attempt_count,
        answer_text=answer_text,
        is_correct=None,
        score=None,
        attachments=attachments,
    )
    await state.update_data(
        open_answer_text=None,
        open_attachments=[],
        open_attempt_index=None,
    )
    await state.set_state(StudentAnswerStates.in_assignment)
    await _clear_tracked_messages(message, state)
    await _send_tracked(message, state, 'Ответ сохранен.', reply_markup=ReplyKeyboardRemove())
    await _post_answer_flow(
        message,
        state,
        assignment_id,
        message.from_user.id,
        answering_mode,
        clear_previous=False,
    )


@router.message(StudentAnswerStates.waiting_for_open_text)
async def homework_open_text_answer(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    await _track_message(state, message)
    data = await state.get_data()
    assignment_id = data.get('answer_assignment_id')
    question_id = data.get('answer_question_id')
    answering_mode = data.get('answer_answering_mode')
    if not assignment_id or not question_id:
        await _clear_tracked_messages(message, state)
        await _send_tracked(message, state, 'Не удалось обработать ответ.')
        await state.clear()
        return

    assignment = await get_assignment_view(assignment_id, message.from_user.id)
    if not assignment:
        await _clear_tracked_messages(message, state)
        await _send_tracked(message, state, 'Задание не найдено.')
        await state.clear()
        return

    attempt_count = await get_attempt_count(assignment_id, question_id, message.from_user.id)
    if assignment.max_attempts is not None and attempt_count >= assignment.max_attempts:
        await _clear_tracked_messages(message, state)
        await _send_tracked(
            message,
            state,
            'Лимит попыток исчерпан.',
            reply_markup=ReplyKeyboardRemove(),
        )
        await state.set_state(StudentAnswerStates.in_assignment)
        await _post_answer_flow(
            message,
            state,
            assignment_id,
            message.from_user.id,
            answering_mode,
            clear_previous=False,
        )
        return

    raw_text = message.text or message.caption or ''
    text = raw_text.strip()
    skip_requested = _is_skip_message(raw_text)
    attachments = _extract_attachments(message, MAX_STUDENT_ATTACHMENTS)

    if not text and not attachments and not skip_requested:
        await _send_tracked(
            message,
            state,
            'Отправьте ответ сообщением или нажмите "Пропустить".',
            reply_markup=_skip_keyboard(),
        )
        return

    if skip_requested:
        text = ''
    answer_text = text if text else None

    await state.update_data(
        open_answer_text=answer_text,
        open_attachments=attachments,
        open_attempt_index=attempt_count + 1,
    )
    await state.set_state(StudentAnswerStates.waiting_for_open_attachments)
    await _clear_tracked_messages(message, state)

    if attachments:
        if len(attachments) >= MAX_STUDENT_ATTACHMENTS:
            await _send_tracked(
                message,
                state,
                'Достигнут лимит вложений (10).',
                reply_markup=ReplyKeyboardRemove(),
            )
            await _finalize_open_answer(
                message,
                state,
                assignment_id,
                question_id,
                answering_mode,
                answer_text,
                attachments,
                attempt_index=attempt_count + 1,
            )
            return
        await _send_tracked(
            message,
            state,
            'Вложение добавлено. Можно отправить еще или нажмите "Готово".',
            reply_markup=_attachments_keyboard('open', attachments),
        )
        return

    await _send_tracked(
        message,
        state,
        'Отправьте вложения (по одному, максимум 10) или нажмите "Пропустить".',
        reply_markup=_attachments_keyboard('open', attachments),
    )


@router.message(StudentAnswerStates.waiting_for_open_attachments)
async def homework_open_attachments(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    await _track_message(state, message)
    data = await state.get_data()
    assignment_id = data.get('answer_assignment_id')
    question_id = data.get('answer_question_id')
    answering_mode = data.get('answer_answering_mode')
    answer_text = data.get('open_answer_text')
    attachments = data.get('open_attachments', [])
    attempt_index = data.get('open_attempt_index')
    if not assignment_id or not question_id:
        await _clear_tracked_messages(message, state)
        await _send_tracked(message, state, 'Не удалось обработать ответ.')
        await state.clear()
        return

    if _is_skip_message(message.text) or (message.text or '').strip().lower() == 'готово':
        await _finalize_open_answer(
            message,
            state,
            assignment_id,
            question_id,
            answering_mode,
            answer_text,
            attachments,
            attempt_index=attempt_index,
        )
        return

    new_attachments = _extract_attachments(message, MAX_STUDENT_ATTACHMENTS)
    if not new_attachments:
        if not attachments:
            prompt = 'Отправьте вложение или нажмите "Пропустить".'
        else:
            prompt = 'Отправьте вложение или нажмите "Готово".'
        await _send_tracked(message, state, prompt, reply_markup=_attachments_keyboard('open', attachments))
        return

    if len(attachments) >= MAX_STUDENT_ATTACHMENTS:
        await _send_tracked(
            message,
            state,
            'Достигнут лимит вложений (10).',
            reply_markup=ReplyKeyboardRemove(),
        )
        await _finalize_open_answer(
            message,
            state,
            assignment_id,
            question_id,
            answering_mode,
            answer_text,
            attachments,
            attempt_index=attempt_index,
        )
        return

    attachments.extend(new_attachments)
    attachments = attachments[:MAX_STUDENT_ATTACHMENTS]
    await state.update_data(open_attachments=attachments)

    if len(attachments) >= MAX_STUDENT_ATTACHMENTS:
        await _send_tracked(
            message,
            state,
            'Достигнут лимит вложений (10).',
            reply_markup=ReplyKeyboardRemove(),
        )
        await _finalize_open_answer(
            message,
            state,
            assignment_id,
            question_id,
            answering_mode,
            answer_text,
            attachments,
            attempt_index=attempt_index,
        )
        return

    await _send_tracked(
        message,
        state,
        'Вложение добавлено. Можно отправить еще или нажмите "Готово".',
        reply_markup=_attachments_keyboard('open', attachments),
    )


@router.message(StudentAnswerStates.waiting_for_text_answer)
async def homework_text_answer(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    await _track_message(state, message)
    data = await state.get_data()
    assignment_id = data.get('answer_assignment_id')
    question_id = data.get('answer_question_id')
    question_type = data.get('answer_question_type')
    answering_mode = data.get('answer_answering_mode')
    if not assignment_id or not question_id or not question_type:
        await _clear_tracked_messages(message, state)
        await _send_tracked(message, state, 'Не удалось обработать ответ.')
        await state.clear()
        return

    assignment = await get_assignment_view(assignment_id, message.from_user.id)
    if not assignment:
        await _clear_tracked_messages(message, state)
        await _send_tracked(message, state, 'Задание не найдено.')
        await state.clear()
        return

    attempt_count = await get_attempt_count(assignment_id, question_id, message.from_user.id)
    if assignment.max_attempts is not None and attempt_count >= assignment.max_attempts:
        await _clear_tracked_messages(message, state)
        await _send_tracked(
            message,
            state,
            'Лимит попыток исчерпан.',
            reply_markup=ReplyKeyboardRemove(),
        )
        await state.set_state(StudentAnswerStates.in_assignment)
        await _post_answer_flow(
            message,
            state,
            assignment_id,
            message.from_user.id,
            answering_mode,
            clear_previous=False,
        )
        return

    answer_text = message.text or message.caption
    attachments = _extract_attachments(message)
    if not answer_text and not attachments:
        await _send_tracked(message, state, 'Отправьте текст ответа или вложение.')
        return

    question = await get_homework_question(question_id)
    is_correct: int | None = None
    score: float | None = None
    if question and question.question_type == 'short':
        is_correct = 1 if _normalize_answer(answer_text) == _normalize_answer(question.correct_answer) else 0
        points = question.points or 1.0
        score = points if is_correct else 0.0

    await record_assignment_attempt(
        assignment_id=assignment_id,
        question_id=question_id,
        student_tg_id=message.from_user.id,
        attempt_index=attempt_count + 1,
        answer_text=answer_text,
        is_correct=is_correct,
        score=score,
        attachments=attachments,
    )
    await state.set_state(StudentAnswerStates.in_assignment)
    await _clear_tracked_messages(message, state)
    await _send_tracked(message, state, 'Ответ сохранен.')

    await _post_answer_flow(
        message,
        state,
        assignment_id,
        message.from_user.id,
        answering_mode,
        clear_previous=False,
    )


async def _post_answer_flow(
    message: Message,
    state: FSMContext,
    assignment_id: int,
    student_tg_id: int,
    answering_mode: str,
    clear_previous: bool = True,
) -> None:
    if clear_previous:
        await _clear_tracked_messages(message, state)
    if answering_mode == 'FIXED':
        next_question = await get_next_unanswered_question(assignment_id, student_tg_id)
        if next_question:
            assignment = await get_assignment_view(assignment_id, student_tg_id)
            if assignment:
                await _present_question(message, state, assignment, next_question, student_tg_id)
            return
        await state.set_state(StudentAnswerStates.in_assignment)
        await _send_tracked(
            message,
            state,
            'Все вопросы уже отвечены. Нажмите "Сдать задание".',
            reply_markup=_build_submit_keyboard(assignment_id).as_markup(),
        )
        return

    await _send_free_order_question_list(
        message,
        assignment_id,
        student_tg_id,
        note='Можно выбрать следующий вопрос.',
        state=state,
        clear_previous=clear_previous,
    )
