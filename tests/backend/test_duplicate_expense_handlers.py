import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

TEST_ENV = {
    "TELEGRAM_BOT_TOKEN": "FAKE_TELEGRAM_TOKEN",
    "TELEGRAM_SECRET_TOKEN": "FAKE_SECRET",
    "SUPABASE_URL": "https://fake.supabase.co",
    "SUPABASE_KEY": "FAKE_SUPABASE_KEY_1234567890",
    "DEEPSEEK_API_KEY": "FAKE_DEEPSEEK_KEY_1234567890",
    "GROQ_API_KEY": "FAKE_GROQ_KEY_1234567890",
    "GEMINI_API_KEY": "FAKE_GEMINI_KEY_1234567890",
    "TELEGRAM_TASKS_PROJECT": "financemgmtbot",
    "TELEGRAM_TASKS_LOCATION": "southamerica-east1",
    "TELEGRAM_TASKS_QUEUE": "telegram-updates",
    "TELEGRAM_WORKER_URL": "https://worker.example.run.app",
    "TELEGRAM_TASK_INVOKER_SERVICE_ACCOUNT": "telegram-task-invoker@financemgmtbot.iam.gserviceaccount.com",
}
for key, value in TEST_ENV.items():
    os.environ.setdefault(key, value)

for dependency_patch in [
    patch("supabase.create_client", return_value=MagicMock()),
    patch("groq.AsyncGroq", return_value=MagicMock()),
    patch("openai.AsyncOpenAI", return_value=MagicMock()),
    patch("google.genai.Client", return_value=MagicMock()),
]:
    dependency_patch.start()
from datetime import datetime, timedelta, timezone

import handlers
import security
from domain import duplicate_expense as dup
from domain.finance import build_installment_records, normalize_register_payload
from telegram_update_processor import ProcessorDeps, UpdateOutcome, process_telegram_update
from telegram_update_ledger import UpdateClaim

CHAT = 1
USER = 2
ORIGINAL_UPDATE = 700
TODAY = datetime(2026, 11, 11, 10, 0, 0)


class World:
    """In-memory stand-in for the pending table, the decision RPC and the expense table."""

    def __init__(self):
        self.pending = {}
        self.expenses = []
        self.inserts = 0
        self.store_calls = 0
        self.lookups = 0
        self.today = TODAY
        self.failures = {}

    def fail_once(self, name, exc=None):
        self.failures[name] = exc or RuntimeError("injected")

    def _maybe_fail(self, name):
        exc = self.failures.pop(name, None)
        if exc:
            raise exc

    def seed_expense(self, **overrides):
        row = {
            "id": len(self.expenses) + 1,
            "data": "2026-11-10",
            "valor": 25.5,
            "natureza": "Essencial",
            "categoria": "Mercado",
            "descricao": "Padaria Central",
            "metodo_pagamento": "Dinheiro",
            "conta": "Nubank",
        }
        row.update(overrides)
        self.expenses.append(row)
        return row

    def expire(self, cache_id):
        self.pending[cache_id]["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

    def _view(self, row):
        return {**row, "payload": row["payload"], "preview_json": {"summary": "Confirmação pendente"}}

    # --- security.py / db_repository.py replacements ---
    def store_pending_item(self, payload, *, kind=None, origin_chat_id=None, origin_user_id=None, source_update_id=None):
        self.store_calls += 1
        self._maybe_fail("store")
        for row in self.pending.values():
            if row["source_update_id"] == source_update_id:
                if row["origin_chat_id"] != str(origin_chat_id):
                    raise RuntimeError("Pending conflict winner belongs to another chat.")
                return {"id": row["id"], "kind": row["kind"], "payload": row["payload"], "source_update_id": source_update_id,
                        "duplicate_decision": row["duplicate_decision"], "expires_at": row["expires_at"]}
        cache_id = f"tu_{source_update_id}"
        row = {
            "id": cache_id,
            "kind": kind,
            "payload": payload,
            "origin_chat_id": str(origin_chat_id),
            "origin_user_id": str(origin_user_id) if origin_user_id is not None else None,
            "source_update_id": source_update_id,
            "duplicate_decision": None,
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        }
        self.pending[cache_id] = row
        return {"id": cache_id, "kind": kind, "payload": payload, "source_update_id": source_update_id, "duplicate_decision": None}

    def load_pending_item(self, cache_id):
        row = self.pending.get(cache_id)
        return self._view(row) if row else None

    def load_pending_item_by_source_update_id(self, source_update_id):
        for row in self.pending.values():
            if row["source_update_id"] == source_update_id:
                return self._view(row)
        return None

    def decide(self, cache_id, chat_id, user_id, decision):
        self._maybe_fail("decide")
        assert decision in ("save", "skip")
        row = self.pending.get(cache_id)
        if not row or row["kind"] != "duplicate_expense":
            return None
        if row["origin_chat_id"] != str(chat_id) or row["origin_user_id"] != str(user_id):
            return None
        if row["duplicate_decision"] is None:
            expired = row["expires_at"] is None or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc)
            row["duplicate_decision"] = "expired" if expired else decision
        return row["duplicate_decision"]

    def clear(self, cache_id):
        self._maybe_fail("clear")
        row = self.pending[cache_id]
        assert row["duplicate_decision"] is not None
        row["payload"] = {}

    def insert(self, dados, *, source_update_id=None, origin_chat_id=None):
        self.inserts += 1
        self._maybe_fail("insert")
        records = build_installment_records(dados, fallback_date=self.today)
        for index, record in enumerate(records, start=1):
            key = (source_update_id, f"installment:{index:04d}")
            if any(r.get("_key") == key for r in self.expenses):
                continue
            self.expenses.append({**record, "id": len(self.expenses) + 1000, "_key": key, "source_origin_chat_id": origin_chat_id})
        return records

    def records_by_source(self, source_update_id, origin_chat_id=None):
        return [r for r in self.expenses if r.get("_key", (None,))[0] == source_update_id and r.get("source_origin_chat_id") == origin_chat_id]

    def find(self, candidate):
        self.lookups += 1
        self._maybe_fail("find")
        rows = [
            r for r in self.expenses
            if r["data"] == candidate.record["data"] and r["valor"] == candidate.record["valor"] and r["natureza"] != "Receita"
        ]
        return dup.pick_first_match(candidate, sorted(rows, key=lambda r: r["id"]))

    def count_saved(self, source_update_id=ORIGINAL_UPDATE):
        return len([r for r in self.expenses if r.get("_key", (None,))[0] == source_update_id])


def _dados(**overrides):
    base = {
        "data": "2026-11-10",
        "valor_total": 25.5,
        "parcelas": 1,
        "categoria": "Mercado",
        "descricao": "Padaria Central",
        "metodo_pagamento": "Pix",
        "conta": "Nubank",
    }
    base.update(overrides)
    return base


def _llm(**overrides):
    return AsyncMock(return_value={"intencao": "registrar", "dados_registro": _dados(**overrides)})


def text_update(update_id=ORIGINAL_UPDATE, chat=CHAT, user=USER):
    return {"update_id": update_id, "message": {"chat": {"id": chat}, "from": {"id": user}, "text": "gasto"}}


def voice_update(update_id=ORIGINAL_UPDATE):
    return {"update_id": update_id, "message": {"chat": {"id": CHAT}, "from": {"id": USER}, "voice": {"file_id": "f"}}}


def callback_update(data, update_id=900, chat=CHAT, user=USER, message_id=50):
    return {
        "update_id": update_id,
        "callback_query": {"id": "cb", "data": data, "from": {"id": user}, "message": {"chat": {"id": chat}, "message_id": message_id}},
    }


class Env:
    def __init__(self, world, llm):
        self.world = world
        self.llm = llm
        self.send = AsyncMock(return_value={"message_id": 11})
        self.edit = AsyncMock(return_value={})
        self.remove = AsyncMock()
        self.stt = AsyncMock(return_value="gastei na padaria")

    async def run(self, update, **kwargs):
        kwargs.setdefault("source_update_id", update["update_id"])
        return await handlers.processar_update_assincrono(update, **kwargs)

    def sent_texts(self):
        return [call.args[1] for call in self.send.await_args_list]

    def edited_texts(self):
        return [call.args[2] for call in self.edit.await_args_list]


@pytest.fixture
def env():
    world = World()
    environment = Env(world, _llm())
    patches = [
        patch.object(handlers, "processar_texto_com_llm", environment.llm),
        patch.object(handlers, "transcrever_audio", environment.stt),
        patch.object(handlers, "baixar_arquivo_telegram", AsyncMock(return_value=b"x")),
        patch.object(handlers, "enviar_acao_telegram", AsyncMock()),
        patch.object(handlers, "responder_callback_telegram", AsyncMock()),
        patch.object(handlers, "allow_request", return_value=True),
        patch.object(handlers, "enviar_mensagem_telegram", environment.send),
        patch.object(handlers, "editar_mensagem_telegram", environment.edit),
        patch.object(handlers, "remover_teclado_mensagem_telegram", environment.remove),
        patch.object(handlers, "get_brasilia_time", lambda: world.today),
        patch.object(handlers, "find_matching_expense", world.find),
        patch.object(handlers, "store_pending_item", world.store_pending_item),
        patch.object(handlers, "load_pending_item", world.load_pending_item),
        patch.object(handlers, "load_pending_item_by_source_update_id", world.load_pending_item_by_source_update_id),
        patch.object(handlers, "decide_duplicate_expense", world.decide),
        patch.object(handlers, "clear_duplicate_snapshot", world.clear),
        patch.object(handlers, "inserir_no_banco", world.insert),
        patch.object(handlers, "load_records_by_source_update_id", world.records_by_source),
        patch.object(handlers, "delete_pending_item", MagicMock(side_effect=AssertionError("duplicate flow must not delete markers"))),
    ]
    for p in patches:
        p.start()
    yield environment
    for p in reversed(patches):
        p.stop()


def _keyboard_ids(call):
    markup = next(arg for arg in call.args if isinstance(arg, dict) and "inline_keyboard" in arg)
    return [b["callback_data"] for row in markup["inline_keyboard"] for b in row]


class TestMatchCreatesDurableConfirmation:
    @pytest.mark.asyncio
    async def test_match_stores_frozen_payload_and_sends_keyboard_without_saving(self, env):
        env.world.seed_expense()
        await env.run(text_update())

        assert env.world.inserts == 0
        row = env.world.pending["tu_700"]
        assert row["kind"] == "duplicate_expense"
        assert row["origin_chat_id"] == "1" and row["origin_user_id"] == "2"
        assert row["payload"]["transaction"]["data"] == "2026-11-10"
        assert row["payload"]["transaction"]["valor_total"] == 25.5
        assert row["payload"]["matched_record"] == {
            "id": 1, "data": "2026-11-10", "valor": 25.5, "conta": "Nubank", "descricao": "Padaria Central",
        }
        text = env.sent_texts()[0]
        assert "Este gasto já está registrado. É outro gasto?" in text
        assert "Anterior" in text and "Proposto" in text
        assert _keyboard_ids(env.send.await_args) == ["dupskip_tu_700", "dupsave_tu_700"]

    @pytest.mark.asyncio
    async def test_frozen_date_uses_brasilia_fallback_when_llm_gives_none(self, env):
        env.llm.return_value = {"intencao": "registrar", "dados_registro": _dados(data="")}
        env.world.seed_expense(data="2026-11-11")
        await env.run(text_update())
        assert env.world.pending["tu_700"]["payload"]["transaction"]["data"] == "2026-11-11"

    @pytest.mark.asyncio
    async def test_voice_reuses_progress_message(self, env):
        env.world.seed_expense()
        await env.run(voice_update(), progress_message_id=33)
        edited = [c for c in env.edit.await_args_list if c.args[1] == 33]
        assert "Este gasto já está registrado" in edited[-1].args[2]
        assert _keyboard_ids(edited[-1]) == ["dupskip_tu_700", "dupsave_tu_700"]

    @pytest.mark.asyncio
    async def test_delivery_stage_is_reported(self, env):
        env.world.seed_expense()
        stages = []

        async def stage(name, progress=None):
            stages.append(name)

        await env.run(text_update(), stage_callback=stage)
        assert "telegram_delivery" in stages

    @pytest.mark.asyncio
    async def test_dynamic_values_are_markdown_escaped(self, env):
        env.llm.return_value = {"intencao": "registrar", "dados_registro": _dados(descricao="a_b*c")}
        env.world.seed_expense(descricao="a_b*c")
        await env.run(text_update())
        assert "a\\_b\\*c" in env.sent_texts()[0]


class TestNoWarning:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "seed,dados",
        [
            (None, {}),
            ({"valor": 25.51}, {}),
            ({"data": "2026-11-09"}, {}),
            ({"conta": "Itau"}, {}),
            ({"descricao": "Outra coisa"}, {}),
            ({"descricao": "Padaria Central."}, {}),
            ({"natureza": "Receita"}, {}),
            ({"conta": "Nao Informada"}, {"conta": "Nao Informada"}),
            ({"descricao": "Sem descricao"}, {"descricao": "Sem descricao"}),
            ({"conta": ""}, {"conta": ""}),
        ],
    )
    async def test_saves_with_current_flow(self, env, seed, dados):
        if seed is not None:
            env.world.seed_expense(**seed)
        env.llm.return_value = {"intencao": "registrar", "dados_registro": _dados(**dados)}
        await env.run(text_update())
        assert env.world.inserts == 1
        assert env.world.pending == {}
        assert "Salvo!" in env.sent_texts()[0]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("dados", [{"parcelas": 3}, {"categoria": "Salário"}, {"valor_total": 0}])
    async def test_ineligible_transactions_skip_the_lookup(self, env, dados):
        env.world.seed_expense()
        env.llm.return_value = {"intencao": "registrar", "dados_registro": _dados(**dados)}
        await env.run(text_update())
        assert env.world.lookups == 0
        assert env.world.pending == {}

    @pytest.mark.asyncio
    async def test_missing_sender_cannot_be_bound_and_keeps_current_flow(self, env):
        env.world.seed_expense()
        update = {"update_id": 700, "message": {"chat": {"id": CHAT}, "text": "gasto"}}
        await env.run(update)
        assert env.world.lookups == 0 and env.world.inserts == 1

    @pytest.mark.asyncio
    async def test_manual_and_recurring_rows_without_chat_or_source_still_match(self, env):
        env.world.seed_expense(descricao="Assinatura Streaming", recurring_expense_id="r1", source_update_id=None)
        env.llm.return_value = {"intencao": "registrar", "dados_registro": _dados(descricao="assinatura  STREAMING")}
        await env.run(text_update())
        assert env.world.inserts == 0 and "tu_700" in env.world.pending


class TestOperationalFailures:
    @pytest.mark.asyncio
    async def test_lookup_failure_never_saves_and_surfaces_a_retry(self, env):
        env.world.seed_expense()
        env.world.fail_once("find")
        with pytest.raises(RuntimeError):
            await env.run(text_update())
        assert env.world.inserts == 0 and env.world.pending == {}
        env.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_pending_store_failure_never_saves(self, env):
        env.world.seed_expense()
        env.world.fail_once("store")
        with pytest.raises(RuntimeError):
            await env.run(text_update())
        assert env.world.inserts == 0

    @pytest.mark.asyncio
    async def test_failure_after_pending_replays_without_llm_stt_or_lookup(self, env):
        env.world.seed_expense()
        env.send.side_effect = [RuntimeError("telegram down"), {"message_id": 12}]
        with pytest.raises(RuntimeError):
            await env.run(text_update())
        assert env.llm.await_count == 1 and env.world.store_calls == 1 and env.world.lookups == 1

        await env.run(text_update())
        assert env.llm.await_count == 1 and env.world.store_calls == 1 and env.world.lookups == 1
        assert env.world.inserts == 0
        assert _keyboard_ids(env.send.await_args) == ["dupskip_tu_700", "dupsave_tu_700"]

    @pytest.mark.asyncio
    async def test_voice_replay_skips_stt(self, env):
        env.world.seed_expense()
        env.edit.side_effect = [{}, RuntimeError("telegram down"), {}]
        with pytest.raises(RuntimeError):
            await env.run(voice_update(), progress_message_id=33)
        await env.run(voice_update(), progress_message_id=33)
        assert env.stt.await_count == 1 and env.llm.await_count == 1

    @pytest.mark.asyncio
    async def test_replay_of_expired_undecided_marker_is_not_recreated(self, env):
        env.world.seed_expense()
        await env.run(text_update())
        env.world.expire("tu_700")
        env.send.reset_mock()

        await env.run(text_update())
        assert env.llm.await_count == 1 and env.world.store_calls == 1
        assert env.world.pending["tu_700"]["duplicate_decision"] == "expired"
        assert env.sent_texts() == [dup.DUPLICATE_EXPIRED_MESSAGE]
        assert env.world.pending["tu_700"]["payload"] == {}
        assert env.world.inserts == 0

    @pytest.mark.asyncio
    async def test_replay_with_invalid_payload_fails_closed(self, env):
        env.world.seed_expense()
        await env.run(text_update())
        env.world.pending["tu_700"]["payload"] = {"transaction": "broken"}
        env.send.reset_mock()
        await env.run(text_update())
        assert env.world.pending["tu_700"]["duplicate_decision"] is None
        assert env.world.inserts == 0
        assert dup.DUPLICATE_INVALID_MESSAGE in env.sent_texts()[0]

    @pytest.mark.asyncio
    async def test_replay_from_another_chat_does_not_resume_marker(self, env):
        env.world.seed_expense()
        await env.run(text_update())
        env.send.reset_mock()
        with pytest.raises(RuntimeError, match="another chat"):
            await env.run(text_update(chat=99))
        assert env.world.inserts == 0


async def _prepare(env, seed=True):
    if seed:
        env.world.seed_expense()
    await env.run(text_update())
    env.send.reset_mock()
    env.edit.reset_mock()
    env.remove.reset_mock()
    env.llm.reset_mock()


class TestSkip:
    @pytest.mark.asyncio
    async def test_skip_persists_decision_clears_snapshot_and_removes_keyboard(self, env):
        await _prepare(env)
        await env.run(callback_update("dupskip_tu_700"))

        row = env.world.pending["tu_700"]
        assert row["duplicate_decision"] == "skip" and row["payload"] == {}
        assert env.world.inserts == 0
        env.remove.assert_awaited_once_with(CHAT, 50)
        assert env.sent_texts() == [dup.DUPLICATE_SKIPPED_MESSAGE]
        assert env.llm.await_count == 0

    @pytest.mark.asyncio
    async def test_skip_retry_after_partial_delivery_is_idempotent(self, env):
        await _prepare(env)
        env.send.side_effect = [RuntimeError("down"), {"message_id": 1}]
        with pytest.raises(RuntimeError):
            await env.run(callback_update("dupskip_tu_700"))
        await env.run(callback_update("dupskip_tu_700"))
        assert env.world.inserts == 0
        assert env.world.pending["tu_700"]["duplicate_decision"] == "skip"
        assert env.sent_texts()[-1] == dup.DUPLICATE_SKIPPED_MESSAGE


class TestSave:
    @pytest.mark.asyncio
    async def test_save_persists_one_frozen_expense_with_original_identity(self, env):
        await _prepare(env)
        env.world.today = datetime(2027, 1, 5)  # day rolled over before the click
        await env.run(callback_update("dupsave_tu_700"))

        saved = [r for r in env.world.expenses if r.get("_key")]
        assert len(saved) == 1
        assert saved[0]["_key"] == (ORIGINAL_UPDATE, "installment:0001")
        assert saved[0]["data"] == "2026-11-10" and saved[0]["valor"] == 25.5
        assert saved[0]["source_origin_chat_id"] == CHAT
        row = env.world.pending["tu_700"]
        assert row["duplicate_decision"] == "save" and row["payload"] == {}
        env.remove.assert_awaited_once_with(CHAT, 50)
        assert "Padaria Central" in env.sent_texts()[0]
        assert env.llm.await_count == 0 and env.world.lookups == 1

    @pytest.mark.asyncio
    async def test_edit_or_delete_of_previous_record_does_not_interfere(self, env):
        await _prepare(env)
        env.world.expenses.clear()
        await env.run(callback_update("dupsave_tu_700"))
        assert env.world.count_saved() == 1

    @pytest.mark.asyncio
    async def test_failure_after_decision_before_insert_keeps_payload_and_retries(self, env):
        await _prepare(env)
        env.world.fail_once("insert")
        with pytest.raises(RuntimeError):
            await env.run(callback_update("dupsave_tu_700"))
        row = env.world.pending["tu_700"]
        assert row["duplicate_decision"] == "save" and row["payload"] != {}
        assert env.world.count_saved() == 0

        await env.run(callback_update("dupsave_tu_700"))
        assert env.world.count_saved() == 1
        assert env.world.pending["tu_700"]["payload"] == {}

    @pytest.mark.asyncio
    async def test_failure_after_insert_before_clear_preserves_payload_without_duplicating(self, env):
        await _prepare(env)
        env.world.fail_once("clear")
        with pytest.raises(RuntimeError):
            await env.run(callback_update("dupsave_tu_700"))
        assert env.world.pending["tu_700"]["payload"] != {}
        await env.run(callback_update("dupsave_tu_700"))
        assert env.world.count_saved() == 1

    @pytest.mark.asyncio
    async def test_original_update_retry_after_insert_does_not_bypass_marker_and_clears_snapshot(self, env):
        await _prepare(env)
        env.world.fail_once("clear")
        with pytest.raises(RuntimeError):
            await env.run(callback_update("dupsave_tu_700"))
        assert env.world.count_saved() == 1 and env.world.pending["tu_700"]["payload"] != {}

        await env.run(text_update())  # retried original update: record exists, marker is the owner
        assert env.world.pending["tu_700"]["payload"] == {}
        assert env.world.pending["tu_700"]["duplicate_decision"] == "save"
        assert env.world.count_saved() == 1
        assert env.llm.await_count == 0 and env.stt.await_count == 0
        assert "Padaria Central" in env.sent_texts()[-1]

    @pytest.mark.asyncio
    async def test_original_update_retry_after_skip_never_saves(self, env):
        await _prepare(env)
        await env.run(callback_update("dupskip_tu_700"))
        await env.run(text_update())
        assert env.world.count_saved() == 0 and env.llm.await_count == 0
        assert dup.DUPLICATE_SKIPPED_MESSAGE in env.sent_texts()[-1]

    @pytest.mark.asyncio
    async def test_failure_before_delivery_replays_from_persisted_effect(self, env):
        await _prepare(env)
        env.send.side_effect = [RuntimeError("down"), {"message_id": 1}]
        with pytest.raises(RuntimeError):
            await env.run(callback_update("dupsave_tu_700"))
        inserts_after_first = env.world.inserts
        await env.run(callback_update("dupsave_tu_700"))
        assert env.world.count_saved() == 1
        assert env.world.inserts == inserts_after_first  # snapshot already cleared, no new write
        assert "Padaria Central" in env.sent_texts()[-1]

    @pytest.mark.asyncio
    async def test_decision_not_persisted_means_no_effect(self, env):
        await _prepare(env)
        env.world.fail_once("decide")
        with pytest.raises(RuntimeError):
            await env.run(callback_update("dupsave_tu_700"))
        assert env.world.count_saved() == 0 and env.world.pending["tu_700"]["duplicate_decision"] is None

    @pytest.mark.asyncio
    async def test_save_accepted_in_time_completes_after_deadline_on_retry(self, env):
        await _prepare(env)
        env.world.fail_once("insert")
        with pytest.raises(RuntimeError):
            await env.run(callback_update("dupsave_tu_700"))
        env.world.expire("tu_700")
        await env.run(callback_update("dupsave_tu_700"))
        assert env.world.count_saved() == 1
        assert dup.DUPLICATE_EXPIRED_MESSAGE not in env.sent_texts()

    @pytest.mark.asyncio
    async def test_persisted_save_without_payload_or_effect_fails_closed(self, env):
        await _prepare(env)
        env.world.pending["tu_700"]["duplicate_decision"] = "save"
        env.world.pending["tu_700"]["payload"] = {}
        with pytest.raises(RuntimeError):
            await env.run(callback_update("dupsave_tu_700"))
        assert env.world.count_saved() == 0

    @pytest.mark.asyncio
    async def test_original_update_replay_after_save_shows_the_saved_result(self, env):
        await _prepare(env)
        await env.run(callback_update("dupsave_tu_700"))
        env.send.reset_mock()
        await env.run(text_update())
        assert env.llm.await_count == 0 and env.world.count_saved() == 1


class TestExpiredAndRaces:
    @pytest.mark.asyncio
    async def test_click_after_deadline_expires_without_saving(self, env):
        await _prepare(env)
        env.world.expire("tu_700")
        await env.run(callback_update("dupsave_tu_700"))
        assert env.world.pending["tu_700"]["duplicate_decision"] == "expired"
        assert env.world.pending["tu_700"]["payload"] == {}
        assert env.world.inserts == 0
        env.remove.assert_awaited_once()
        assert env.sent_texts() == [dup.DUPLICATE_EXPIRED_MESSAGE]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("first,second,winner", [("dupskip", "dupsave", "skip"), ("dupsave", "dupskip", "save")])
    async def test_opposite_clicks_first_decision_wins_and_never_changes(self, env, first, second, winner):
        await _prepare(env)
        await env.run(callback_update(f"{first}_tu_700", update_id=901))
        await env.run(callback_update(f"{second}_tu_700", update_id=902))
        assert env.world.pending["tu_700"]["duplicate_decision"] == winner
        assert env.world.count_saved() == (1 if winner == "save" else 0)

    @pytest.mark.asyncio
    async def test_repeated_clicks_do_not_duplicate(self, env):
        await _prepare(env)
        for update_id in (901, 902, 903):
            await env.run(callback_update("dupsave_tu_700", update_id=update_id))
        assert env.world.count_saved() == 1


class TestBindingsAndBlocking:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", ["dupskip", "dupsave"])
    @pytest.mark.parametrize("chat,user", [(99, USER), (CHAT, 99)])
    async def test_other_chat_or_user_changes_nothing(self, env, action, chat, user):
        await _prepare(env)
        await env.run(callback_update(f"{action}_tu_700", chat=chat, user=user))
        row = env.world.pending["tu_700"]
        assert row["duplicate_decision"] is None and row["payload"] != {}
        assert env.world.inserts == 0
        env.edit.assert_not_awaited(); env.send.assert_not_awaited(); env.remove.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_user_changes_nothing(self, env):
        await _prepare(env)
        update = callback_update("dupsave_tu_700")
        del update["callback_query"]["from"]
        await env.run(update)
        assert env.world.pending["tu_700"]["duplicate_decision"] is None
        env.edit.assert_not_awaited(); env.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_marker_without_user_binding_is_never_decided(self, env):
        await _prepare(env)
        env.world.pending["tu_700"]["origin_user_id"] = None
        await env.run(callback_update("dupsave_tu_700"))
        assert env.world.pending["tu_700"]["duplicate_decision"] is None and env.world.inserts == 0

    @pytest.mark.asyncio
    async def test_missing_marker_is_a_silent_noop(self, env):
        await env.run(callback_update("dupsave_nope"))
        env.edit.assert_not_awaited(); env.send.assert_not_awaited(); assert env.world.inserts == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", ["receipt_batch", "delete_confirmation", "mystery"])
    @pytest.mark.parametrize("action", ["dupskip", "dupsave"])
    async def test_duplicate_actions_on_other_kinds_do_nothing(self, env, kind, action):
        env.world.pending["x1"] = {
            "id": "x1", "kind": kind, "payload": {"ids": [1]}, "origin_chat_id": "1", "origin_user_id": "2",
            "source_update_id": 5, "duplicate_decision": None,
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        }
        await env.run(callback_update(f"{action}_x1"))
        assert env.world.pending["x1"]["duplicate_decision"] is None and env.world.inserts == 0
        env.edit.assert_not_awaited(); env.send.assert_not_awaited(); env.remove.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", ["aprovar", "editar", "confirmdel", "cancelar"])
    async def test_legacy_callbacks_on_duplicate_or_unknown_kinds_are_blocked(self, env, action):
        await _prepare(env)
        env.world.pending["x1"] = {
            "id": "x1", "kind": "mystery", "payload": {"ids": [1]}, "origin_chat_id": "1", "origin_user_id": "2",
            "source_update_id": 5, "duplicate_decision": None,
            "expires_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        }
        with patch.object(handlers, "gravar_lote_no_banco_com_registros", MagicMock()) as grava, patch.object(
            handlers, "supabase", MagicMock()
        ) as supabase:
            for cache_id in ("tu_700", "x1"):
                await env.run(callback_update(f"{action}_{cache_id}"))
        grava.assert_not_called()
        supabase.table.assert_not_called()
        assert env.world.pending["tu_700"]["duplicate_decision"] is None and "x1" in env.world.pending
        env.edit.assert_not_awaited(); env.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_payload_on_click_fails_closed_without_deciding(self, env):
        await _prepare(env)
        env.world.pending["tu_700"]["payload"] = {"transaction": {}}
        await env.run(callback_update("dupsave_tu_700"))
        assert env.world.pending["tu_700"]["duplicate_decision"] is None and env.world.inserts == 0
        assert dup.DUPLICATE_INVALID_MESSAGE in env.sent_texts()[0]


class TestExpiryBeatsPayloadValidation:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", ["dupsave", "dupskip"])
    @pytest.mark.parametrize("payload", [{}, {"transaction": {}}, {"transaction": {}, "matched_record": {}}])
    async def test_expired_click_with_invalid_payload_reports_expired(self, env, action, payload):
        await _prepare(env)
        env.world.pending["tu_700"]["payload"] = payload
        env.world.expire("tu_700")
        await env.run(callback_update(f"{action}_tu_700"))
        assert env.world.pending["tu_700"]["duplicate_decision"] == "expired"
        assert env.world.inserts == 0
        assert dup.DUPLICATE_EXPIRED_MESSAGE in env.sent_texts()
        assert dup.DUPLICATE_INVALID_MESSAGE not in " ".join(env.sent_texts())

    @pytest.mark.asyncio
    async def test_expired_click_with_missing_deadline_is_expired(self, env):
        await _prepare(env)
        env.world.pending["tu_700"]["payload"] = {}
        env.world.pending["tu_700"]["expires_at"] = None
        await env.run(callback_update("dupsave_tu_700"))
        assert env.world.pending["tu_700"]["duplicate_decision"] == "expired" and env.world.inserts == 0


class TestProcessorReplay:
    def _deps(self, claim_status=1):
        handler = handlers.processar_update_assincrono
        return ProcessorDeps(
            claim_update=AsyncMock(return_value=UpdateClaim(claimed=True, status="processing", attempt_count=claim_status, progress_message_id=None)),
            update_stage=AsyncMock(),
            mark_completed=AsyncMock(),
            mark_failed=AsyncMock(),
            mark_terminal_failed=AsyncMock(),
            prepare_terminal_failure=AsyncMock(),
            reserve_ocr_round=AsyncMock(),
            reset_ocr_rounds=AsyncMock(),
            processar_update_assincrono=handler,
            editar_mensagem_telegram=AsyncMock(),
        )

    @pytest.mark.asyncio
    async def test_delivery_failure_retries_through_the_existing_mechanism_without_duplicating(self, env):
        env.world.seed_expense()
        env.send.side_effect = [RuntimeError("down"), {"message_id": 1}]
        first = await process_telegram_update(text_update(), self._deps())
        second = await process_telegram_update(text_update(), self._deps(2))
        assert first.outcome is UpdateOutcome.RETRY and second.outcome is UpdateOutcome.DONE
        assert env.llm.await_count == 1 and env.world.inserts == 0 and env.world.store_calls == 1
        assert "dupsave_tu_700" in _keyboard_ids(env.send.await_args)

    @pytest.mark.asyncio
    async def test_lookup_failure_is_retryable_and_sanitized(self, env):
        env.world.seed_expense()
        env.world.fail_once("find", RuntimeError("secret detail 123"))
        deps = self._deps()
        result = await process_telegram_update(text_update(), deps)
        assert result.outcome is UpdateOutcome.RETRY
        assert deps.mark_failed.await_args.kwargs["error_code"] == "RuntimeError"
        assert env.world.inserts == 0


class TestPhotoStaysOutsideDuplicateFlow:
    @pytest.mark.asyncio
    async def test_photo_routed_as_registrar_skips_lookup_and_saves(self, env):
        env.world.seed_expense()
        update = {
            "update_id": 700,
            "message": {"chat": {"id": CHAT}, "from": {"id": USER}, "photo": [{"file_id": "synthetic-photo"}]},
        }
        ocr = MagicMock(text="synthetic receipt", model="synthetic-ocr")
        with patch.object(handlers, "extrair_tabela_recibo_gemini", AsyncMock(return_value=ocr)):
            await env.run(update, progress_message_id=33)

        assert env.world.lookups == 0
        assert env.world.inserts == 1
        assert not env.world.pending
