import copy
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
from datetime import datetime, timedelta

import handlers
import security
from domain.finance import RECEIPT_ITEM_CATEGORIES, build_receipt_transaction_records, normalize_receipt_payload

CHAT = 1
USER = 2
ORIGINAL_UPDATE = 700
CACHE = "tu_700"
NOW = datetime(2026, 11, 23, 10, 0, 0)
BA = [c for c, _ in RECEIPT_ITEM_CATEGORIES].index("Bebidas Alcoólicas")
MERCADO = [c for c, _ in RECEIPT_ITEM_CATEGORIES].index("Mercado")
OUTROS = [c for c, _ in RECEIPT_ITEM_CATEGORIES].index("Outros")


def _lote(**overrides):
    base = {
        "metodo_pagamento": "Crédito",
        "conta": "Nubank",
        "desconto_global": 0.0,
        "itens": [
            {"nome": "Arroz", "valor_bruto": 30.0, "desconto_item": 0.0, "categoria": "Mercado"},
            {"nome": "Cerveja", "valor_bruto": 12.5, "desconto_item": 0.5, "categoria": "Mercado"},
            {"nome": "Pão", "valor_bruto": 5.0, "desconto_item": 0.0, "categoria": "Mercado"},
            {"nome": "Pão", "valor_bruto": 7.0, "desconto_item": 0.0, "categoria": "Mercado"},
        ],
    }
    base.update(overrides)
    return base


class World:
    """In-memory pending table whose fake RPCs enforce the same rules as the migration."""

    def __init__(self):
        self.pending = {}
        self.gastos = {}
        self.now = NOW
        self.store_calls = 0
        self.edit_calls = 0
        self.writes = 0
        self.before_edit = None
        self.before_claim = None
        self.before_discard = None
        self.failures = {}

    def fail_once(self, name, exc=None):
        self.failures[name] = exc or RuntimeError("injected")

    def _maybe_fail(self, name):
        exc = self.failures.pop(name, None)
        if exc:
            raise exc

    def expire(self, cache_id=CACHE):
        self.pending[cache_id]["expires_at"] = (self.now - timedelta(minutes=1)).isoformat()

    def _open(self, row, now):
        try:
            return row["expires_at"] is not None and datetime.fromisoformat(row["expires_at"]) > now
        except (TypeError, ValueError):
            return False

    def _bound(self, row, chat, user):
        return (
            row is not None and row["kind"] == "receipt_batch" and row["origin_chat_id"] is not None
            and row["origin_user_id"] is not None and row["origin_chat_id"] == str(chat) and row["origin_user_id"] == str(user)
        )

    def _view(self, row):
        return {**copy.deepcopy(row), "preview_json": {"summary": "Cupom pendente"}}

    # --- security.py replacements ---
    def store_pending_item(self, payload, *, kind=None, origin_chat_id=None, origin_user_id=None, source_update_id=None):
        self.store_calls += 1
        cache_id = f"tu_{source_update_id}"
        if cache_id not in self.pending:
            self.pending[cache_id] = {
                "id": cache_id,
                "kind": kind,
                "payload": copy.deepcopy(payload),
                "origin_chat_id": str(origin_chat_id),
                "origin_user_id": str(origin_user_id) if origin_user_id is not None else None,
                "source_update_id": source_update_id,
                "expires_at": (self.now + timedelta(hours=24)).isoformat(),
                "payload_revision": 0,
                "approval_claimed_revision": None,
            }
        row = self.pending[cache_id]
        return {"id": cache_id, "kind": kind, "payload": copy.deepcopy(row["payload"]), "source_update_id": source_update_id}

    def load_pending_item(self, cache_id):
        row = self.pending.get(cache_id)
        return self._view(row) if row else None

    def load_by_source(self, source_update_id):
        for row in self.pending.values():
            if row["source_update_id"] == source_update_id:
                return self._view(row)
        return None

    def edit_rpc(self, cache_id, chat_id, user_id, expected_revision, payload):
        self.edit_calls += 1
        if self.before_edit:
            hook, self.before_edit = self.before_edit, None
            hook()
        row = self.pending.get(cache_id)
        if not self._bound(row, chat_id, user_id) or row["approval_claimed_revision"] is not None:
            return None
        if row["payload_revision"] != expected_revision or not self._open(row, self.now):
            return None
        row["payload"] = copy.deepcopy(payload)
        row["payload_revision"] += 1
        self.writes += 1
        self._maybe_fail("after_edit")
        return row["payload_revision"]

    def _claim(self, row, revision):
        if row["approval_claimed_revision"] is not None:
            return "already_claimed", row["approval_claimed_revision"]
        if not self._open(row, self.now):
            return "expired", None
        if revision is not None and row["payload_revision"] != revision:
            return "stale", row["payload_revision"]
        row["approval_claimed_revision"] = row["payload_revision"]
        return "claimed", row["payload_revision"]

    def claim_rpc(self, cache_id, chat_id, user_id, revision):
        if self.before_claim:
            hook, self.before_claim = self.before_claim, None
            hook()
        row = self.pending.get(cache_id)
        if not self._bound(row, chat_id, user_id):
            return "unavailable", None
        return self._claim(row, revision)

    def claim_admin(self, cache_id):
        row = self.pending.get(cache_id)
        if row is None or row["kind"] != "receipt_batch":
            return "unavailable", None
        return self._claim(row, None)

    def discard_rpc(self, cache_id, chat_id, user_id):
        if self.before_discard:
            hook, self.before_discard = self.before_discard, None
            hook()
        row = self.pending.get(cache_id)
        if not self._bound(row, chat_id, user_id):
            return "unavailable"
        if row["approval_claimed_revision"] is not None:
            return "claimed"
        del self.pending[cache_id]
        return "discarded"

    def delete(self, cache_id):
        self.pending.pop(cache_id, None)

    def mark_summary_sent(self, cache_id, payload):
        self.pending[cache_id]["payload"] = {**payload, "_approval_summary_sent": True}

    # --- db_repository.py replacements ---
    def gravar(self, dados_lote, *, source_update_id=None, origin_chat_id=None):
        self._maybe_fail("gravar")
        records, total = build_receipt_transaction_records(dados_lote, "2026-11-23")
        saved = []
        for index, record in enumerate(records, start=1):
            key = (source_update_id, f"receipt:{index:04d}")
            self.gastos.setdefault(key, {**record, "source_origin_chat_id": origin_chat_id})
            saved.append(self.gastos[key])
        return len(saved), total, saved

    def records_by_source(self, source_update_id, origin_chat_id=None):
        return [r for (source, _), r in self.gastos.items() if source == source_update_id]


def text_update(update_id=ORIGINAL_UPDATE, chat=CHAT, user=USER):
    return {"update_id": update_id, "message": {"chat": {"id": chat}, "from": {"id": user}, "text": "cupom"}}


def callback_update(data, update_id=900, chat=CHAT, user=USER, message_id=50):
    return {
        "update_id": update_id,
        "callback_query": {"id": "cb", "data": data, "from": {"id": user}, "message": {"chat": {"id": chat}, "message_id": message_id}},
    }


class Env:
    def __init__(self, world):
        self.world = world
        self.llm = AsyncMock(return_value={"intencao": "registrar_lote_pendente", "dados_lote": _lote()})
        self.send = AsyncMock(return_value={"message_id": 11})
        self.edit = AsyncMock(return_value={})
        self.remove = AsyncMock()
        self.answer = AsyncMock()
        self.next_update = 900

    async def run(self, update, **kwargs):
        kwargs.setdefault("source_update_id", update["update_id"])
        return await handlers.processar_update_assincrono(update, **kwargs)

    async def click(self, data, **kwargs):
        self.next_update += 1
        return await self.run(callback_update(data, update_id=self.next_update, **kwargs))

    def last_edit(self):
        return self.edit.await_args

    def last_text(self):
        return self.edit.await_args.args[2]


def buttons(call):
    markup = next((arg for arg in call.args[2:] if isinstance(arg, dict)), None)
    if markup is None:
        return []
    return [(b["text"], b["callback_data"]) for row in markup["inline_keyboard"] for b in row]


def callbacks(call):
    return [data for _, data in buttons(call)]


@pytest.fixture
def env():
    world = World()
    environment = Env(world)
    patches = [
        patch.object(handlers, "processar_texto_com_llm", environment.llm),
        patch.object(handlers, "enviar_acao_telegram", AsyncMock()),
        patch.object(handlers, "responder_callback_telegram", environment.answer),
        patch.object(handlers, "allow_request", return_value=True),
        patch.object(handlers, "enviar_mensagem_telegram", environment.send),
        patch.object(handlers, "editar_mensagem_telegram", environment.edit),
        patch.object(handlers, "remover_teclado_mensagem_telegram", environment.remove),
        patch.object(handlers, "get_brasilia_time", lambda: world.now),
        patch.object(security, "get_brasilia_time", lambda: world.now),
        patch.object(handlers, "store_pending_item", world.store_pending_item),
        patch.object(handlers, "load_pending_item", world.load_pending_item),
        patch.object(handlers, "load_pending_item_by_source_update_id", world.load_by_source),
        patch.object(handlers, "edit_receipt_pending", world.edit_rpc),
        patch.object(handlers, "claim_receipt_approval", world.claim_rpc),
        patch.object(handlers, "discard_receipt_pending", world.discard_rpc),
        patch.object(handlers, "delete_pending_item", world.delete),
        patch.object(handlers, "mark_pending_summary_sent", world.mark_summary_sent),
        patch.object(handlers, "gravar_lote_no_banco_com_registros", world.gravar),
        patch.object(handlers, "load_records_by_source_update_id", world.records_by_source),
    ]
    for p in patches:
        p.start()
    yield environment
    for p in reversed(patches):
        p.stop()


async def _prepare(env, lote=None):
    if lote is not None:
        env.llm.return_value = {"intencao": "registrar_lote_pendente", "dados_lote": lote}
    await env.run(text_update())
    env.send.reset_mock()
    env.edit.reset_mock()
    env.remove.reset_mock()


def _categories(env):
    return [item["categoria"] for item in env.world.pending[CACHE]["payload"]["itens"]]


class TestSummaryKeyboard:
    @pytest.mark.asyncio
    async def test_summary_offers_category_editor_and_keeps_text_edit(self, env):
        await env.run(text_update())
        call = env.send.await_args
        assert callbacks(call) == ["ca:0:tu_700", "ce:0:tu_700", "editar_tu_700", "cancelar_tu_700"]
        labels = [text for text, _ in buttons(call)]
        assert any("Editar categorias" in label for label in labels)
        assert any(label.endswith("Editar") for label in labels)

    def test_every_callback_fits_the_telegram_64_byte_limit(self):
        long_id = "tu_" + "f" * 20
        for data in (
            handlers._receipt_callback("ca", 999_999_999, long_id),
            handlers._receipt_callback("cc", 999_999_999, long_id, 13),
        ):
            assert len(data.encode("utf-8")) <= 64
            assert handlers._parse_receipt_callback(data) is not None


class TestNavigation:
    @pytest.mark.asyncio
    async def test_list_shows_position_name_net_value_and_category(self, env):
        await _prepare(env)
        await env.click("ce:0:tu_700")
        text = env.last_text()
        assert "#1 Arroz" in text and "#2 Cerveja" in text and "#3 Pão" in text and "#4 Pão" in text
        assert "R$ 12.00" in text and "Mercado" in text
        assert env.last_edit().args[:2] == (CHAT, 50)
        assert callbacks(env.last_edit()) == ["ci:1:tu_700", "ci:2:tu_700", "ci:3:tu_700", "ci:4:tu_700", "cv:0:tu_700"]
        assert env.world.edit_calls == 0 and env.world.pending[CACHE]["payload_revision"] == 0

    @pytest.mark.asyncio
    async def test_pagination_keeps_original_positions(self, env):
        itens = [{"nome": f"Item {i}", "valor_bruto": 1.0, "desconto_item": 0.0, "categoria": "Mercado"} for i in range(1, 20)]
        await _prepare(env, _lote(itens=itens))
        await env.click("cl:1:tu_700")
        data = callbacks(env.last_edit())
        assert [d for d in data if d.startswith("ci:")] == [f"ci:{n}:tu_700" for n in range(9, 17)]
        assert "cl:0:tu_700" in data and "cl:2:tu_700" in data and "cv:0:tu_700" in data
        assert "#9 Item 9" in env.last_text() and "#8 Item 8" not in env.last_text()
        await env.click("cl:2:tu_700")
        assert [d for d in callbacks(env.last_edit()) if d.startswith("ci:")] == ["ci:17:tu_700", "ci:18:tu_700", "ci:19:tu_700"]
        assert "cl:3:tu_700" not in callbacks(env.last_edit())

    @pytest.mark.asyncio
    async def test_item_screen_shows_category_and_derived_nature(self, env):
        await _prepare(env)
        await env.click("ci:2:tu_700")
        text = env.last_text()
        assert "#2" in text and "Cerveja" in text and "R$ 12.00" in text and "Mercado" in text and "Essencial" in text
        assert callbacks(env.last_edit()) == ["cs:2:tu_700", "cl:0:tu_700", "cv:0:tu_700"]

    @pytest.mark.asyncio
    async def test_selector_lists_canonical_categories_marking_the_current_one(self, env):
        await _prepare(env)
        await env.click("cs:2:tu_700")
        options = [(text, data) for text, data in buttons(env.last_edit()) if data.startswith("cc:")]
        assert [data for _, data in options] == [f"cc:2:{i}:tu_700" for i in range(len(RECEIPT_ITEM_CATEGORIES))]
        marked = [text for text, _ in options if "✓" in text]
        assert marked == ["✓ Mercado · Essencial"]
        labels = " ".join(text for text, _ in options)
        assert "Bebidas Alcoólicas · Lazer" in labels
        assert "Salário" not in labels and "Gasto" not in labels and "Despesa" not in labels
        assert callbacks(env.last_edit())[-1] == "ci:2:tu_700"

    @pytest.mark.asyncio
    async def test_back_returns_to_summary_without_changes(self, env):
        await _prepare(env)
        for data in ("ce:0:tu_700", "ci:2:tu_700", "cs:2:tu_700", "ci:2:tu_700", "cl:0:tu_700", "cv:0:tu_700"):
            await env.click(data)
        assert "Resumo do Cupom" in env.last_text()
        assert callbacks(env.last_edit())[:2] == ["ca:0:tu_700", "ce:0:tu_700"]
        assert env.world.edit_calls == 0 and env.world.gastos == {}
        assert _categories(env) == ["Mercado"] * 4

    @pytest.mark.asyncio
    async def test_invalid_positions_fall_back_to_the_list_without_writing(self, env):
        await _prepare(env)
        for data in ("ci:9:tu_700", "cs:0:tu_700", "cc:9:1:tu_700", "cc:1:99:tu_700"):
            await env.click(data)
            assert callbacks(env.last_edit())[0] == "ci:1:tu_700"
        assert env.world.edit_calls == 0


class TestCategoryChange:
    @pytest.mark.asyncio
    async def test_beer_moves_to_alcohol_while_rice_stays_in_market(self, env):
        await _prepare(env)
        deadline = env.world.pending[CACHE]["expires_at"]
        await env.click(f"cc:2:{BA}:tu_700")

        row = env.world.pending[CACHE]
        assert row["payload_revision"] == 1 and row["expires_at"] == deadline
        assert _categories(env) == ["Mercado", "Bebidas Alcoólicas", "Mercado", "Mercado"]
        expected = _lote()
        expected["itens"][1]["categoria"] = "Bebidas Alcoólicas"
        assert row["payload"] == normalize_receipt_payload(expected)

        text = env.last_text()
        assert "Bebidas Alcoólicas (Lazer)** - R$ 12.00" in text
        assert "Mercado (Essencial)** - R$ 42.00" in text
        assert "Arroz (R$ 30.00)" in text
        assert "Total Líquido Validado: R$ 54.00" in text
        assert callbacks(env.last_edit()) == ["ca:1:tu_700", "ce:1:tu_700", "editar_tu_700", "cancelar_tu_700"]
        assert env.world.gastos == {}

    @pytest.mark.asyncio
    async def test_same_category_does_not_write(self, env):
        await _prepare(env)
        await env.click(f"cc:1:{MERCADO}:tu_700")
        assert env.world.edit_calls == 0 and env.world.pending[CACHE]["payload_revision"] == 0
        assert "Resumo do Cupom" in env.last_text()
        assert callbacks(env.last_edit())[0] == "ca:0:tu_700"

    @pytest.mark.asyncio
    async def test_corrections_accumulate(self, env):
        await _prepare(env)
        await env.click(f"cc:2:{BA}:tu_700")
        await env.click(f"cc:4:{OUTROS}:tu_700")
        assert env.world.pending[CACHE]["payload_revision"] == 2
        assert _categories(env) == ["Mercado", "Bebidas Alcoólicas", "Mercado", "Outros"]
        assert callbacks(env.last_edit())[0] == "ca:2:tu_700"

    @pytest.mark.asyncio
    async def test_global_discount_goes_to_the_largest_group_after_regrouping(self, env):
        await _prepare(env, _lote(desconto_global=2.0))
        await env.click(f"cc:2:{BA}:tu_700")
        text = env.last_text()
        assert "Desconto Global Aplicado: R$ 2.00" in text
        assert "Mercado (Essencial)** - R$ 40.00" in text
        assert env.world.pending[CACHE]["payload"]["desconto_global"] == 2.0

    @pytest.mark.asyncio
    async def test_change_is_persisted_before_display_and_replay_does_not_lose_it(self, env):
        await _prepare(env)
        env.edit.side_effect = [RuntimeError("telegram down"), {}, {}]
        with pytest.raises(RuntimeError):
            await env.run(callback_update(f"cc:2:{BA}:tu_700", update_id=950))
        assert env.world.pending[CACHE]["payload_revision"] == 1

        await env.run(callback_update(f"cc:2:{BA}:tu_700", update_id=950))  # same update retried
        assert env.world.pending[CACHE]["payload_revision"] == 1 and env.world.writes == 1
        assert callbacks(env.last_edit())[0] == "ca:1:tu_700"

        env.send.reset_mock()
        await env.run(text_update())  # original update replayed (e.g. after a restart)
        assert env.llm.await_count == 1 and env.world.store_calls == 1
        call = env.send.await_args
        assert "Bebidas Alcoólicas (Lazer)" in call.args[1]
        assert callbacks(call)[0] == "ca:1:tu_700"

    @pytest.mark.asyncio
    async def test_concurrent_edit_is_reapplied_on_the_new_revision(self, env):
        await _prepare(env)

        def other_edit():
            row = env.world.pending[CACHE]
            row["payload"]["itens"][3]["categoria"] = "Outros"
            row["payload_revision"] += 1

        env.world.before_edit = other_edit
        await env.click(f"cc:2:{BA}:tu_700")
        assert env.world.pending[CACHE]["payload_revision"] == 2
        assert _categories(env) == ["Mercado", "Bebidas Alcoólicas", "Mercado", "Outros"]
        assert callbacks(env.last_edit())[0] == "ca:2:tu_700"

    @pytest.mark.asyncio
    async def test_failure_of_the_edit_rpc_writes_nothing(self, env):
        await _prepare(env)
        with patch.object(handlers, "edit_receipt_pending", MagicMock(side_effect=RuntimeError("db down"))):
            with pytest.raises(RuntimeError):
                await env.click(f"cc:2:{BA}:tu_700")
        assert env.world.pending[CACHE]["payload_revision"] == 0
        env.edit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_logs_do_not_contain_item_names(self, env):
        with patch.object(handlers, "logger") as log:
            await _prepare(env)
            await env.click("ce:0:tu_700")
            await env.click(f"cc:2:{BA}:tu_700")
            await env.click("ca:1:tu_700")
        logged = " ".join(str(c) for c in log.method_calls)
        assert "receipt_item_category_changed" in logged
        assert "Cerveja" not in logged and "Arroz" not in logged


class TestApproval:
    @pytest.mark.asyncio
    async def test_approval_saves_the_displayed_version_with_original_identity(self, env):
        await _prepare(env)
        await env.click(f"cc:2:{BA}:tu_700")
        await env.click("ca:1:tu_700")

        assert {key[0] for key in env.world.gastos} == {ORIGINAL_UPDATE}
        saved = {(r["natureza"], r["categoria"], r["valor"]) for r in env.world.gastos.values()}
        assert saved == {("Essencial", "Mercado", 42.0), ("Lazer", "Bebidas Alcoólicas", 12.0)}
        assert all(r["conta"] == "Nubank" and r["metodo_pagamento"] == "Crédito" for r in env.world.gastos.values())
        assert CACHE not in env.world.pending
        env.remove.assert_awaited_once_with(CHAT, 50)
        assert "Cupom salvo" in env.send.await_args.args[1]

    @pytest.mark.asyncio
    async def test_unedited_receipt_still_approves_with_legacy_button(self, env):
        await _prepare(env)
        await env.click("aprovar_tu_700")
        assert len(env.world.gastos) == 1 and CACHE not in env.world.pending

    @pytest.mark.asyncio
    @pytest.mark.parametrize("old_button", ["ca:0:tu_700", "aprovar_tu_700"])
    async def test_old_approval_button_only_shows_the_current_summary(self, env, old_button):
        await _prepare(env)
        await env.click(f"cc:2:{BA}:tu_700")
        await env.click(old_button)
        assert env.world.gastos == {}
        assert env.world.pending[CACHE]["approval_claimed_revision"] is None
        text = env.last_text()
        assert "mudou" in text and "Bebidas Alcoólicas (Lazer)" in text
        assert callbacks(env.last_edit())[0] == "ca:1:tu_700"
        env.remove.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_edit_between_screen_and_claim_is_stale(self, env):
        await _prepare(env)

        def other_edit():
            env.world.pending[CACHE]["payload"]["itens"][1]["categoria"] = "Bebidas Alcoólicas"
            env.world.pending[CACHE]["payload_revision"] = 1

        env.world.before_claim = other_edit
        await env.click("ca:0:tu_700")
        assert env.world.gastos == {} and callbacks(env.last_edit())[0] == "ca:1:tu_700"

    @pytest.mark.asyncio
    async def test_approval_retry_after_failure_resumes_the_locked_revision(self, env):
        await _prepare(env)
        await env.click(f"cc:2:{BA}:tu_700")
        env.world.fail_once("gravar")
        with pytest.raises(RuntimeError):
            await env.click("ca:1:tu_700")
        assert env.world.pending[CACHE]["approval_claimed_revision"] == 1

        await env.click(f"cc:2:{MERCADO}:tu_700")  # editing is closed once approval started
        assert "aprovação" in env.last_text().lower() and env.world.writes == 1

        await env.click("ca:1:tu_700")
        assert len(env.world.gastos) == 2 and CACHE not in env.world.pending

    @pytest.mark.asyncio
    async def test_double_approval_does_not_duplicate(self, env):
        await _prepare(env)
        await env.click("ca:0:tu_700")
        await env.click("ca:0:tu_700")
        assert len(env.world.gastos) == 1
        assert env.last_text() == handlers.RECEIPT_NOT_PENDING_MESSAGE
        assert "TG-" not in env.last_text() and callbacks(env.last_edit()) == []

    @pytest.mark.asyncio
    async def test_approval_already_claimed_elsewhere_completes_idempotently(self, env):
        await _prepare(env)
        await env.click(f"cc:2:{BA}:tu_700")
        assert env.world.claim_admin(CACHE) == ("claimed", 1)
        await env.click("ca:0:tu_700")
        saved = {r["categoria"] for r in env.world.gastos.values()}
        assert saved == {"Mercado", "Bebidas Alcoólicas"}

    @pytest.mark.asyncio
    async def test_expired_receipt_cannot_be_approved(self, env):
        await _prepare(env)
        env.world.expire()
        await env.click("ca:0:tu_700")
        assert env.world.gastos == {}
        assert env.world.pending[CACHE]["approval_claimed_revision"] is None

    @pytest.mark.asyncio
    async def test_claim_from_admin_between_load_and_edit_blocks_the_edit(self, env):
        await _prepare(env)
        env.world.before_edit = lambda: env.world.claim_admin(CACHE)
        await env.click(f"cc:2:{BA}:tu_700")
        assert env.world.pending[CACHE]["payload_revision"] == 0
        assert _categories(env)[1] == "Mercado"
        assert "aprovação" in env.last_text().lower()


class TestCancelAndLegacyEdit:
    @pytest.mark.asyncio
    async def test_cancel_saves_nothing(self, env):
        await _prepare(env)
        await env.click(f"cc:2:{BA}:tu_700")
        await env.click("cancelar_tu_700")
        assert CACHE not in env.world.pending and env.world.gastos == {}
        assert "Cancelada" in env.last_text()

    @pytest.mark.asyncio
    async def test_cancel_after_approval_started_is_refused(self, env):
        await _prepare(env)
        env.world.claim_admin(CACHE)
        await env.click("cancelar_tu_700")
        assert CACHE in env.world.pending
        assert "aprovação" in env.last_text().lower()

    @pytest.mark.asyncio
    async def test_legacy_text_edit_still_works_and_shows_corrected_categories(self, env):
        await _prepare(env)
        await env.click(f"cc:2:{BA}:tu_700")
        await env.click("editar_tu_700")
        assert "CUPOM_EDIT" in env.last_text() and "[Bebidas Alcoólicas] Cerveja" in env.last_text()
        assert CACHE not in env.world.pending

    @pytest.mark.asyncio
    async def test_legacy_text_edit_after_approval_started_is_refused(self, env):
        await _prepare(env)
        env.world.claim_admin(CACHE)
        await env.click("editar_tu_700")
        assert CACHE in env.world.pending
        assert "CUPOM_EDIT" not in env.last_text()


class TestUnavailable:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("data", ["ce:0:tu_700", "ci:1:tu_700", "cs:1:tu_700", f"cc:2:{BA}:tu_700", "cv:0:tu_700"])
    async def test_expired_receipt_cannot_be_edited_and_is_not_deleted(self, env, data):
        await _prepare(env)
        env.world.expire()
        await env.click(data)
        assert "não está mais disponível" in env.last_text()
        assert callbacks(env.last_edit()) == []
        assert CACHE in env.world.pending and env.world.pending[CACHE]["payload_revision"] == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("expires_at", [None, "garbage"])
    async def test_missing_or_unreadable_deadline_fails_closed(self, env, expires_at):
        await _prepare(env)
        env.world.pending[CACHE]["expires_at"] = expires_at
        await env.click(f"cc:2:{BA}:tu_700")
        assert env.world.writes == 0 and "não está mais disponível" in env.last_text()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("decision", ["approve", "reject"])
    async def test_receipt_handled_in_the_panel_is_unavailable_without_recreation(self, env, decision):
        await _prepare(env)
        if decision == "approve":
            env.world.claim_admin(CACHE)
        env.world.delete(CACHE)
        for data in ("ce:0:tu_700", f"cc:2:{BA}:tu_700", "ca:0:tu_700"):
            await env.click(data)
            assert "não está mais disponível" in env.last_text() or "não está mais pendente" in env.last_text()
        assert env.world.pending == {} and env.world.store_calls == 1 and env.world.gastos == {}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("chat,user", [(99, USER), (CHAT, 99)])
    @pytest.mark.parametrize("data", ["ce:0:tu_700", f"cc:2:{BA}:tu_700", "ca:0:tu_700", "cv:0:tu_700"])
    async def test_other_chat_or_sender_changes_nothing(self, env, chat, user, data):
        await _prepare(env)
        await env.click(data, chat=chat, user=user)
        env.edit.assert_not_awaited()
        assert env.world.pending[CACHE]["payload_revision"] == 0 and env.world.gastos == {}

    @pytest.mark.asyncio
    async def test_receipt_without_sender_binding_fails_closed(self, env):
        await _prepare(env)
        env.world.pending[CACHE]["origin_user_id"] = None
        await env.click(f"cc:2:{BA}:tu_700")
        await env.click("aprovar_tu_700")
        assert env.world.writes == 0 and env.world.gastos == {}

    @pytest.mark.asyncio
    async def test_other_kinds_are_ignored(self, env):
        await _prepare(env)
        env.world.pending[CACHE]["kind"] = "delete_confirmation"
        await env.click("ce:0:tu_700")
        env.edit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_payload_fails_closed(self, env):
        await _prepare(env)
        env.world.pending[CACHE]["payload"] = {"itens": "broken"}
        await env.click("ce:0:tu_700")
        assert "não está mais disponível" in env.last_text()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "data",
        [
            "ce:abc:tu_700", "cc:2:tu_700", "ce:1:2:tu_700", "zz:1:tu_700", "ce:01:tu_700", "ce:-1:tu_700",
            "ce:0:tu 700", "ce:0:", "ce:0:tu_700:x", "ce:0:" + "a" * 60, ":::", "ce:0:tu_700\n",
        ],
    )
    async def test_malformed_callbacks_are_ignored(self, env, data):
        await _prepare(env)
        with patch.object(handlers, "load_pending_item", MagicMock()) as load:
            await env.click(data)
        load.assert_not_called()
        env.edit.assert_not_awaited()
        env.answer.assert_awaited()



class TestExpiredLegacyCallbacks:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("data", ["cancelar_tu_700", "editar_tu_700", "aprovar_tu_700"])
    async def test_expired_receipt_is_discarded_atomically(self, env, data):
        await _prepare(env)
        env.world.expire()
        with patch.object(handlers, "delete_pending_item", MagicMock()) as raw_delete:
            await env.click(data)
        raw_delete.assert_not_called()
        assert CACHE not in env.world.pending and env.world.gastos == {}
        assert "expirado ou já processado" in env.last_text()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("data", ["cancelar_tu_700", "editar_tu_700"])
    async def test_claim_between_read_and_discard_keeps_the_receipt(self, env, data):
        await _prepare(env)
        env.world.expire()
        env.world.before_discard = lambda: env.world.pending[CACHE].update(approval_claimed_revision=0)
        await env.click(data)
        assert CACHE in env.world.pending and env.world.pending[CACHE]["approval_claimed_revision"] == 0
        assert env.last_text() == handlers.RECEIPT_APPROVAL_STARTED_MESSAGE

    @pytest.mark.asyncio
    @pytest.mark.parametrize("chat,user", [(99, USER), (CHAT, 99)])
    async def test_other_chat_or_sender_does_not_discard_an_expired_receipt(self, env, chat, user):
        await _prepare(env)
        env.world.expire()
        discard = MagicMock(side_effect=env.world.discard_rpc)
        with patch.object(handlers, "discard_receipt_pending", discard):
            await env.click("cancelar_tu_700", chat=chat, user=user)
        discard.assert_not_called()
        assert CACHE in env.world.pending
        assert "não autorizada" in env.last_text()

    @pytest.mark.asyncio
    async def test_expired_delete_confirmation_is_still_removed(self, env):
        await _prepare(env)
        env.world.pending[CACHE]["kind"] = "delete_confirmation"
        env.world.expire()
        discard = MagicMock()
        with patch.object(handlers, "discard_receipt_pending", discard):
            await env.click("confirmdel_tu_700")
        discard.assert_not_called()
        assert CACHE not in env.world.pending
        assert "expirado ou já processado" in env.last_text()


class TestFailClosedBranches:
    @pytest.mark.asyncio
    async def test_receipt_removed_during_the_edit_retry(self, env):
        await _prepare(env)
        env.world.before_edit = lambda: env.world.delete(CACHE)
        await env.click(f"cc:2:{BA}:tu_700")
        assert "não está mais disponível" in env.last_text() and env.world.writes == 0

    @pytest.mark.asyncio
    async def test_same_choice_applied_concurrently_is_not_written_twice(self, env):
        await _prepare(env)

        def same_edit():
            env.world.pending[CACHE]["payload"]["itens"][1]["categoria"] = "Bebidas Alcoólicas"
            env.world.pending[CACHE]["payload_revision"] = 1

        env.world.before_edit = same_edit
        await env.click(f"cc:2:{BA}:tu_700")
        assert env.world.edit_calls == 1 and env.world.writes == 0
        assert callbacks(env.last_edit())[0] == "ca:1:tu_700"

    @pytest.mark.asyncio
    async def test_second_lost_race_reports_unavailable(self, env):
        await _prepare(env)
        rpc = MagicMock(return_value=None)
        with patch.object(handlers, "edit_receipt_pending", rpc):
            await env.click(f"cc:2:{BA}:tu_700")
        assert rpc.call_count == 2
        assert "não está mais disponível" in env.last_text()

    @pytest.mark.asyncio
    async def test_unbound_receipt_cannot_be_approved_with_legacy_button(self, env):
        await _prepare(env)
        env.world.pending[CACHE]["origin_user_id"] = None
        await env.click("aprovar_tu_700")
        assert env.last_text() == handlers.RECEIPT_UNAVAILABLE_MESSAGE and env.world.gastos == {}

    @pytest.mark.asyncio
    async def test_receipt_without_source_identity_is_not_approved(self, env):
        await _prepare(env)
        env.world.pending[CACHE]["source_update_id"] = None
        await env.click("ca:0:tu_700")
        assert env.last_text() == handlers.RECEIPT_UNAVAILABLE_MESSAGE
        assert env.world.pending[CACHE]["approval_claimed_revision"] is None and env.world.gastos == {}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("data", ["ce:0:tu_700", "ci:1:tu_700", "cs:1:tu_700", f"cc:2:{BA}:tu_700", "cv:0:tu_700"])
    async def test_receipt_without_source_identity_is_not_offered_for_correction(self, env, data):
        await _prepare(env)
        env.world.pending[CACHE]["source_update_id"] = None
        await env.click(data)
        assert env.last_text() == handlers.RECEIPT_UNAVAILABLE_MESSAGE
        assert callbacks(env.last_edit()) == []
        assert env.world.edit_calls == 0 and env.world.pending[CACHE]["payload_revision"] == 0

    @pytest.mark.asyncio
    async def test_stale_claim_with_unusable_current_version_fails_closed(self, env):
        await _prepare(env)

        def break_it():
            env.world.pending[CACHE]["payload_revision"] = 1
            env.world.pending[CACHE]["payload"] = {"itens": []}

        env.world.before_claim = break_it
        await env.click("ca:0:tu_700")
        assert env.last_text() == handlers.RECEIPT_UNAVAILABLE_MESSAGE and env.world.gastos == {}

    @pytest.mark.asyncio
    async def test_receipt_removed_right_after_the_claim(self, env):
        await _prepare(env)
        original = env.world.claim_rpc

        def claim_then_vanish(*args):
            result = original(*args)
            env.world.delete(CACHE)
            return result

        with patch.object(handlers, "claim_receipt_approval", claim_then_vanish):
            await env.click("ca:0:tu_700")
        # A locked approval can only disappear by finishing, so the user is told it was approved.
        assert env.world.gastos == {}
        env.remove.assert_awaited_once_with(CHAT, 50)
        env.edit.assert_not_awaited()
        assert env.send.await_args.args[1] == handlers.RECEIPT_ALREADY_APPROVED_MESSAGE
        assert "TG-" not in env.send.await_args.args[1]

    @pytest.mark.asyncio
    async def test_inconsistent_claimed_revision_raises_without_saving(self, env):
        await _prepare(env)
        with patch.object(handlers, "claim_receipt_approval", MagicMock(return_value=("claimed", 3))):
            with pytest.raises(RuntimeError):
                await env.click("ca:0:tu_700")
        assert env.world.gastos == {}

    @pytest.mark.asyncio
    async def test_approval_reports_processor_stages(self, env):
        await _prepare(env)
        stages = []

        async def stage(name, progress=None):
            stages.append(name)

        await env.run(callback_update("ca:0:tu_700", update_id=990), stage_callback=stage)
        assert stages == [
            "approval_persisted", "telegram_delivery", "approval_keyboard_removed", "telegram_delivery", "approval_summary_sent",
        ]

    @pytest.mark.asyncio
    async def test_summary_already_sent_is_not_resent_on_retry(self, env):
        await _prepare(env)
        env.world.fail_once("delete_after_summary")
        original_delete = env.world.delete

        def failing_delete(cache_id):
            env.world._maybe_fail("delete_after_summary")
            original_delete(cache_id)

        with patch.object(handlers, "delete_pending_item", failing_delete):
            with pytest.raises(RuntimeError):
                await env.click("ca:0:tu_700")
            sent = env.send.await_count
            await env.click("ca:0:tu_700")
        assert env.send.await_count == sent and CACHE not in env.world.pending and len(env.world.gastos) == 1


class TestFinishApproval:
    """Once an approval started, every other button explains it and offers to finish it."""

    @staticmethod
    def _assert_finish_offer(env, revision):
        assert env.last_text() == handlers.RECEIPT_APPROVAL_STARTED_MESSAGE
        assert "Concluir aprovação" in env.last_text()
        assert buttons(env.last_edit()) == [("✅ Concluir aprovação", f"ca:{revision}:tu_700")]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "data",
        ["ce:0:tu_700", "cl:0:tu_700", "ci:1:tu_700", "cs:1:tu_700", f"cc:2:{BA}:tu_700", "cv:0:tu_700"],
    )
    async def test_editor_buttons_offer_to_finish_after_the_claim(self, env, data):
        await _prepare(env)
        env.world.claim_admin(CACHE)
        await env.click(data)
        self._assert_finish_offer(env, 0)
        assert env.world.writes == 0 and CACHE in env.world.pending

    @pytest.mark.asyncio
    @pytest.mark.parametrize("data", ["cancelar_tu_700", "editar_tu_700"])
    async def test_cancel_and_text_edit_offer_to_finish_with_the_locked_revision(self, env, data):
        await _prepare(env)
        await env.click(f"cc:2:{BA}:tu_700")
        env.world.claim_admin(CACHE)
        await env.click(data)
        self._assert_finish_offer(env, 1)
        assert CACHE in env.world.pending

    @pytest.mark.asyncio
    @pytest.mark.parametrize("data", ["cancelar_tu_700", "editar_tu_700"])
    async def test_claim_between_read_and_discard_offers_to_finish(self, env, data):
        await _prepare(env)
        env.world.expire()
        env.world.before_discard = lambda: env.world.pending[CACHE].update(approval_claimed_revision=0)
        await env.click(data)
        self._assert_finish_offer(env, 0)

    @pytest.mark.asyncio
    async def test_claim_between_load_and_edit_offers_to_finish(self, env):
        await _prepare(env)
        env.world.before_edit = lambda: env.world.claim_admin(CACHE)
        await env.click(f"cc:2:{BA}:tu_700")
        self._assert_finish_offer(env, 0)
        assert env.world.pending[CACHE]["payload_revision"] == 0

    @pytest.mark.asyncio
    async def test_finish_button_completes_the_locked_approval_once(self, env):
        await _prepare(env)
        await env.click(f"cc:2:{BA}:tu_700")
        env.world.fail_once("gravar")
        with pytest.raises(RuntimeError):
            await env.click("ca:1:tu_700")
        await env.click("cancelar_tu_700")
        finish = callbacks(env.last_edit())[0]

        await env.click(finish)
        saved = {(r["categoria"], r["valor"]) for r in env.world.gastos.values()}
        assert saved == {("Mercado", 42.0), ("Bebidas Alcoólicas", 12.0)}
        assert {key[0] for key in env.world.gastos} == {ORIGINAL_UPDATE}
        assert CACHE not in env.world.pending
        env.remove.assert_awaited_once_with(CHAT, 50)

    @pytest.mark.asyncio
    async def test_other_sender_does_not_get_the_finish_offer(self, env):
        await _prepare(env)
        env.world.claim_admin(CACHE)
        await env.click("cancelar_tu_700", user=99)
        assert not any(data.startswith("ca:") for data in callbacks(env.last_edit()))
        assert "Concluir aprovação" not in env.last_text()
        assert CACHE in env.world.pending and env.world.gastos == {}


class TestAlreadyApproved:
    @pytest.mark.asyncio
    async def test_missing_receipt_on_approval_button_is_neutral(self, env):
        await _prepare(env)
        env.world.delete(CACHE)
        await env.click("ca:0:tu_700")
        assert env.last_text() == handlers.RECEIPT_NOT_PENDING_MESSAGE
        assert "TG-" not in env.last_text() and callbacks(env.last_edit()) == []
        env.remove.assert_not_awaited()
        assert env.world.gastos == {}

    @pytest.mark.asyncio
    async def test_missing_receipt_on_legacy_approval_button_keeps_the_old_message(self, env):
        await _prepare(env)
        env.world.delete(CACHE)
        await env.click("aprovar_tu_700")
        assert "expirado ou já processado" in env.last_text()

    @pytest.mark.asyncio
    async def test_already_claimed_elsewhere_and_finished_meanwhile_reports_approved(self, env):
        await _prepare(env)
        env.world.claim_admin(CACHE)
        original = env.world.claim_rpc

        def claim_then_panel_finishes(*args):
            result = original(*args)
            env.world.delete(CACHE)
            return result

        with patch.object(handlers, "claim_receipt_approval", claim_then_panel_finishes):
            await env.click("ca:0:tu_700")
        env.remove.assert_awaited_once_with(CHAT, 50)
        assert env.send.await_args.args[1] == handlers.RECEIPT_ALREADY_APPROVED_MESSAGE
