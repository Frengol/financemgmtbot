import random
import string
import traceback
from postgrest.exceptions import APIError
from config import supabase, logger, mascarar_segredos
from telegram_service import enviar_acao_telegram, enviar_mensagem_telegram, editar_mensagem_telegram, baixar_arquivo_telegram, TELEGRAM_API_URL
from ai_service import extrair_tabela_recibo_gemini, transcrever_audio, processar_texto_com_llm
from core_logic import aplicar_map_reduce, gerar_mensagem_resumo, gerar_texto_edicao, formatar_relatorio_exclusao
from db_repository import aplicar_filtros_query, gravar_lote_no_banco, consultar_no_banco, inserir_no_banco
from utils import inferir_natureza
import telegram_service

async def iniciar_fluxo_exclusao(chat_id, filtros_exclusao):
    filtros_validos = {k: v for k, v in filtros_exclusao.items() if v}
    if not filtros_validos:
        await enviar_mensagem_telegram(chat_id, "⚠️ **Operação Recusada.**\nNão posso apagar a base inteira sem filtros! Diga-me o valor exato, a data, a categoria ou o método de pagamento da transação que deseja excluir.")
        return

    query_select = supabase.table("gastos").select("id, data, valor, natureza, categoria, descricao, metodo_pagamento, conta")
    resposta = aplicar_filtros_query(query_select, filtros_exclusao).execute()
    
    registros = resposta.data
    if not isinstance(registros, list) or not registros:
        await enviar_mensagem_telegram(chat_id, "🔎 Não encontrei nenhum gasto com essas características para apagar.")
        return
        
    ids_para_apagar = [r.get("id") for r in registros if isinstance(r, dict) and "id" in r]
    
    cache_id = "DEL_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
    supabase.table("cache_aprovacao").insert({"id": cache_id, "payload": {"ids": ids_para_apagar}}).execute()
    
    msg_alerta = formatar_relatorio_exclusao(registros)
    
    teclado = {
        "inline_keyboard": [
            [{"text": "✅ Sim, Apagar", "callback_data": f"confirmdel_{cache_id}"}],
            [{"text": "❌ Cancelar", "callback_data": f"cancelar_{cache_id}"}]
        ]
    }
    await enviar_mensagem_telegram(chat_id, msg_alerta, teclado)

async def processar_update_assincrono(update):
    chat_id = None
    update_id = update.get("update_id")
    if update_id:
        try:
            supabase.table("webhook_idempotencia").insert({"update_id": update_id}).execute()
        except APIError as e:
            if "23505" in getattr(e, "code", "") or "duplicate key" in getattr(e, "message", "").lower():
                logger.warning({"event": "idempotency_duplicate_intercepted", "update_id": update_id})
                return
            logger.error({"event": "idempotency_insert_failed", "error": str(e)})

    try:
        if "callback_query" in update:
            cb = update["callback_query"]
            chat_id = cb["message"]["chat"]["id"]
            msg_id = cb["message"]["message_id"]
            acao_bruta = cb["data"]
            
            if "_" in acao_bruta:
                acao, cache_id = acao_bruta.split("_", 1)
            else:
                acao = acao_bruta
                cache_id = None
            
            if telegram_service.http_client:
                await telegram_service.http_client.post(f"{TELEGRAM_API_URL}/answerCallbackQuery", json={"callback_query_id": cb["id"]})
            
            if not cache_id: return
                
            resp = supabase.table("cache_aprovacao").select("payload").eq("id", cache_id).execute()
            if not resp.data:
                await editar_mensagem_telegram(chat_id, msg_id, "❌ Rascunho expirado ou já processado.")
                return
                
            payload_cache = resp.data[0]["payload"]
            
            if acao == "aprovar":
                gravar_lote_no_banco(payload_cache)
                supabase.table("cache_aprovacao").delete().eq("id", cache_id).execute()
                await editar_mensagem_telegram(chat_id, msg_id, "✅ **Cupom Aprovado e Salvo!**")
                
            elif acao == "editar":
                texto_edit = gerar_texto_edicao(payload_cache)
                supabase.table("cache_aprovacao").delete().eq("id", cache_id).execute()
                await editar_mensagem_telegram(chat_id, msg_id, f"📝 **MODO EDIÇÃO**\nCopie, altere as categorias/valores e envie:\n\n`{texto_edit}`")
                
            elif acao == "confirmdel":
                ids = payload_cache.get("ids", [])
                supabase.table("gastos").delete().in_("id", ids).execute()
                supabase.table("cache_aprovacao").delete().eq("id", cache_id).execute()
                await editar_mensagem_telegram(chat_id, msg_id, f"🗑️ **Exclusão Efetuada!** ({len(ids)} registros apagados).")
                
            elif acao == "cancelar":
                supabase.table("cache_aprovacao").delete().eq("id", cache_id).execute()
                await editar_mensagem_telegram(chat_id, msg_id, "❌ **Operação Cancelada.** A base de dados não foi alterada.")
                
            return

        if "message" not in update: return
        message = update["message"]
        chat_id = message["chat"]["id"]
        texto_analise = ""

        logger.info({"event": "webhook_received", "type": "photo" if "photo" in message else "voice" if "voice" in message else "text"})

        if "photo" in message:
            await enviar_acao_telegram(chat_id, "upload_photo")
            await enviar_mensagem_telegram(chat_id, "👀 *Lendo cupom fiscal...*")
            foto_id = message["photo"][-1]["file_id"]
            img_bytes = await baixar_arquivo_telegram(foto_id)
            tabela_md = await extrair_tabela_recibo_gemini(img_bytes)
            texto_analise = f"Contexto: {message.get('caption', '')}\n\nNota Fiscal Extratada:\n{tabela_md}"
            logger.info({"event": "ocr_completed", "model": "gemini-2.5-flash"})
        elif "voice" in message:
            await enviar_acao_telegram(chat_id, "record_voice")
            await enviar_mensagem_telegram(chat_id, "⏳ *Ouvindo...*")
            audio_bytes = await baixar_arquivo_telegram(message["voice"]["file_id"])
            texto_analise = await transcrever_audio(audio_bytes)
            logger.info({"event": "stt_completed", "model": "whisper-large-v3"})
        elif "text" in message:
            await enviar_acao_telegram(chat_id, "typing")
            texto_analise = message["text"]
        else:
            return
            
        analise_ia = await processar_texto_com_llm(texto_analise)
        intencao = analise_ia.get("intencao")

        logger.info({"event": "llm_routed", "intent": intencao})

        if intencao == "registrar_lote_pendente":
            dados_lote = analise_ia.get("dados_lote", {})
            logger.info({"event": "items_extracted", "items_count": len(dados_lote.get("itens", []))})
            
            grupos, total_final, desc_global = aplicar_map_reduce(dados_lote)
            
            cache_id = "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
            supabase.table("cache_aprovacao").insert({"id": cache_id, "payload": dados_lote}).execute()
            
            logger.info({"event": "cache_created", "cache_id": cache_id})
            
            texto_resumo = gerar_mensagem_resumo(cache_id, dados_lote, grupos, total_final, desc_global)
            teclado = {
                "inline_keyboard": [
                    [{"text": "✅ Aprovar", "callback_data": f"aprovar_{cache_id}"}],
                    [{"text": "✏️ Editar", "callback_data": f"editar_{cache_id}"}, {"text": "❌ Cancelar", "callback_data": f"cancelar_{cache_id}"}]
                ]
            }
            await enviar_mensagem_telegram(chat_id, texto_resumo, teclado)

        elif intencao == "salvar_edicao_cupom":
            dados_lote = analise_ia.get("dados_lote", {})
            linhas, soma = gravar_lote_no_banco(dados_lote)
            await enviar_mensagem_telegram(chat_id, f"✅ **Edição Salva!**\n📊 **Total:** R$ {soma:,.2f}\n📝 Registos: {linhas}")

        elif intencao == "registrar":
            dados_reg = analise_ia.get("dados_registro", {})
            inserir_no_banco(dados_reg)
            val_total = float(dados_reg.get("valor_total") or 0.0)
            parcelas = int(dados_reg.get("parcelas") or 1)
            val_str = f"R$ {val_total:,.2f}" + (f" (em {parcelas}x)" if parcelas > 1 else "")
            
            nat_inf, cat_inf = inferir_natureza(dados_reg.get('categoria'))
            
            data_str = dados_reg.get('data')
            data_txt = f"🗓️ Data: {data_str}\n" if data_str else ""
            
            msg = (f"✅ **Salvo!**\n💰 {val_str} | 📊 {nat_inf}\n"
                   f"📂 Categoria: {cat_inf}\n"
                   f"{data_txt}"
                   f"🏦 {dados_reg.get('conta')} ({dados_reg.get('metodo_pagamento')})\n"
                   f"📝 {dados_reg.get('descricao')}")
            await enviar_mensagem_telegram(chat_id, msg)

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
                     msg += f"🗂️ Natureza: Todas"
            else:
                msg += f"🗂️ Busca Global"
                
            await enviar_mensagem_telegram(chat_id, msg)

        elif intencao == "excluir":
            filtros_exc = analise_ia.get("filtros_exclusao", {})
            await iniciar_fluxo_exclusao(chat_id, filtros_exc)

        else:
            raise Exception("Intenção não reconhecida.")

    except Exception as e:
        erro_tratado = mascarar_segredos(traceback.format_exc())
        logger.error({"event": "system_failure", "error": str(e), "traceback": erro_tratado})
        if 'chat_id' in locals() and chat_id:
            await enviar_mensagem_telegram(chat_id, f"❌ *Falha Sistémica*\n⚠️ `{str(e)}`")
