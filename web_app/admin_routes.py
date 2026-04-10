from quart import request

from admin_runtime.approvals import aprovar_cache_admin, listar_cache_admin, rejeitar_cache_admin
from admin_runtime.auth import obter_admin_atual
from admin_runtime.transactions import atualizar_gasto_admin, criar_gasto_admin, deletar_gasto_admin, listar_gastos_admin


def register_admin_routes(app):
    @app.route("/api/admin/me", methods=["GET", "OPTIONS"])
    async def admin_me():
        if request.method == "OPTIONS":
            return "", 204
        return obter_admin_atual()

    @app.route("/api/admin/gastos", methods=["GET", "POST", "OPTIONS"])
    async def admin_gastos():
        if request.method == "OPTIONS":
            return "", 204
        if request.method == "GET":
            return listar_gastos_admin()
        payload = await request.get_json(silent=True)
        return criar_gasto_admin(payload)

    @app.route("/api/admin/gastos/<gasto_id>", methods=["DELETE", "PATCH", "OPTIONS"])
    async def admin_manage_gasto(gasto_id):
        if request.method == "OPTIONS":
            return "", 204
        if request.method == "PATCH":
            payload = await request.get_json(silent=True)
            return atualizar_gasto_admin(gasto_id, payload)
        return deletar_gasto_admin(gasto_id)

    @app.route("/api/admin/cache-aprovacao", methods=["GET", "OPTIONS"])
    async def admin_list_cache():
        if request.method == "OPTIONS":
            return "", 204
        return listar_cache_admin()

    @app.route("/api/admin/cache-aprovacao/<cache_id>/approve", methods=["POST", "OPTIONS"])
    async def admin_approve_cache(cache_id):
        if request.method == "OPTIONS":
            return "", 204
        return aprovar_cache_admin(cache_id)

    @app.route("/api/admin/cache-aprovacao/<cache_id>/reject", methods=["POST", "OPTIONS"])
    async def admin_reject_cache(cache_id):
        if request.method == "OPTIONS":
            return "", 204
        return rejeitar_cache_admin(cache_id)
