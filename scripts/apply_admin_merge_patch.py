from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"

FUNCTION_MARKER = "def admin_merge_member_accounts("
ROUTE_MARKER = '@app.post("/api/admin/members/merge")'

FUNCTION_ANCHOR = "\ndef purge_account_migration_snapshots(state, now=None):\n"
ROUTE_ANCHOR = '    @app.post("/api/admin/test-accounts/<line_user_id>/reset")\n'

FUNCTION_CODE = r'''
def admin_merge_member_accounts(data_file, old_line_user_id, new_line_user_id, now=None):
    """Safely consolidate a stale LINE identity into the verified replacement."""
    source_id = str(old_line_user_id or "").strip()
    target_id = str(new_line_user_id or "").strip()
    if not source_id or not target_id or source_id == target_id:
        return {"ok": False, "error": "invalid_identity_pair"}, 400
    current = _account_migration_now(now)

    def mutate(state):
        users = state.setdefault("users", {})
        old_profile = users.get(source_id)
        new_profile = users.get(target_id)
        if not isinstance(old_profile, dict) or not isinstance(new_profile, dict):
            return {"ok": False, "error": "member_not_found"}, 404
        if source_id in (state.get("account_migration_aliases") or {}):
            return {"ok": False, "error": "source_already_merged"}, 409

        event_id = f"ame_{secrets.token_urlsafe(12)}"
        synthetic_ticket = {
            "old_line_user_id": source_id,
            "status": "admin_merge",
            "created_at": current.isoformat(timespec="seconds"),
        }
        snapshot_id, snapshot = _account_migration_snapshot(
            state, synthetic_ticket, source_id, target_id, event_id, current
        )
        state.setdefault("account_migration_snapshots", {})[snapshot_id] = snapshot
        merged_profile = merge_migration_profiles(old_profile, new_profile, now=current)
        reindex_account_references(state, source_id, target_id, event_id, now=current)
        _reindex_migration_record(merged_profile, source_id, target_id, event_id)
        users[target_id] = merged_profile
        users.pop(source_id, None)
        create_account_migration_alias(state, source_id, target_id, now=current)
        counts = _account_migration_safe_counts(state, merged_profile, target_id)
        state.setdefault("account_migration_audit", []).append({
            "event_id": event_id,
            "status": "success",
            "created_at": current.isoformat(timespec="seconds"),
            "failure_category": "",
            "source": "admin_merge",
            "counts": counts,
        })
        return {"ok": True, "status": "merged", "counts": counts}, 200

    try:
        return mutate_state_atomically(data_file, mutate)
    except Exception:
        return {"ok": False, "error": "merge_failed"}, 500

'''

ROUTE_CODE = r'''    @app.post("/api/admin/members/merge")
    def admin_member_merge_api():
        denied = _admin_guard(write=True, permission="member.manage")
        if denied:
            return denied
        if str(session.get("admin_role") or "viewer") != "super_admin":
            return jsonify({"ok": False, "error": "only_super_admin"}), 403
        payload = request.get_json(silent=True) or {}
        if payload.get("confirm") is not True:
            return jsonify({"ok": False, "error": "confirmation_required"}), 400
        data, code = admin_merge_member_accounts(
            app.config["DATA_FILE"],
            payload.get("old_line_user_id"),
            payload.get("new_line_user_id"),
        )
        return _admin_mutation_response("member.merge", data, code)

'''


def main():
    raw = APP_PATH.read_bytes()
    if b"\x00" in raw:
        raise SystemExit("app.py contains null bytes before patching")
    source = raw.decode("utf-8")
    if FUNCTION_MARKER not in source:
        if FUNCTION_ANCHOR not in source:
            raise SystemExit("member merge function anchor not found")
        source = source.replace(FUNCTION_ANCHOR, "\n" + FUNCTION_CODE + FUNCTION_ANCHOR, 1)
    if ROUTE_MARKER not in source:
        if ROUTE_ANCHOR not in source:
            raise SystemExit("member merge route anchor not found")
        source = source.replace(ROUTE_ANCHOR, ROUTE_CODE + ROUTE_ANCHOR, 1)
    compile(source, str(APP_PATH), "exec")
    APP_PATH.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
