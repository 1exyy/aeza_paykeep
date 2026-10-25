"""Dialog of the application bot, independent of aiogram so it can be tested.

Steps: team name → administrator login → chat for reminders (the main bot must be able to
post there) → optional SMTP (server, port, security, login, password, sender, recipients)
→ summary → submit. The draft lives in `application_drafts`; /cancel drops it.
Every function returns a `Reply`; the bot adapter renders it. Callers commit.
"""

import copy
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.core.config import get_settings
from app.core.errors import AppError
from app.models.application import TeamApplication
from app.models.application_draft import ApplicationDraft
from app.schemas.application import ApplicationInput, SmtpInput, clean_team_name
from app.schemas.user import _normalize_login
from app.services import applications, teams

ChatCheck = Callable[[str], Awaitable[str | None]]  # chat id → error text, None when it works

_CHAT_RE = re.compile(r"^(-?\d{1,20}|@[A-Za-z][A-Za-z0-9_]{4,31})$")
_HOST_RE = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$"
)
_EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")
SECURITY_LABELS = {"starttls": "STARTTLS", "ssl": "SSL/TLS", "none": "без шифрования"}


@dataclass
class Applicant:
    telegram_id: int
    username: str | None
    name: str | None


@dataclass
class Reply:
    text: str
    buttons: list[tuple[str, str]] = field(default_factory=list)  # (label, callback data)
    delete_incoming: bool = False  # the incoming message held a password


START = Reply(
    "Здравствуйте! Здесь можно заказать команду в Invoice Keeper — сервисе напоминаний "
    "о регулярных платежах. Понадобятся название команды, логин администратора и чат "
    "для напоминаний; почту можно указать по желанию.",
    [("Подать заявку", "apply:start")],
)
CANCELLED = Reply("Заявка отменена. Начать заново — /start", [("Подать заявку", "apply:start")])


async def _draft(db: AsyncSession, who: Applicant) -> ApplicationDraft | None:
    return await db.get(ApplicationDraft, who.telegram_id, with_for_update=True)


async def _save(
    db: AsyncSession, clock: Clock, who: Applicant, step: str, data: dict[str, Any]
) -> None:
    draft = await _draft(db, who)
    if draft is None:
        db.add(
            ApplicationDraft(
                applicant_telegram_id=who.telegram_id, step=step, data=data, updated_at=clock.now()
            )
        )
    else:
        draft.step, draft.data, draft.updated_at = step, copy.deepcopy(data), clock.now()
    await db.flush()


async def _drop(db: AsyncSession, who: Applicant) -> None:
    await db.execute(
        delete(ApplicationDraft).where(ApplicationDraft.applicant_telegram_id == who.telegram_id)
    )


async def _pending(db: AsyncSession, who: Applicant) -> TeamApplication | None:
    return await db.scalar(
        select(TeamApplication).where(
            TeamApplication.applicant_telegram_id == who.telegram_id,
            TeamApplication.status == "pending",
        )
    )


def _ask(step: str) -> Reply:
    bot = get_settings().telegram_bot_username
    main_bot = f"@{bot}" if bot else "бота напоминаний Invoice Keeper"
    questions = {
        "team": Reply(
            "Как назовётся команда? Это название вводят при входе.\n"
            "2–64 символа: буквы, цифры, пробел, точка, дефис, подчёркивание."
        ),
        "login": Reply(
            "Логин администратора команды (латиница, цифры, точка, дефис, _; 3–32 символа):"
        ),
        "chat": Reply(
            f"Куда присылать напоминания? Добавьте {main_bot} в группу или канал "
            "(в канал — администратором), затем пришлите сюда ID чата или @имя канала.\n"
            f"ID группы подскажет сам бот: напишите в группе /chatid."
        ),
        "smtp_choice": Reply(
            "Отправлять напоминания ещё и на почту?",
            [("Указать почту (SMTP)", "apply:smtp:yes"), ("Пропустить", "apply:smtp:skip")],
        ),
        "smtp_host": Reply("SMTP-сервер, например smtp-relay.brevo.com:"),
        "smtp_port": Reply("Порт SMTP (обычно 587, 2525 или 465):"),
        "smtp_security": Reply(
            "Шифрование:",
            [
                ("STARTTLS (587, 2525)", "apply:sec:starttls"),
                ("SSL/TLS (465)", "apply:sec:ssl"),
                ("Без шифрования", "apply:sec:none"),
            ],
        ),
        "smtp_user": Reply("Логин SMTP (или «-», если без авторизации):"),
        "smtp_password": Reply(
            "Пароль или SMTP-ключ (или «-»). Сообщение с паролем я сразу удалю из чата."
        ),
        "smtp_from": Reply("Адрес отправителя (подтверждённый у почтового сервиса):"),
        "smtp_recipients": Reply("Кому слать письма — адреса через запятую:"),
    }
    return questions[step]


def _summary(data: dict[str, Any]) -> Reply:
    smtp = data.get("smtp")
    mail = (
        f"{smtp['host']}:{smtp['port']}, {SECURITY_LABELS[smtp['security']]}; "
        f"отправитель {smtp['from'] or '—'}; получатели: {', '.join(smtp['recipients'])}"
        if smtp
        else "не указана"
    )
    return Reply(
        "Проверьте заявку:\n\n"
        f"Команда: {data['team_name']}\n"
        f"Логин администратора: {data['admin_login']}\n"
        f"Чат для напоминаний: {data['telegram_chat_id']}\n"
        f"Почта: {mail}\n\n"
        "Администратором станет ваш Telegram: после одобрения сюда придут данные для входа.",
        [("Отправить заявку", "apply:submit"), ("Начать заново", "apply:restart")],
    )


async def start(db: AsyncSession, clock: Clock, who: Applicant) -> Reply:
    pending = await _pending(db, who)
    if pending is not None:
        return Reply(
            f"Заявка на команду «{pending.team_name}» уже рассматривается. Ответ придёт сюда."
        )
    draft = await _draft(db, who)
    if draft is not None:
        reply = _summary(draft.data) if draft.step == "confirm" else _ask(draft.step)
        return Reply(
            "Продолжим заявку. " + reply.text,
            reply.buttons + [("Отменить заявку", "apply:cancel")],
        )
    return START


async def cancel(db: AsyncSession, who: Applicant) -> Reply:
    await _drop(db, who)
    return CANCELLED


async def on_button(
    db: AsyncSession, clock: Clock, who: Applicant, data: str, check_chat: ChatCheck
) -> Reply:
    if data in ("apply:start", "apply:restart"):
        if await _pending(db, who) is not None:
            return await start(db, clock, who)
        await _save(db, clock, who, "team", {})
        return _ask("team")
    if data == "apply:cancel":
        return await cancel(db, who)
    draft = await _draft(db, who)
    if draft is None:
        return START
    values = copy.deepcopy(draft.data)  # JSONB: nested changes must make a new value
    if data == "apply:smtp:skip" and draft.step == "smtp_choice":
        values.pop("smtp", None)
        await _save(db, clock, who, "confirm", values)
        return _summary(values)
    if data == "apply:smtp:yes" and draft.step == "smtp_choice":
        values["smtp"] = {}
        await _save(db, clock, who, "smtp_host", values)
        return _ask("smtp_host")
    if data.startswith("apply:sec:") and draft.step == "smtp_security":
        security = data.removeprefix("apply:sec:")
        if security in SECURITY_LABELS:
            values["smtp"]["security"] = security
            await _save(db, clock, who, "smtp_user", values)
            return _ask("smtp_user")
    if data == "apply:submit" and draft.step == "confirm":
        return await _submit(db, clock, who, values)
    return Reply("Эта кнопка уже не действует. " + _current(draft).text, _current(draft).buttons)


def _current(draft: ApplicationDraft) -> Reply:
    return _summary(draft.data) if draft.step == "confirm" else _ask(draft.step)


async def _submit(db: AsyncSession, clock: Clock, who: Applicant, values: dict[str, Any]) -> Reply:
    try:
        data = ApplicationInput.model_validate(
            {
                "team_name": values["team_name"],
                "admin_login": values["admin_login"],
                "telegram_chat_id": values["telegram_chat_id"],
                "smtp": values.get("smtp"),
            }
        )
        application = await applications.submit(
            db,
            clock,
            data,
            applicant_telegram_id=who.telegram_id,
            applicant_username=who.username,
            applicant_name=who.name,
        )
    except AppError as exc:
        if exc.code == "team_name_taken":
            await _save(db, clock, who, "team", values)
            return Reply("Пока вы заполняли заявку, это название заняли. " + _ask("team").text)
        return Reply(exc.message)
    except (ValidationError, ValueError, KeyError):
        await _save(db, clock, who, "team", {})
        return Reply("Не получилось собрать заявку, начнём заново. " + _ask("team").text)
    await _drop(db, who)
    return Reply(
        f"Заявка №{application.id} на команду «{application.team_name}» отправлена. "
        "Решение придёт сюда."
    )


async def on_text(
    db: AsyncSession, clock: Clock, who: Applicant, text: str, check_chat: ChatCheck
) -> Reply:
    draft = await _draft(db, who)
    if draft is None:
        return await start(db, clock, who)
    step, values, answer = draft.step, copy.deepcopy(draft.data), text.strip()
    smtp = values.get("smtp") or {}

    if step == "team":
        try:
            name = clean_team_name(answer)
        except ValueError as exc:
            return Reply(f"{exc} Попробуйте ещё раз.")
        if not await applications.name_available(db, teams.normalize(name)):
            return Reply("Команда с таким названием уже есть. Придумайте другое название.")
        values["team_name"] = name
        await _save(db, clock, who, "login", values)
        return _ask("login")
    if step == "login":
        try:
            values["admin_login"] = _normalize_login(answer)
        except ValueError as exc:
            return Reply(f"{exc}. Попробуйте ещё раз.")
        await _save(db, clock, who, "chat", values)
        return _ask("chat")
    if step == "chat":
        if not _CHAT_RE.match(answer):
            return Reply(
                "Нужен ID чата (у групп и каналов начинается с -100) или @имя канала. "
                "ID группы покажет команда /chatid в самой группе."
            )
        problem = await check_chat(answer)
        if problem:
            return Reply(f"Не удалось написать в этот чат: {problem}\n" + _ask("chat").text)
        values["telegram_chat_id"] = answer
        await _save(db, clock, who, "smtp_choice", values)
        return _ask("smtp_choice")
    if step == "smtp_host":
        if not _HOST_RE.match(answer):
            return Reply("Это не похоже на имя сервера. Пример: smtp-relay.brevo.com")
        smtp["host"] = answer
        return await _next(db, clock, who, values, smtp, "smtp_port")
    if step == "smtp_port":
        if not answer.isdigit() or not 1 <= int(answer) <= 65535:
            return Reply("Порт — число от 1 до 65535.")
        smtp["port"] = int(answer)
        return await _next(db, clock, who, values, smtp, "smtp_security")
    if step == "smtp_user":
        smtp["user"] = "" if answer == "-" else answer[:256]
        return await _next(db, clock, who, values, smtp, "smtp_password")
    if step == "smtp_password":
        smtp["password"] = "" if answer == "-" else answer[:256]
        reply = await _next(db, clock, who, values, smtp, "smtp_from")
        reply.delete_incoming = True
        reply.text = "Пароль сохранён, сообщение удалено. " + reply.text
        return reply
    if step == "smtp_from":
        if answer != "-" and not _EMAIL_RE.match(answer):
            return Reply("Укажите адрес, например billing@example.com")
        smtp["from"] = "" if answer == "-" else answer
        return await _next(db, clock, who, values, smtp, "smtp_recipients")
    if step == "smtp_recipients":
        recipients = [part for part in re.split(r"[,;\s]+", answer) if part]
        bad = [address for address in recipients if not _EMAIL_RE.match(address)]
        if not recipients or bad:
            return Reply(
                f"Некорректный адрес: {bad[0] if bad else '—'}. Перечислите через запятую."
            )
        smtp["recipients"] = list(dict.fromkeys(recipients))
        try:
            SmtpInput.model_validate(smtp).as_settings()
        except (ValidationError, ValueError) as exc:
            return Reply(f"Настройки почты не прошли проверку: {exc}")
        values["smtp"] = smtp
        await _save(db, clock, who, "confirm", values)
        return _summary(values)
    current = _current(draft)
    return Reply("Выберите вариант кнопкой ниже. " + current.text, current.buttons)


async def _next(
    db: AsyncSession,
    clock: Clock,
    who: Applicant,
    values: dict[str, Any],
    smtp: dict[str, Any],
    step: str,
) -> Reply:
    values["smtp"] = smtp
    await _save(db, clock, who, step, values)
    return _ask(step)
