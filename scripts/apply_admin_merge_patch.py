from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"

FUNCTION_MARKER = "def admin_merge_member_accounts("
ROUTE_MARKER = '@app.post("/api/admin/members/merge")'
COMPLETION_MARKER = '"is_onboarding_completed": bool(access["home_ready"])'
BETA_REPAIR_MARKER = '# Repair stale beta identity before rendering admin member rows.'
STARTUP_REPAIR_MARKER = "def repair_authoritative_beta_onboarding_state("
STARTUP_CALL_MARKER = "repair_authoritative_beta_onboarding_state,\n    )\n    if Flask is None:"

FUNCTION_ANCHOR = "\ndef purge_account_migration_snapshots(state, now=None):\n"
ROUTE_ANCHOR = '    @app.post("/api/admin/test-accounts/<line_user_id>/reset")\n'
COMPLETION_ANCHOR = '"is_onboarding_completed": bool(profile.get("is_onboarding_completed"))'
BETA_REPAIR_ANCHOR = '    for user in (state.get("users") or {}).values():\n        if (\n            str(user.get("membership_source") or "") == "beta"\n'
STARTUP_REPAIR_ANCHOR = "\ndef should_show_guardian_prompt(profile, contact_count):\n"
STARTUP_CALL_ANCHOR = "def create_app(config=None):\n    if Flask is None:\n"

STARTUP_REPAIR_CODE = r'''
def repair_authoritative_beta_onboarding_state(state):
    """Persist beta plan and completed binding facts before any page is opened."""
    changed = 0
    for profile in (state.get("users") or {}).values():
        if not isinstance(profile, dict):
            continue
        profile_changed = False
        cohort = str(profile.get("beta_cohort") or "").strip().upper()
        if (
            str(profile.get("membership_source") or "") == "beta"
            and cohort in BETA_COHORT_PLAN
        ):
            expected_plan = BETA_COHORT_PLAN[cohort]
            if profile.get("plan") != expected_plan:
                profile["plan"] = expected_plan
                profile_changed = True
            if profile.get("payment_status") != "beta":
                profile["payment_status"] = "beta"
                profile_changed = True
        if profile_has_bound_line_guardian(profile):
            if profile.get("beta_reset_pending"):
                profile["beta_reset_pending"] = False
                profile_changed = True
            if ensure_onboarding_completed_flag(profile):
                profile_changed = True
            interaction = get_or_create_interaction_state(profile)
            if interaction.get("guardian_prompt_status") != "accepted":
                interaction["guardian_prompt_status"] = "accepted"
                profile_changed = True
        if profile_changed:
            changed += 1
    return changed

'''

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
    if COMPLETION_MARKER not in source:
        if COMPLETION_ANCHOR not in source:
            raise SystemExit("member completion anchor not found")
        source = source.replace(
            COMPLETION_ANCHOR,
            '"is_onboarding_completed": bool(access["home_ready"])',
            1,
        )
    if BETA_REPAIR_MARKER not in source:
        if BETA_REPAIR_ANCHOR not in source:
            raise SystemExit("beta membership repair anchor not found")
        source = source.replace(
            BETA_REPAIR_ANCHOR,
            '    for user in (state.get("users") or {}).values():\n'
            '        # Repair stale beta identity before rendering admin member rows.\n'
            '        cohort = str(user.get("beta_cohort") or "").strip().upper()\n'
            '        if (\n'
            '            str(user.get("membership_source") or "") == "beta"\n'
            '            and cohort in BETA_COHORT_PLAN\n'
            '        ):\n'
            '            expected_plan = BETA_COHORT_PLAN[cohort]\n'
            '            if user.get("plan") != expected_plan:\n'
            '                user["plan"] = expected_plan\n'
            '                dirty = True\n'
            '            if user.get("payment_status") != "beta":\n'
            '                user["payment_status"] = "beta"\n'
            '                dirty = True\n'
            '        if ensure_onboarding_completed_flag(user):\n'
            '            dirty = True\n'
            '        if (\n'
            '            str(user.get("membership_source") or "") == "beta"\n',
            1,
        )
    if STARTUP_REPAIR_MARKER not in source:
        if STARTUP_REPAIR_ANCHOR not in source:
            raise SystemExit("startup beta repair anchor not found")
        source = source.replace(
            STARTUP_REPAIR_ANCHOR,
            "\n" + STARTUP_REPAIR_CODE + STARTUP_REPAIR_ANCHOR,
            1,
        )
    if STARTUP_CALL_MARKER not in source:
        if STARTUP_CALL_ANCHOR not in source:
            raise SystemExit("create_app startup repair anchor not found")
        source = source.replace(
            STARTUP_CALL_ANCHOR,
            "def create_app(config=None):\n"
            "    startup_data_file = (\n"
            "        (config or {}).get(\"DATA_FILE\")\n"
            "        or resolve_data_file(os.environ.get(\"DATA_FILE\"))\n"
            "    )\n"
            "    mutate_state_atomically(\n"
            "        startup_data_file,\n"
            "        repair_authoritative_beta_onboarding_state,\n"
            "    )\n"
            "    if Flask is None:\n",
            1,
        )
    compile(source, str(APP_PATH), "exec")
    APP_PATH.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
