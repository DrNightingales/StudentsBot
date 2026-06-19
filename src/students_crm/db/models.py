from collections import namedtuple
from dataclasses import dataclass
from typing import Any


Invite = namedtuple('Invite', ['tg_username', 'invite_code'])
Student = namedtuple('Student', ['username', 'tg_username', 'tg_id'])
HomeworkTemplate = namedtuple(
    'HomeworkTemplate',
    ['id', 'title', 'description', 'answering_mode', 'max_attempts', 'is_published'],
)
HomeworkQuestion = namedtuple(
    'HomeworkQuestion',
    ['id', 'assignment_id', 'question_type', 'text', 'correct_answer', 'points', 'order_index'],
)
HomeworkQuestionAttachment = namedtuple(
    'HomeworkQuestionAttachment',
    ['id', 'question_id', 'file_id', 'file_type', 'position'],
)
HomeworkAttempt = namedtuple(
    'HomeworkAttempt',
    ['id', 'answer_text', 'is_correct', 'score', 'attempt_index'],
)
HomeworkAttemptAttachment = namedtuple(
    'HomeworkAttemptAttachment',
    ['id', 'attempt_id', 'file_id', 'file_type', 'position'],
)
HomeworkOption = namedtuple(
    'HomeworkOption',
    ['id', 'question_id', 'option_text', 'is_correct', 'position'],
)
HomeworkAssignmentView = namedtuple(
    'HomeworkAssignmentView',
    [
        'id',
        'title',
        'text',
        'soft_deadline',
        'hard_deadline',
        'status',
        'template_id',
        'answering_mode',
        'max_attempts',
    ],
)
HomeworkQuestionProgress = namedtuple(
    'HomeworkQuestionProgress',
    ['question_id', 'order_index', 'question_type', 'points', 'attempted', 'is_correct', 'score'],
)
ProvisioningStatus = namedtuple(
    'ProvisioningStatus',
    ['username', 'status', 'error', 'created_at', 'updated_at'],
)


@dataclass
class Result:
    """Represents the outcome of an operation."""

    ok: bool
    message: str | None
    data: Any = None

    def __bool__(self):
        return self.ok

    def __str__(self):
        return self.message or ''
