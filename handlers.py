import re
from dataclasses import dataclass

from ai_service import extrair_tabela_recibo_gemini, processar_texto_com_llm, transcrever_audio
from config import logger, supabase
from core_logic import (
    aplicar_map_reduce,
    formatar_previa_exclusao,
    formatar_resumo_registros_salvos,
    gerar_lista_itens_cupom,
    gerar_mensagem_resumo,
    gerar_resumo_cupom,
    gerar_seletor_categoria,
    gerar_tela_item_cupom,
    gerar_texto_edicao,
)
from db_repository import (
    apagar_registros_por_ids,
    buscar_candidatos_exclusao,
    consultar_no_banco,
    find_matching_expense,
    gravar_lote_no_banco_com_registros,
    inserir_no_banco,
    load_records_by_source_update_id,
    normalizar_ids_exclusao,
)
from domain.duplicate_expense import (
    DUPLICATE_DECISIONS,
    DUPLICATE_EXPENSE_KIND,
    DUPLICATE_EXPIRED_MESSAGE,
    DUPLICATE_INVALID_MESSAGE,
    DUPLICATE_SKIPPED_MESSAGE,
    SAVE_ACTION,
    SKIP_ACTION,
    duplicate_keyboard,
    format_duplicate_confirmation,
    format_saved_expense,
    parse_duplicate_payload,
    prepare_duplicate_candidate,
    snapshot_matched_record,
)
from domain.finance import (
    RECEIPT_EDIT_PAGE_SIZE,
    RECEIPT_ITEM_CATEGORIES,
    REGISTER_AMOUNT_REQUIRED_MESSAGE,
    DeleteRefusal,
    DomainValidationError,
    normalize_delete_request,
    normalize_receipt_payload,
    normalize_register_payload,
    paginate_receipt_rows,
    receipt_item_rows,
    set_receipt_item_category,
    single_register_missing_amount,
)
from security import (
    LEGACY_PENDING_KINDS,
    MAX_TELEGRAM_AUDIO_BYTES,
    MAX_TELEGRAM_IMAGE_BYTES,
    allow_request,
    claim_receipt_approval,
    clear_duplicate_snapshot,
    decide_duplicate_expense,
    delete_pending_item,
    discard_receipt_pending,
    duplicate_item_expired,
    edit_receipt_pending,
    load_pending_item,
    load_pending_item_by_source_update_id,
    mark_pending_summary_sent,
    matches_pending_origin,
    matches_pending_origin_exact,
    pending_item_expired,
    pending_revision,
    receipt_pending_expired_strict,
    store_pending_item,
)
from telegram_service import (
    baixar_arquivo_telegram,
    editar_mensagem_telegram,
    enviar_acao_telegram,
    enviar_mensagem_telegram,
    remover_teclado_mensagem_telegram,
    responder_callback_telegram,
)
from telegram_correlation import with_error_reference
from utils import get_brasilia_time, inferir_natureza

CHAT_MEDIA_RATE_LIMIT = 12
CHAT_MEDIA_RATE_WINDOW_SECONDS = 60
CHAT_AI_RATE_LIMIT = 30
CHAT_AI_RATE_WINDOW_SECONDS = 60
DUPLICATE_ACTIONS = frozenset({SKIP_ACTION, SAVE_ACTION})
DELETE_IDENTIFY_HINT = "o valor exato, a data, a categoria, a conta ou o método de pagamento"
DELETE_REFUSAL_MESSAGES = {
    "pedido_incompleto": f"⚠️ Não consegui identificar qual registro apagar. Diga novamente {DELETE_IDENTIFY_HINT} do que deseja excluir.",
    "sem_criterio": f"⚠️ **Operação Recusada.**\nNão posso apagar a base inteira sem filtros! Diga-me {DELETE_IDENTIFY_HINT} da transação que deseja excluir.",
    "data_invalida": "⚠️ Não entendi a data informada. Diga o dia completo (dia, mês e ano) do registro que deseja excluir.",
    "mes_sem_ano": "⚠️ Você citou o mês sem o ano. Diga o mês e o ano do registro que deseja excluir.",
    "periodo_invalido": "⚠️ Não entendi o período informado. Diga o mês e o ano (ou só o ano) do registro que deseja excluir.",
    "periodo_conflitante": "⚠️ O dia e o mês/ano informados não combinam. Diga novamente a data do registro que deseja excluir.",
    "valor_invalido": "⚠️ Não entendi o valor informado. Diga o valor exato do registro que deseja excluir.",
    "categoria_invalida": "⚠️ Não reconheci a categoria informada. Diga uma categoria válida do registro que deseja excluir.",
    "natureza_invalida": "⚠️ Não reconheci a natureza informada. Use Essencial, Lazer, Receita ou Outros.",
    "tipo_invalido": "⚠️ Não entendi se é despesa ou receita. Diga qual dos dois deseja excluir.",
    "campo_invalido": "⚠️ Não entendi a conta ou o método de pagamento informado. Diga novamente.",
}
DELETE_REFUSAL_FALLBACK = DELETE_REFUSAL_MESSAGES["pedido_incompleto"]


def _normalize_dados_lote(dados_lote: object):
    return normalize_receipt_payload(dados_lote)


def _normalize_dados_registro(dados_registro: object):
    return normalize_register_payload(dados_registro)


def _chat_rate_key(chat_id, user_id=None):
    return f"chat:{chat_id}:user:{user_id or 'unknown'}"


async def _send_rate_limit_message(chat_id, source_update_id=None):
    await enviar_mensagem_telegram(
        chat_id,
        with_error_reference(
            "⚠️ Muitas solicitações em pouco tempo. Tente novamente em instantes.",
            update_id=source_update_id,
        ),
    )


async def _chat_rate_limited(
    scope: str,
    chat_id,
    user_id,
    *,
    limit: int,
    window_seconds: int,
    source_update_id=None,
):
    if allow_request(scope, _chat_rate_key(chat_id, user_id), limit=limit, window_seconds=window_seconds):
        return False
    await _send_rate_limit_message(chat_id, source_update_id)
    return True


async def _deliver_final_message(chat_id, progress_message_id, text, reply_markup=None, stage_callback=None):
    if stage_callback:
        await stage_callback("telegram_delivery", progress_message_id)
    if progress_message_id:
        return await editar_mensagem_telegram(chat_id, progress_message_id, text, reply_markup)
    return await enviar_mensagem_telegram(chat_id, text, reply_markup)


# Receipt category editor callbacks: "<action>:<number>[:<category>]:<cache id>".
# ":" never appears in legacy callbacks ("<action>_<id>") nor in pending ids, so these
# are parsed before the legacy split. The number is a revision (ca, ce), a page (cl) or
# an item position (ci, cs, cc); cv ignores it. Telegram caps callback_data at 64 bytes.
RECEIPT_CALLBACK_MAX_BYTES = 64
_RECEIPT_CALLBACK = re.compile(
    r"(ce|cl|ci|cs|cc|cv|ca):(0|[1-9][0-9]{0,8})(?::(0|[1-9][0-9]?))?:([A-Za-z0-9_-]{1,64})"
)
RECEIPT_UNAVAILABLE_MESSAGE = "❌ Este rascunho não está mais disponível para edição."
RECEIPT_GONE_MESSAGE = "❌ Rascunho expirado ou já processado."
RECEIPT_APPROVAL_STARTED_MESSAGE = (
    "⏳ A aprovação deste rascunho já foi iniciada e ainda não terminou; ele não pode mais ser alterado. "
    "Toque em Concluir aprovação para terminar."
)
RECEIPT_ALREADY_APPROVED_MESSAGE = "✅ Este cupom já foi aprovado."
RECEIPT_NOT_PENDING_MESSAGE = "ℹ️ Este rascunho não está mais pendente: ele já foi aprovado, cancelado ou expirou."
RECEIPT_STALE_MESSAGE = "⚠️ O rascunho mudou desde aquela tela. Confira o resumo atual e aprove novamente."


@dataclass(frozen=True)
class ReceiptCallback:
    action: str
    number: int
    category: int | None
    cache_id: str


def _receipt_callback(action, number, cache_id, category=None):
    middle = f"{number}" if category is None else f"{number}:{category}"
    return f"{action}:{middle}:{cache_id}"


def _parse_receipt_callback(data):
    if not isinstance(data, str) or len(data.encode("utf-8")) > RECEIPT_CALLBACK_MAX_BYTES:
        return None
    match = _RECEIPT_CALLBACK.fullmatch(data)
    if not match:
        return None
    action, number, category, cache_id = match.groups()
    if (action == "cc") != (category is not None):
        return None
    return ReceiptCallback(action, int(number), int(category) if category is not None else None, cache_id)


def _receipt_approval_keyboard(cache_id, revision=0):
    return {
        "inline_keyboard": [
            [{"text": "✅ Aprovar", "callback_data": _receipt_callback("ca", revision, cache_id)}],
            [{"text": "🏷️ Editar categorias", "callback_data": _receipt_callback("ce", revision, cache_id)}],
            [
                {"text": "✏️ Editar", "callback_data": f"editar_{cache_id}"},
                {"text": "❌ Cancelar", "callback_data": f"cancelar_{cache_id}"},
            ],
        ]
    }


def _receipt_finish_approval_keyboard(cache_id, revision=None):
    # The claim RPC answers "already_claimed" with the locked revision whatever revision the button carries.
    return {
        "inline_keyboard": [
            [{"text": "✅ Concluir aprovação", "callback_data": _receipt_callback("ca", revision or 0, cache_id)}],
        ]
    }


async def _explain_receipt_blocked(chat_id, msg_id, item, message):
    """Edit the message with why the draft cannot change; a started approval offers to finish it."""
    keyboard = None
    if message == RECEIPT_APPROVAL_STARTED_MESSAGE:
        revision = item.get("approval_claimed_revision")
        keyboard = _receipt_finish_approval_keyboard(item["id"], revision if revision is not None else pending_revision(item))
    await editar_mensagem_telegram(chat_id, msg_id, message, keyboard)


def _button_label(text, limit=40):
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _receipt_list_screen(cache_id, rows, page):
    page_rows, page, pages = paginate_receipt_rows(rows, page)
    keyboard = [
        [{"text": _button_label(f"#{row.position} {row.name}"), "callback_data": _receipt_callback("ci", row.position, cache_id)}]
        for row in page_rows
    ]
    navigation = []
    if page > 0:
        navigation.append({"text": "◀️ Anteriores", "callback_data": _receipt_callback("cl", page - 1, cache_id)})
    if page < pages - 1:
        navigation.append({"text": "Próximos ▶️", "callback_data": _receipt_callback("cl", page + 1, cache_id)})
    if navigation:
        keyboard.append(navigation)
    keyboard.append([{"text": "↩️ Voltar ao resumo", "callback_data": _receipt_callback("cv", 0, cache_id)}])
    return gerar_lista_itens_cupom(page_rows, page, pages, len(rows)), {"inline_keyboard": keyboard}


def _receipt_item_screen(cache_id, row):
    keyboard = [
        [{"text": "🏷️ Alterar categoria", "callback_data": _receipt_callback("cs", row.position, cache_id)}],
        [{"text": "⬅️ Voltar à lista", "callback_data": _receipt_callback("cl", (row.position - 1) // RECEIPT_EDIT_PAGE_SIZE, cache_id)}],
        [{"text": "↩️ Voltar ao resumo", "callback_data": _receipt_callback("cv", 0, cache_id)}],
    ]
    return gerar_tela_item_cupom(row), {"inline_keyboard": keyboard}


def _receipt_category_screen(cache_id, row):
    options = []
    for index, (category, nature) in enumerate(RECEIPT_ITEM_CATEGORIES):
        mark = "✓ " if category == row.category else ""
        options.append({
            "text": f"{mark}{category} · {nature}",
            "callback_data": _receipt_callback("cc", row.position, cache_id, index),
        })
    keyboard = [options[index:index + 2] for index in range(0, len(options), 2)]
    keyboard.append([{"text": "⬅️ Voltar ao item", "callback_data": _receipt_callback("ci", row.position, cache_id)}])
    return gerar_seletor_categoria(row), {"inline_keyboard": keyboard}


def _receipt_editable_rows(item):
    """Rows of a receipt that can still be edited, or the message explaining why not."""
    if item.get("approval_claimed_revision") is not None:
        return None, RECEIPT_APPROVAL_STARTED_MESSAGE
    # Approval needs the source update identity, so a draft without it is not offered for correction.
    if item.get("source_update_id") is None:
        return None, RECEIPT_UNAVAILABLE_MESSAGE
    if receipt_pending_expired_strict(item) or pending_revision(item) is None:
        return None, RECEIPT_UNAVAILABLE_MESSAGE
    rows = receipt_item_rows(item.get("payload"))
    if rows is None:
        return None, RECEIPT_UNAVAILABLE_MESSAGE
    return rows, None


async def _show_receipt_summary(chat_id, msg_id, cache_id, payload, revision, prefix=""):
    text = gerar_resumo_cupom(cache_id, payload)
    await editar_mensagem_telegram(chat_id, msg_id, f"{prefix}\n\n{text}" if prefix else text, _receipt_approval_keyboard(cache_id, revision))


async def _change_receipt_item_category(item, callback, rows, chat_id, msg_id, origin_user_id, source_update_id):
    cache_id = item["id"]
    try:
        updated = set_receipt_item_category(item.get("payload"), callback.number, callback.category)
    except DomainValidationError:
        text, keyboard = _receipt_list_screen(cache_id, rows, 0)
        await editar_mensagem_telegram(chat_id, msg_id, text, keyboard)
        return

    revision = pending_revision(item)
    payload = item.get("payload")
    if updated is not None:
        # The correction is persisted before anything is shown. A lost race (another
        # edit) is retried once on the reloaded version, since the choice is absolute.
        new_revision = edit_receipt_pending(cache_id, chat_id, origin_user_id, revision, updated)
        if new_revision is None:
            item = load_pending_item(cache_id)
            if not item:
                await editar_mensagem_telegram(chat_id, msg_id, RECEIPT_UNAVAILABLE_MESSAGE)
                return
            _, error = _receipt_editable_rows(item)
            if error:
                await _explain_receipt_blocked(chat_id, msg_id, item, error)
                return
            revision = pending_revision(item)
            payload = item.get("payload")
            updated = set_receipt_item_category(payload, callback.number, callback.category)
            if updated is not None:
                new_revision = edit_receipt_pending(cache_id, chat_id, origin_user_id, revision, updated)
                if new_revision is None:
                    await editar_mensagem_telegram(chat_id, msg_id, RECEIPT_UNAVAILABLE_MESSAGE)
                    return
        if updated is not None:
            payload, revision = updated, new_revision
            logger.info({
                "event": "receipt_item_category_changed",
                "cache_id": cache_id,
                "revision": revision,
                "update_id": source_update_id,
            })

    category, nature = RECEIPT_ITEM_CATEGORIES[callback.category]
    prefix = f"✅ Item #{callback.number}: {category} ({nature})."
    await _show_receipt_summary(chat_id, msg_id, cache_id, payload, revision, prefix)


async def _approve_receipt(item, revision, chat_id, msg_id, origin_user_id, source_update_id, stage_callback, progress_message_id):
    """Approve exactly the revision the owner saw; an outdated button only shows the current summary."""
    cache_id = item["id"]
    if item.get("source_update_id") is None or not isinstance(item.get("payload"), dict):
        await editar_mensagem_telegram(chat_id, msg_id, RECEIPT_UNAVAILABLE_MESSAGE)
        return

    status, locked_revision = claim_receipt_approval(cache_id, chat_id, origin_user_id, revision)
    if status == "stale":
        current = load_pending_item(cache_id)
        if not current or pending_revision(current) is None or receipt_item_rows(current.get("payload")) is None:
            await editar_mensagem_telegram(chat_id, msg_id, RECEIPT_UNAVAILABLE_MESSAGE)
            return
        await _show_receipt_summary(
            chat_id, msg_id, cache_id, current["payload"], pending_revision(current), RECEIPT_STALE_MESSAGE
        )
        logger.info({"event": "receipt_approval_stale", "cache_id": cache_id, "update_id": source_update_id})
        return
    if status == "expired":
        await editar_mensagem_telegram(chat_id, msg_id, with_error_reference(RECEIPT_GONE_MESSAGE, update_id=source_update_id))
        return
    if status not in ("claimed", "already_claimed"):
        await editar_mensagem_telegram(chat_id, msg_id, RECEIPT_UNAVAILABLE_MESSAGE)
        return

    item = load_pending_item(cache_id)
    if not item:
        # A locked approval is only removed when it finishes, so another delivery (or the panel) approved it.
        await remover_teclado_mensagem_telegram(chat_id, msg_id)
        await enviar_mensagem_telegram(chat_id, RECEIPT_ALREADY_APPROVED_MESSAGE)
        return
    payload_cache = item.get("payload")
    if (
        pending_revision(item) != locked_revision
        or item.get("approval_claimed_revision") != locked_revision
        or not isinstance(payload_cache, dict)
    ):
        raise RuntimeError("Claimed receipt revision is unavailable.")

    _, _, registros_salvos = gravar_lote_no_banco_com_registros(
        payload_cache,
        source_update_id=item["source_update_id"],
        origin_chat_id=chat_id,
    )
    if stage_callback:
        await stage_callback("approval_persisted", progress_message_id)
        await stage_callback("telegram_delivery", progress_message_id)
    await remover_teclado_mensagem_telegram(chat_id, msg_id)
    if stage_callback:
        await stage_callback("approval_keyboard_removed", progress_message_id)
        await stage_callback("telegram_delivery", progress_message_id)
    if not payload_cache.get("_approval_summary_sent"):
        await enviar_mensagem_telegram(chat_id, formatar_resumo_registros_salvos(registros_salvos))
        mark_pending_summary_sent(cache_id, payload_cache)
        if stage_callback:
            await stage_callback("approval_summary_sent", progress_message_id)
    delete_pending_item(cache_id)
    logger.info({"event": "receipt_approved", "cache_id": cache_id, "revision": locked_revision, "update_id": source_update_id})


async def _discard_receipt_or_explain(item, chat_id, msg_id, origin_user_id):
    status = discard_receipt_pending(item["id"], chat_id, origin_user_id)
    if status == "discarded":
        return True
    await _explain_receipt_blocked(
        chat_id,
        msg_id,
        item,
        RECEIPT_APPROVAL_STARTED_MESSAGE if status == "claimed" else RECEIPT_UNAVAILABLE_MESSAGE,
    )
    return False


async def _handle_receipt_edit_callback(callback, chat_id, msg_id, origin_user_id, source_update_id, stage_callback, progress_message_id):
    cache_id = callback.cache_id
    item = load_pending_item(cache_id)
    if not item:
        # The row is deleted on approval, cancel and expiry alike, so a missing draft cannot say which.
        message = RECEIPT_NOT_PENDING_MESSAGE if callback.action == "ca" else RECEIPT_UNAVAILABLE_MESSAGE
        await editar_mensagem_telegram(chat_id, msg_id, message)
        return
    # Anything not bound to exactly this chat and sender is ignored without touching the message.
    if item.get("kind") != "receipt_batch" or not matches_pending_origin_exact(item, chat_id, origin_user_id):
        return

    if callback.action == "ca":
        await _approve_receipt(item, callback.number, chat_id, msg_id, origin_user_id, source_update_id, stage_callback, progress_message_id)
        return

    rows, error = _receipt_editable_rows(item)
    if error:
        await _explain_receipt_blocked(chat_id, msg_id, item, error)
        return

    if callback.action == "cv":
        await _show_receipt_summary(chat_id, msg_id, cache_id, item["payload"], pending_revision(item))
        return
    if callback.action == "cc":
        await _change_receipt_item_category(item, callback, rows, chat_id, msg_id, origin_user_id, source_update_id)
        return

    row = rows[callback.number - 1] if 1 <= callback.number <= len(rows) else None
    if callback.action == "ci" and row:
        text, keyboard = _receipt_item_screen(cache_id, row)
    elif callback.action == "cs" and row:
        text, keyboard = _receipt_category_screen(cache_id, row)
    else:
        page = callback.number if callback.action == "cl" else 0
        text, keyboard = _receipt_list_screen(cache_id, rows, page)
    await editar_mensagem_telegram(chat_id, msg_id, text, keyboard)


async def _apply_duplicate_decision(item, decision, chat_id, *, deliver, remove_keyboard=None):
    """Carry a persisted decision to its end; every step is safe to repeat after a failure."""
    cache_id = item["id"]
    if decision == "save":
        effect_source_update_id = item.get("source_update_id")
        parsed = parse_duplicate_payload(item.get("payload"))
        if parsed is not None:
            inserir_no_banco(parsed.transaction, source_update_id=effect_source_update_id, origin_chat_id=chat_id)
        records = load_records_by_source_update_id(effect_source_update_id, chat_id)
        if not records:
            raise RuntimeError("Duplicate save effect is unavailable.")
        clear_duplicate_snapshot(cache_id)
        text = format_saved_expense(records[0])
    else:
        clear_duplicate_snapshot(cache_id)
        text = DUPLICATE_EXPIRED_MESSAGE if decision == "expired" else DUPLICATE_SKIPPED_MESSAGE
    if remove_keyboard:
        await remove_keyboard()
    await deliver(text)
    logger.info({"event": "duplicate_expense_decision_applied", "decision": decision, "update_id": item.get("source_update_id")})


async def _handle_duplicate_callback(acao, item, chat_id, msg_id, origin_user_id, source_update_id):
    # Anything that is not exactly a duplicate action on a duplicate item bound to this
    # chat and user is ignored: no decision, no write, no delete and no message edit.
    if not item or acao not in DUPLICATE_ACTIONS or item.get("kind") != DUPLICATE_EXPENSE_KIND:
        return
    if not matches_pending_origin_exact(item, chat_id, origin_user_id):
        return

    decision = item.get("duplicate_decision")
    if decision not in DUPLICATE_DECISIONS:
        # Past the deadline (or without a readable one) the database stores "expired"
        # whatever the click, so an unreadable payload must not mask the expiry.
        if not duplicate_item_expired(item) and parse_duplicate_payload(item.get("payload")) is None:
            await enviar_mensagem_telegram(
                chat_id,
                with_error_reference(DUPLICATE_INVALID_MESSAGE, update_id=source_update_id),
            )
            return
        decision = decide_duplicate_expense(
            item["id"], chat_id, origin_user_id, "save" if acao == SAVE_ACTION else "skip"
        )
        if decision is None:
            raise RuntimeError("Duplicate decision was not persisted.")

    await _apply_duplicate_decision(
        item,
        decision,
        chat_id,
        deliver=lambda text: enviar_mensagem_telegram(chat_id, text),
        remove_keyboard=lambda: remover_teclado_mensagem_telegram(chat_id, msg_id),
    )


async def _resume_duplicate_expense(pending, chat_id, origin_user_id, progress_message_id, source_update_id, stage_callback=None):
    if not matches_pending_origin_exact(pending, chat_id, origin_user_id):
        return False

    decision = pending.get("duplicate_decision")
    if decision not in DUPLICATE_DECISIONS:
        if duplicate_item_expired(pending):
            # The database turns any decision requested after the deadline into "expired".
            decision = decide_duplicate_expense(pending["id"], chat_id, origin_user_id, "skip")
            if decision is None:
                raise RuntimeError("Duplicate decision was not persisted.")
        else:
            parsed = parse_duplicate_payload(pending.get("payload"))
            if parsed is None:
                await _deliver_final_message(
                    chat_id,
                    progress_message_id,
                    with_error_reference(DUPLICATE_INVALID_MESSAGE, update_id=source_update_id),
                )
            else:
                await _deliver_final_message(
                    chat_id,
                    progress_message_id,
                    format_duplicate_confirmation(parsed),
                    duplicate_keyboard(pending["id"]),
                    stage_callback,
                )
            logger.info({"event": "persisted_duplicate_confirmation_resumed", "update_id": source_update_id})
            return True

    await _apply_duplicate_decision(
        pending,
        decision,
        chat_id,
        deliver=lambda text: _deliver_final_message(chat_id, progress_message_id, text, stage_callback=stage_callback),
    )
    return True


async def _resume_existing_effect(chat_id, source_update_id, progress_message_id, origin_user_id=None, stage_callback=None):
    if source_update_id is None:
        return False

    # A duplicate marker owns this update: its decision and snapshot cleanup must run
    # even when the financial effect already exists, so it is consulted before records.
    pending = load_pending_item_by_source_update_id(source_update_id)
    if pending and pending.get("kind") == DUPLICATE_EXPENSE_KIND:
        return await _resume_duplicate_expense(
            pending, chat_id, origin_user_id, progress_message_id, source_update_id, stage_callback
        )

    persisted_records = load_records_by_source_update_id(source_update_id, chat_id)
    if persisted_records:
        await _deliver_final_message(
            chat_id,
            progress_message_id,
            formatar_resumo_registros_salvos(persisted_records),
        )
        logger.info({"event": "persisted_financial_effect_resumed", "update_id": source_update_id})
        return True

    if not pending or pending.get("kind") != "receipt_batch" or pending_item_expired(pending):
        return False
    if not matches_pending_origin(pending, chat_id, origin_user_id):
        return False
    payload = pending.get("payload")
    if not isinstance(payload, dict):
        return False
    # The stored payload already carries every persisted category correction.
    await _deliver_final_message(
        chat_id,
        progress_message_id,
        gerar_resumo_cupom(pending["id"], payload),
        _receipt_approval_keyboard(pending["id"], pending_revision(pending) or 0),
    )
    logger.info({"event": "persisted_pending_effect_resumed", "update_id": source_update_id})
    return True


async def iniciar_fluxo_exclusao(chat_id, filtros_exclusao, origin_user_id=None):
    filters = normalize_delete_request(filtros_exclusao)
    if isinstance(filters, DeleteRefusal):
        await enviar_mensagem_telegram(chat_id, DELETE_REFUSAL_MESSAGES.get(filters.reason, DELETE_REFUSAL_FALLBACK))
        return

    registros = buscar_candidatos_exclusao(filters)
    if not registros:
        await enviar_mensagem_telegram(chat_id, "🔎 Não encontrei nenhum gasto com essas características para apagar.")
        return

    if filters.escopo == "um" and len(registros) > 1:
        await enviar_mensagem_telegram(
            chat_id,
            f"🔎 Encontrei {len(registros)} registros com essas características, e você pediu para apagar um só. "
            "Informe outro critério (data, valor, conta, categoria ou método de pagamento) para eu identificar qual. "
            "Nada foi apagado.",
        )
        return

    cache_record = store_pending_item(
        {"ids": [r["id"] for r in registros]},
        kind="delete_confirmation",
        origin_chat_id=chat_id,
        origin_user_id=origin_user_id,
    )

    teclado = {
        "inline_keyboard": [
            [{"text": "✅ Sim, Apagar", "callback_data": f"confirmdel_{cache_record['id']}"}],
            [{"text": "❌ Cancelar", "callback_data": f"cancelar_{cache_record['id']}"}],
        ]
    }
    await enviar_mensagem_telegram(chat_id, formatar_previa_exclusao(filters, registros), teclado)


async def processar_update_assincrono(
    update,
    *,
    source_update_id=None,
    progress_message_id=None,
    stage_callback=None,
    worker_attempt=None,
    ocr_round_callback=None,
    ocr_success_callback=None,
    processing_deadline_monotonic=None,
):
    chat_id = None
    if source_update_id is None and isinstance(update, dict):
        candidate_update_id = update.get("update_id")
        if isinstance(candidate_update_id, int) and not isinstance(candidate_update_id, bool):
            source_update_id = candidate_update_id

    try:
        if "callback_query" in update:
            cb = update["callback_query"]
            chat_id = cb["message"]["chat"]["id"]
            msg_id = cb["message"]["message_id"]
            acao_bruta = cb["data"]
            origin_user_id = cb.get("from", {}).get("id")

            if isinstance(acao_bruta, str) and ":" in acao_bruta:
                await responder_callback_telegram(cb["id"])
                receipt_callback = _parse_receipt_callback(acao_bruta)
                if receipt_callback is not None:
                    await _handle_receipt_edit_callback(
                        receipt_callback,
                        chat_id,
                        msg_id,
                        origin_user_id,
                        source_update_id,
                        stage_callback,
                        progress_message_id,
                    )
                return

            if "_" in acao_bruta:
                acao, cache_id = acao_bruta.split("_", 1)
            else:
                acao = acao_bruta
                cache_id = None

            await responder_callback_telegram(cb["id"])

            if not cache_id:
                return

            item = load_pending_item(cache_id)
            if acao in DUPLICATE_ACTIONS or (item and item.get("kind") not in LEGACY_PENDING_KINDS):
                await _handle_duplicate_callback(acao, item, chat_id, msg_id, origin_user_id, source_update_id)
                return
            if not item:
                await editar_mensagem_telegram(
                    chat_id,
                    msg_id,
                    with_error_reference("❌ Rascunho expirado ou já processado.", update_id=source_update_id),
                )
                return
            approval_started = item.get("kind") == "receipt_batch" and item.get("approval_claimed_revision") is not None
            # An approval that already started is finished by its own retry, even past the deadline.
            if pending_item_expired(item) and not approval_started:
                if item.get("kind") == "receipt_batch":
                    # The snapshot may be outdated: the atomic discard is bound to the origin
                    # and refuses to delete a draft whose approval was claimed after the read.
                    if not matches_pending_origin(item, chat_id, origin_user_id):
                        await editar_mensagem_telegram(
                            chat_id,
                            msg_id,
                            with_error_reference(
                                "❌ Operação não autorizada para esta conversa.",
                                update_id=source_update_id,
                            ),
                        )
                        return
                    if discard_receipt_pending(cache_id, chat_id, origin_user_id) == "claimed":
                        await _explain_receipt_blocked(chat_id, msg_id, item, RECEIPT_APPROVAL_STARTED_MESSAGE)
                        return
                else:
                    delete_pending_item(cache_id)
                await editar_mensagem_telegram(
                    chat_id,
                    msg_id,
                    with_error_reference("❌ Rascunho expirado ou já processado.", update_id=source_update_id),
                )
                return
            if not matches_pending_origin(item, chat_id, origin_user_id):
                await editar_mensagem_telegram(
                    chat_id,
                    msg_id,
                    with_error_reference(
                        "❌ Operação não autorizada para esta conversa.",
                        update_id=source_update_id,
                    ),
                )
                return

            payload_cache = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            pending_kind = item.get("kind")

            if acao == "aprovar":
                if pending_kind != "receipt_batch":
                    await editar_mensagem_telegram(
                        chat_id,
                        msg_id,
                        with_error_reference(
                            "❌ Tipo de pendência inválido para aprovação.",
                            update_id=source_update_id,
                        ),
                    )
                    return
                # Summaries sent before the category editor carry this button; it stands for revision 0.
                await _approve_receipt(
                    item, 0, chat_id, msg_id, origin_user_id, source_update_id, stage_callback, progress_message_id
                )

            elif acao == "editar":
                if pending_kind != "receipt_batch":
                    await editar_mensagem_telegram(
                        chat_id,
                        msg_id,
                        with_error_reference(
                            "❌ Tipo de pendência inválido para edição.",
                            update_id=source_update_id,
                        ),
                    )
                    return
                # The draft is discarded first, atomically, so the text edit can never
                # run alongside an approval that already started.
                if not await _discard_receipt_or_explain(item, chat_id, msg_id, origin_user_id):
                    return
                texto_edit = gerar_texto_edicao(payload_cache)
                await editar_mensagem_telegram(chat_id, msg_id, f"📝 **MODO EDIÇÃO**\nCopie, altere as categorias/valores e envie:\n\n`{texto_edit}`")

            elif acao == "confirmdel":
                if pending_kind != "delete_confirmation":
                    await editar_mensagem_telegram(
                        chat_id,
                        msg_id,
                        with_error_reference(
                            "❌ Tipo de pendência inválido para exclusão.",
                            update_id=source_update_id,
                        ),
                    )
                    return
                ids = normalizar_ids_exclusao(payload_cache.get("ids"))
                if ids is None:
                    await editar_mensagem_telegram(
                        chat_id,
                        msg_id,
                        with_error_reference(
                            "❌ Pendência de exclusão inválida. Nada foi apagado.",
                            update_id=source_update_id,
                        ),
                    )
                    return
                apagar_registros_por_ids(ids)
                await editar_mensagem_telegram(chat_id, msg_id, f"🗑️ **Exclusão Efetuada!** ({len(ids)} registros apagados).")
                delete_pending_item(cache_id)

            elif acao == "cancelar":
                if pending_kind == "receipt_batch":
                    if not await _discard_receipt_or_explain(item, chat_id, msg_id, origin_user_id):
                        return
                    await editar_mensagem_telegram(chat_id, msg_id, "❌ **Operação Cancelada.** A base de dados não foi alterada.")
                    return
                await editar_mensagem_telegram(chat_id, msg_id, "❌ **Operação Cancelada.** A base de dados não foi alterada.")
                delete_pending_item(cache_id)

            return

        if "message" not in update:
            return
        message = update["message"]
        chat_id = message["chat"]["id"]
        origin_user_id = message.get("from", {}).get("id")
        texto_analise = ""

        logger.info({"event": "webhook_received", "type": "photo" if "photo" in message else "voice" if "voice" in message else "text", "update_id": source_update_id})

        if await _resume_existing_effect(
            chat_id,
            source_update_id,
            progress_message_id,
            origin_user_id=origin_user_id,
            stage_callback=stage_callback,
        ):
            return

        if "photo" in message:
            if await _chat_rate_limited(
                "telegram-media",
                chat_id,
                origin_user_id,
                limit=CHAT_MEDIA_RATE_LIMIT,
                window_seconds=CHAT_MEDIA_RATE_WINDOW_SECONDS,
                source_update_id=source_update_id,
            ):
                return
            await enviar_acao_telegram(chat_id, "upload_photo")
            if progress_message_id:
                await editar_mensagem_telegram(chat_id, progress_message_id, "👀 *Lendo cupom fiscal...*")
            else:
                progress = await enviar_mensagem_telegram(chat_id, "👀 *Lendo cupom fiscal...*")
                progress_message_id = progress.get("message_id") or progress_message_id
            foto_id = message["photo"][-1]["file_id"]
            if stage_callback:
                await stage_callback("media_get_file", progress_message_id)
            img_bytes = await baixar_arquivo_telegram(
                foto_id,
                stage_callback=stage_callback,
                progress_message_id=progress_message_id,
            )
            if not img_bytes or len(img_bytes) > MAX_TELEGRAM_IMAGE_BYTES:
                await _deliver_final_message(
                    chat_id,
                    progress_message_id,
                    with_error_reference(
                        "⚠️ A imagem enviada é inválida ou excede o tamanho suportado.",
                        update_id=source_update_id,
                    ),
                    stage_callback=stage_callback,
                )
                return
            if stage_callback:
                await stage_callback("ocr", progress_message_id)
            ocr_round = await ocr_round_callback() if ocr_round_callback else None
            ocr_result = await extrair_tabela_recibo_gemini(
                img_bytes,
                source_update_id=source_update_id,
                worker_attempt=worker_attempt,
                ocr_round=ocr_round,
                processing_deadline_monotonic=processing_deadline_monotonic,
            )
            if ocr_success_callback:
                await ocr_success_callback()
            texto_analise = f"Contexto: {message.get('caption', '')}\n\nNota Fiscal Extratada:\n{ocr_result.text}"
            logger.info(
                {
                    "event": "ocr_completed",
                    "model": ocr_result.model,
                    "ocr_round": ocr_round,
                    "update_id": source_update_id,
                    "worker_attempt": worker_attempt,
                }
            )
        elif "voice" in message:
            if await _chat_rate_limited(
                "telegram-media",
                chat_id,
                origin_user_id,
                limit=CHAT_MEDIA_RATE_LIMIT,
                window_seconds=CHAT_MEDIA_RATE_WINDOW_SECONDS,
                source_update_id=source_update_id,
            ):
                return
            await enviar_acao_telegram(chat_id, "record_voice")
            if progress_message_id:
                await editar_mensagem_telegram(chat_id, progress_message_id, "⏳ *Ouvindo...*")
            else:
                progress = await enviar_mensagem_telegram(chat_id, "⏳ *Ouvindo...*")
                progress_message_id = progress.get("message_id") or progress_message_id
            if stage_callback:
                await stage_callback("media_get_file", progress_message_id)
            audio_bytes = await baixar_arquivo_telegram(
                message["voice"]["file_id"],
                stage_callback=stage_callback,
                progress_message_id=progress_message_id,
            )
            if not audio_bytes or len(audio_bytes) > MAX_TELEGRAM_AUDIO_BYTES:
                await _deliver_final_message(
                    chat_id,
                    progress_message_id,
                    with_error_reference(
                        "⚠️ O áudio enviado é inválido ou excede o tamanho suportado.",
                        update_id=source_update_id,
                    ),
                    stage_callback=stage_callback,
                )
                return
            if stage_callback:
                await stage_callback("stt", progress_message_id)
            texto_analise = await transcrever_audio(
                audio_bytes,
                source_update_id=source_update_id,
                worker_attempt=worker_attempt,
            )
            logger.info(
                {
                    "event": "stt_completed",
                    "model": "whisper-large-v3",
                    "update_id": source_update_id,
                    "worker_attempt": worker_attempt,
                }
            )
        elif "text" in message:
            if await _chat_rate_limited(
                "telegram-ai",
                chat_id,
                origin_user_id,
                limit=CHAT_AI_RATE_LIMIT,
                window_seconds=CHAT_AI_RATE_WINDOW_SECONDS,
                source_update_id=source_update_id,
            ):
                return
            await enviar_acao_telegram(chat_id, "typing")
            texto_analise = message["text"]
        else:
            return

        if "photo" in message or "voice" in message:
            if await _chat_rate_limited(
                "telegram-ai",
                chat_id,
                origin_user_id,
                limit=CHAT_AI_RATE_LIMIT,
                window_seconds=CHAT_AI_RATE_WINDOW_SECONDS,
                source_update_id=source_update_id,
            ):
                return
        if stage_callback:
            await stage_callback("llm", progress_message_id)
        analise_ia = await processar_texto_com_llm(
            texto_analise,
            source_update_id=source_update_id,
            worker_attempt=worker_attempt,
        )
        intencao = analise_ia.get("intencao")

        logger.info(
            {
                "event": "llm_routed",
                "intent": intencao,
                "update_id": source_update_id,
                "worker_attempt": worker_attempt,
            }
        )
        if stage_callback:
            await stage_callback("llm_routed", progress_message_id)

        if intencao == "registrar_lote_pendente":
            dados_lote = _normalize_dados_lote(analise_ia.get("dados_lote", {}))
            logger.info({"event": "items_extracted", "items_count": len(dados_lote.get("itens", []))})

            cache_record = store_pending_item(
                dados_lote,
                kind="receipt_batch",
                origin_chat_id=chat_id,
                origin_user_id=origin_user_id,
                source_update_id=source_update_id,
            )
            persisted_payload = cache_record.get("payload")
            if isinstance(persisted_payload, dict):
                dados_lote = _normalize_dados_lote(persisted_payload)

            logger.info({"event": "cache_created", "cache_id": cache_record["id"]})

            grupos, total_final, desc_global = aplicar_map_reduce(dados_lote)
            texto_resumo = gerar_mensagem_resumo(cache_record["id"], dados_lote, grupos, total_final, desc_global)
            teclado = _receipt_approval_keyboard(cache_record["id"], pending_revision(cache_record) or 0)
            await _deliver_final_message(chat_id, progress_message_id, texto_resumo, teclado, stage_callback)

        elif intencao == "salvar_edicao_cupom":
            dados_lote = _normalize_dados_lote(analise_ia.get("dados_lote", {}))
            _, _, registros_salvos = gravar_lote_no_banco_com_registros(
                dados_lote,
                source_update_id=source_update_id,
                origin_chat_id=chat_id,
            )
            await _deliver_final_message(
                chat_id,
                progress_message_id,
                formatar_resumo_registros_salvos(registros_salvos),
                stage_callback=stage_callback,
            )

        elif intencao == "registrar":
            raw_dados_registro = analise_ia.get("dados_registro", {})
            # Photos and receipts keep their own flow; text and voice need a positive amount before any lookup or write.
            if "photo" not in message and single_register_missing_amount(raw_dados_registro):
                logger.info({"event": "register_rejected_invalid_amount", "update_id": source_update_id})
                await _deliver_final_message(
                    chat_id,
                    progress_message_id,
                    REGISTER_AMOUNT_REQUIRED_MESSAGE,
                    stage_callback=stage_callback,
                )
                return
            dados_reg = _normalize_dados_registro(raw_dados_registro)
            # The warning needs a stable effect identity and a sender to bind the answer to.
            # Only text and voice are eligible; photos keep the previous flow regardless of the LLM route.
            candidate = (
                prepare_duplicate_candidate(dados_reg, fallback_date=get_brasilia_time())
                if source_update_id is not None and origin_user_id is not None and "photo" not in message
                else None
            )
            if candidate is not None:
                matched = find_matching_expense(candidate)
                if matched is not None:
                    cache_record = store_pending_item(
                        {
                            "transaction": candidate.transaction,
                            "matched_record": snapshot_matched_record(matched),
                        },
                        kind=DUPLICATE_EXPENSE_KIND,
                        origin_chat_id=chat_id,
                        origin_user_id=origin_user_id,
                        source_update_id=source_update_id,
                    )
                    parsed = parse_duplicate_payload(cache_record.get("payload"))
                    if parsed is None:
                        raise RuntimeError("Duplicate confirmation payload is unavailable.")
                    logger.info({"event": "duplicate_expense_detected", "update_id": source_update_id})
                    await _deliver_final_message(
                        chat_id,
                        progress_message_id,
                        format_duplicate_confirmation(parsed),
                        duplicate_keyboard(cache_record["id"]),
                        stage_callback,
                    )
                    return
            inserir_no_banco(dados_reg, source_update_id=source_update_id, origin_chat_id=chat_id)
            val_total = float(dados_reg.get("valor_total") or 0.0)
            parcelas = int(dados_reg.get("parcelas") or 1)
            val_str = f"R$ {val_total:,.2f}" + (f" (em {parcelas}x)" if parcelas > 1 else "")

            nat_inf, cat_inf = inferir_natureza(dados_reg.get("categoria"))

            data_str = dados_reg.get("data")
            data_txt = f"🗓️ Data: {data_str}\n" if data_str else ""

            msg = (
                f"✅ **Salvo!**\n💰 {val_str} | 📊 {nat_inf}\n"
                f"📂 Categoria: {cat_inf}\n"
                f"{data_txt}"
                f"🏦 {dados_reg.get('conta')} ({dados_reg.get('metodo_pagamento')})\n"
                f"📝 {dados_reg.get('descricao')}"
            )
            await _deliver_final_message(chat_id, progress_message_id, msg, stage_callback=stage_callback)

        elif intencao == "consultar":
            filtros = analise_ia.get("filtros_pesquisa", {})
            total, qtd = consultar_no_banco(filtros)

            f_mes = filtros.get("mes")
            f_ano = filtros.get("ano")

            if f_mes and f_ano:
                try:
                    str_data = f"{int(f_mes):02d}/{int(f_ano)}"
                except ValueError:
                    str_data = f"{f_mes}/{f_ano}"
            elif f_ano:
                str_data = str(f_ano)
            else:
                str_data = "Nenhum"

            f_cat = filtros.get("categoria")
            f_nat = filtros.get("natureza")
            f_tipo = filtros.get("tipo_transacao")

            if f_tipo == "saida" and not f_nat:
                msg_total = f"📊 **Total de Gastos (Saídas):** R$ {total:,.2f}\n"
            elif f_tipo == "entrada" and not f_nat:
                msg_total = f"📊 **Total de Ganhos (Entradas):** R$ {total:,.2f}\n"
            else:
                msg_total = f"📊 **Total:** R$ {total:,.2f}\n"

            msg = msg_total + f"📝 Registros: {qtd}\n🎛️ Filtros: {str_data}\n"

            if f_cat and not (f_cat and "," in f_cat):
                nat_inferred, cat_clean = inferir_natureza(f_cat)
                msg += f"🗂️ Categoria: {cat_clean} ({nat_inferred})"
            elif f_nat:
                nat_title = f_nat.strip().title()
                if nat_title in ["Essencial", "Lazer", "Receita"]:
                    msg += f"🗂️ Natureza: {nat_title}"
                else:
                    msg += "🗂️ Natureza: Todas"
            else:
                msg += "🗂️ Busca Global"

            await _deliver_final_message(chat_id, progress_message_id, msg, stage_callback=stage_callback)

        elif intencao == "excluir":
            filtros_exc = analise_ia.get("filtros_exclusao", {})
            if origin_user_id is None:
                await iniciar_fluxo_exclusao(chat_id, filtros_exc)
            else:
                await iniciar_fluxo_exclusao(chat_id, filtros_exc, origin_user_id=origin_user_id)

        else:
            raise Exception("Intenção não reconhecida.")

    except Exception:
        logger.error({"event": "system_failure", "error_code": "processing_failed", "update_id": source_update_id})
        raise
