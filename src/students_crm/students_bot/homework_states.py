from aiogram.fsm.state import State, StatesGroup


class AdminCreateStates(StatesGroup):
    waiting_for_title = State()
    waiting_for_description = State()
    waiting_for_attempts = State()
    waiting_for_question_text = State()
    waiting_for_question_attachments = State()
    waiting_for_question_points = State()
    waiting_for_short_answer = State()
    waiting_for_mcq_option = State()
    waiting_for_mcq_correct = State()
    waiting_for_edit_text = State()
    waiting_for_edit_attachments = State()
    waiting_for_edit_short_answer = State()
    waiting_for_edit_points = State()


class AdminAssignStates(StatesGroup):
    waiting_for_assign_soft_deadline = State()
    waiting_for_assign_hard_deadline = State()


class StudentAnswerStates(StatesGroup):
    in_assignment = State()
    waiting_for_text_answer = State()
    waiting_for_mcq_selection = State()
    waiting_for_open_text = State()
    waiting_for_open_attachments = State()


STUDENT_QUESTION_STATES = {
    StudentAnswerStates.waiting_for_text_answer.state,
    StudentAnswerStates.waiting_for_mcq_selection.state,
    StudentAnswerStates.waiting_for_open_text.state,
    StudentAnswerStates.waiting_for_open_attachments.state,
}
STUDENT_ASSIGNMENT_STATE = StudentAnswerStates.in_assignment.state

ADMIN_STATES = {
    AdminCreateStates.waiting_for_title.state,
    AdminCreateStates.waiting_for_description.state,
    AdminCreateStates.waiting_for_attempts.state,
    AdminCreateStates.waiting_for_question_text.state,
    AdminCreateStates.waiting_for_question_attachments.state,
    AdminCreateStates.waiting_for_question_points.state,
    AdminCreateStates.waiting_for_short_answer.state,
    AdminCreateStates.waiting_for_mcq_option.state,
    AdminCreateStates.waiting_for_mcq_correct.state,
    AdminCreateStates.waiting_for_edit_text.state,
    AdminCreateStates.waiting_for_edit_attachments.state,
    AdminCreateStates.waiting_for_edit_short_answer.state,
    AdminCreateStates.waiting_for_edit_points.state,
    AdminAssignStates.waiting_for_assign_soft_deadline.state,
    AdminAssignStates.waiting_for_assign_hard_deadline.state,
}
