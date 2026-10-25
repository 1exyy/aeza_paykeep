"""Dialog of the application bot: services/apply_flow without Telegram."""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import get_clock
from app.models.application import TeamApplication
from app.models.application_draft import ApplicationDraft
from app.services import apply_flow
from app.services.apply_flow import Applicant
from tests.helpers import freeze

WHO = Applicant(telegram_id=4242, username="founder", name="Анна Основатель")
NOW = "2026-11-10T12:00:00+03:00"


async def chat_ok(chat_id: str) -> str | None:
    return None


async def chat_closed(chat_id: str) -> str | None:
    return "Forbidden: bot is not a member of the channel chat"


class Talk:
    """Drives the dialog like the bot does: one commit per incoming update."""

    def __init__(self, db: AsyncSession, who: Applicant = WHO, check=chat_ok) -> None:
        self.db, self.who, self.check = db, who, check

    async def say(self, text: str) -> apply_flow.Reply:
        reply = await apply_flow.on_text(
            self.db, await get_clock(self.db), self.who, text, self.check
        )
        await self.db.commit()
        return reply

    async def press(self, data: str) -> apply_flow.Reply:
        reply = await apply_flow.on_button(
            self.db, await get_clock(self.db), self.who, data, self.check
        )
        await self.db.commit()
        return reply

    async def start(self) -> apply_flow.Reply:
        reply = await apply_flow.start(self.db, await get_clock(self.db), self.who)
        await self.db.commit()
        return reply


async def test_application_without_mail(client: AsyncClient, db: AsyncSession) -> None:
    freeze(NOW)
    await client.get("/api/v1/auth/me")  # API startup: the first team «aeza» exists
    talk = Talk(db)
    assert ("Подать заявку", "apply:start") in (await talk.start()).buttons
    assert "Как назовётся команда" in (await talk.press("apply:start")).text

    assert "уже есть" in (await talk.say("AEZA")).text  # the first team
    assert "Попробуйте" in (await talk.say("x")).text
    assert "Логин администратора" in (await talk.say("  Бета   Команда ")).text
    assert "Попробуйте" in (await talk.say("a")).text
    assert "Куда присылать" in (await talk.say("Boss")).text
    assert "Нужен ID чата" in (await talk.say("my chat")).text
    reply = await talk.say("-1001234567890")
    assert ("Пропустить", "apply:smtp:skip") in reply.buttons
    summary = await talk.press("apply:smtp:skip")
    assert "Команда: Бета Команда" in summary.text and "Почта: не указана" in summary.text
    done = await talk.press("apply:submit")
    assert "отправлена" in done.text

    application = await db.scalar(select(TeamApplication))
    assert application is not None and application.status == "pending"
    assert application.team_name == "Бета Команда" and application.admin_login == "boss"
    assert application.applicant_telegram_id == 4242 and application.applicant_username == "founder"
    assert application.smtp is None
    assert await db.get(ApplicationDraft, 4242) is None  # the draft is gone

    # one open application per Telegram
    again = await talk.start()
    assert "уже рассматривается" in again.text and not again.buttons
    assert "уже рассматривается" in (await talk.press("apply:start")).text


async def test_application_with_mail_hides_the_password(db: AsyncSession) -> None:
    freeze(NOW)
    talk = Talk(db)
    await talk.press("apply:start")
    await talk.say("Gamma")
    await talk.say("gamma-admin")
    await talk.say("@gamma_channel")
    assert "SMTP-сервер" in (await talk.press("apply:smtp:yes")).text
    assert "не похоже" in (await talk.say("bad host")).text
    await talk.say("smtp-relay.brevo.com")
    assert "число" in (await talk.say("99999")).text
    reply = await talk.say("2525")
    assert ("STARTTLS (587, 2525)", "apply:sec:starttls") in reply.buttons
    assert "Выберите вариант" in (await talk.say("starttls")).text  # a button is expected
    await talk.press("apply:sec:starttls")
    await talk.say("a1b2@smtp-brevo.com")
    hidden = await talk.say("xsmtpsib-very-secret")
    assert hidden.delete_incoming is True and "xsmtpsib" not in hidden.text
    assert "например" in (await talk.say("not-an-address")).text
    await talk.say("billing@gamma.example")
    assert "Некорректный адрес" in (await talk.say("boss@gamma.example, nope")).text
    summary = await talk.say("boss@gamma.example; buh@gamma.example")
    assert "smtp-relay.brevo.com:2525, STARTTLS" in summary.text
    assert "xsmtpsib" not in summary.text
    await talk.press("apply:submit")

    application = await db.scalar(select(TeamApplication))
    assert application is not None and application.smtp is not None
    assert application.smtp["smtp_host"] == "smtp-relay.brevo.com"
    assert application.smtp["smtp_port"] == 2525 and application.smtp["smtp_starttls"] is True
    assert application.smtp["smtp_password"] == "xsmtpsib-very-secret"
    assert application.smtp["email_recipients"] == "boss@gamma.example, buh@gamma.example"


async def test_chat_must_be_reachable_and_draft_survives(db: AsyncSession) -> None:
    freeze(NOW)
    talk = Talk(db, check=chat_closed)
    await talk.press("apply:start")
    await talk.say("Delta")
    await talk.say("delta")
    reply = await talk.say("-1009999999999")
    assert "Не удалось написать в этот чат" in reply.text and "not a member" in reply.text

    # the bot restarted: the draft is still there and /start continues it
    resumed = await Talk(db).start()
    assert resumed.text.startswith("Продолжим заявку.") and "Куда присылать" in resumed.text
    assert ("Отменить заявку", "apply:cancel") in resumed.buttons
    assert "Отправлять напоминания" in (await Talk(db).say("-1009999999999")).text

    # stale buttons and cancel
    assert "не действует" in (await talk.press("apply:submit")).text
    assert "отменена" in (await talk.press("apply:cancel")).text
    assert await db.get(ApplicationDraft, WHO.telegram_id) is None
    assert (await talk.say("hello")).buttons == [("Подать заявку", "apply:start")]


async def test_name_taken_while_filling(db: AsyncSession) -> None:
    freeze(NOW)
    first, second = Talk(db), Talk(db, Applicant(5151, None, None))
    for talk in (first, second):
        await talk.press("apply:start")
        await talk.say("Omega")
        await talk.say("omega")
        await talk.say("-1001111111111")
        await talk.press("apply:smtp:skip")
    assert "отправлена" in (await first.press("apply:submit")).text
    late = await second.press("apply:submit")
    assert "заняли" in late.text and "Как назовётся команда" in late.text
    assert "Логин администратора" in (await second.say("Omega 2")).text
