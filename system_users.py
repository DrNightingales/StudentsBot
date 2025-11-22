import grp
import pwd
import subprocess
from pathlib import Path
from typing import Sequence


def _run_command(command: Sequence[str], *, input_data: str | None = None) -> None:
    '''Run a shell command and raise if it fails.

    Args:
        command (Sequence[str]): Command and arguments to execute.
        input_data (str | None): Optional stdin passed to the command.
    '''
    subprocess.run(
        command,
        input=input_data,
        text=True,
        check=True,
    )


def ensure_group_exists(group_name: str, *, use_sudo: bool = True) -> None:
    '''Create the students group if it is missing.

    Args:
        group_name (str): Name of the group to ensure exists.
        use_sudo (bool, optional): Prefix commands with sudo. Defaults to True.
    '''
    try:
        grp.getgrnam(group_name)
        return
    except KeyError:
        pass

    cmd = ['groupadd', '--force', group_name]
    if use_sudo:
        cmd.insert(0, 'sudo')
    _run_command(cmd)


def user_exists(username: str) -> bool:
    '''Check whether a Linux user already exists.

    Args:
        username (str): Username to look up.

    Returns:
        bool: True if the account exists.
    '''
    try:
        pwd.getpwnam(username)
        return True
    except KeyError:
        return False


def create_student_account(
    username: str,
    password: str,
    *,
    teacher_username: str,
    students_group: str = 'students',
    home_base: str = '/home',
    default_shell: str = '/bin/bash',
    use_sudo: bool = True,
) -> None:
    '''Create a Linux account for a student and configure access controls.

    Args:
        username (str): Login to create.
        password (str): Plaintext password that will be hashed by the OS.
        teacher_username (str): Account that must retain access to every student home.
        students_group (str): Shared Unix group for all students.
        home_base (str): Base directory for student homes (e.g. /home).
        default_shell (str): Shell assigned to the account (e.g. /bin/bash).
        use_sudo (bool, optional): Prefix commands with sudo. Defaults to True.
    '''
    ensure_group_exists(students_group, use_sudo=use_sudo)

    if not user_exists(teacher_username):
        raise ValueError(f'teacher account {teacher_username!r} does not exist on this system')

    if user_exists(username):
        raise ValueError(f'user {username!r} already exists')

    home_dir = Path(home_base) / username
    create_cmd = [
        'useradd',
        '--create-home',
        '--home-dir',
        str(home_dir),
        '--shell',
        default_shell,
        '--gid',
        students_group,
        username,
    ]
    if use_sudo:
        create_cmd.insert(0, 'sudo')
    _run_command(create_cmd)

    password_cmd = ['chpasswd']
    if use_sudo:
        password_cmd.insert(0, 'sudo')
    _run_command(password_cmd, input_data=f'{username}:{password}')

    chmod_cmd = ['chmod', '700', str(home_dir)]
    if use_sudo:
        chmod_cmd.insert(0, 'sudo')
    _run_command(chmod_cmd)

    acl_cmd = ['setfacl', '-m', f'u:{teacher_username}:rwx', str(home_dir)]
    if use_sudo:
        acl_cmd.insert(0, 'sudo')
    _run_command(acl_cmd)

    default_acl_cmd = ['setfacl', '-d', '-m', f'u:{teacher_username}:rwx', str(home_dir)]
    if use_sudo:
        default_acl_cmd.insert(0, 'sudo')
    _run_command(default_acl_cmd)
