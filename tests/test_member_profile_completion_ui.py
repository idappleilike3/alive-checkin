from pathlib import Path
import json

from app import load_state, update_member_location


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "app.py").read_text(encoding="utf-8")


def test_member_profile_shows_location_and_birthday_but_not_street_address():
    for field_id in (
        "memberProfileCity",
        "memberProfileDistrict",
        "memberProfileBirthday",
    ):
        assert f'id="{field_id}"' in HTML
    assert 'id="memberProfileAddress"' not in HTML
    assert "生日用於生日祝福與重要節日提醒" in HTML


def test_completed_member_hides_setup_and_share_prompt_section():
    assert 'status.is_onboarding_completed || status.home_ready || status.setup_completed' in HTML
    assert 'showOnboardingCompleteStep();' not in HTML
    assert '"首次設定已完成"' not in HTML
    assert '"再次一鍵邀請分享"' not in HTML


def test_profile_location_api_drops_address_and_persists_birthday():
    assert 'address = str((payload or {}).get("address") or "").strip()' not in APP
    assert 'birthday = str((payload or {}).get("birthday") or "").strip()' in APP
    assert 'profile.pop("address", None)' in APP
    assert 'profile["birthday"] = birthday' in APP
    assert '"address": str(profile.get("address") or "").strip()' not in APP
    assert '"birthday": str(profile.get("birthday") or "").strip()' in APP


def test_profile_location_write_removes_old_address_and_returns_birthday(tmp_path):
    data_file = tmp_path / "state.json"
    data_file.write_text(json.dumps({"users": {"U123": {"line_user_id": "U123", "address": "舊住址"}}}), encoding="utf-8")
    result, code = update_member_location(
        str(data_file),
        "U123",
        {
            "city": "台北市",
            "district": "中正區",
            "address": "忠孝西路一段 1 號",
            "birthday": "1988-06-09",
        },
    )
    assert code == 200
    assert "address" not in result
    assert result["birthday"] == "1988-06-09"
    saved = load_state(str(data_file))["users"]["U123"]
    assert saved["location"] == {"city": "台北市", "district": "中正區"}
    assert "address" not in saved
    assert saved["birthday"] == "1988-06-09"


def test_unbound_member_is_prompted_on_entry_and_checkin_is_blocked():
    assert "maybeShowGuardianPrompt();" in HTML
    assert "if (!hasLineBoundGuardian(currentGuardianContacts()))" in HTML
    assert "你還沒有完成守護綁定，請先邀請一位守護人完成綁定。" in HTML
