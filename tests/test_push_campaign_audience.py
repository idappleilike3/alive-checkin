import unittest
from datetime import datetime, timedelta

from app import push_audience_code
from push_management import (
    CampaignValidationError,
    create_campaign,
    prepare_campaign,
    resolve_recipients,
)


NOW = datetime(2026, 8, 1, 10, 0, 0)


def member(uid, **overrides):
    profile = {
        "line_user_id": uid,
        "display_name": f"會員 {uid}",
        "plan": "trial",
        "membership_source": "public_trial",
        "payment_status": "trial",
        "trial_started_at": (NOW - timedelta(days=2)).isoformat(timespec="seconds"),
        "trial_end": (NOW + timedelta(days=12)).isoformat(timespec="seconds"),
    }
    profile.update(overrides)
    return profile


class PushAudienceCodeTests(unittest.TestCase):
    def test_classifies_active_trial_paid_beta_and_gift(self):
        cases = {
            "trial": member("U-trial"),
            "paid_199": member(
                "U-199",
                plan="paid_199",
                membership_source="paid",
                payment_status="active",
                paid_until=(NOW + timedelta(days=5)).isoformat(timespec="seconds"),
            ),
            "paid_399_year": member(
                "U-399Y",
                plan="paid_399_year",
                membership_source="paid",
                payment_status="active",
                paid_until=(NOW + timedelta(days=90)).isoformat(timespec="seconds"),
            ),
            "paid_799": member(
                "U-799",
                plan="paid_799",
                membership_source="paid",
                payment_status="active",
                paid_until=(NOW + timedelta(days=20)).isoformat(timespec="seconds"),
            ),
            "B399": member(
                "U-B399",
                plan="paid_399_year",
                membership_source="beta",
                payment_status="beta",
                beta_cohort="B399",
                beta_started_at=(NOW - timedelta(days=4)).isoformat(timespec="seconds"),
                beta_ends_at=(NOW + timedelta(days=17)).isoformat(timespec="seconds"),
            ),
            "B799": member(
                "U-B799",
                plan="paid_799_year",
                membership_source="beta",
                payment_status="beta",
                beta_cohort="B799",
                beta_started_at=(NOW - timedelta(days=4)).isoformat(timespec="seconds"),
                beta_ends_at=(NOW + timedelta(days=17)).isoformat(timespec="seconds"),
            ),
            "G799": member(
                "U-G799",
                plan="paid_799_year",
                membership_source="gift",
                payment_status="active",
                gift_code="G799",
                gift_started_at=(NOW - timedelta(days=1)).isoformat(timespec="seconds"),
                gift_ends_at=(NOW + timedelta(days=30)).isoformat(timespec="seconds"),
                paid_until=(NOW + timedelta(days=30)).isoformat(timespec="seconds"),
            ),
        }

        for expected, profile in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(push_audience_code(profile, now=NOW), expected)

    def test_expired_or_review_required_members_have_no_plan_audience(self):
        expired = member(
            "U-expired",
            plan="paid_799",
            membership_source="paid",
            payment_status="active",
            paid_until=(NOW - timedelta(seconds=1)).isoformat(timespec="seconds"),
        )
        review = member(
            "U-review",
            plan="paid_799_year",
            membership_source="paid",
            payment_status="active",
            paid_until="",
            expiry_review_required=True,
        )
        self.assertIsNone(push_audience_code(expired, now=NOW))
        self.assertIsNone(push_audience_code(review, now=NOW))


class RecipientResolutionTests(unittest.TestCase):
    def campaign(self, state, plan_audiences=None, explicit_member_ids=None):
        return create_campaign(
            state,
            {
                "name": "資格測試",
                "content_type": "text",
                "text": "測試訊息",
                "plan_audiences": list(plan_audiences or []),
                "explicit_member_ids": list(explicit_member_ids or []),
            },
            actor="super_admin",
            now=NOW,
        )

    def test_member_upgraded_after_campaign_creation_uses_current_plan(self):
        state = {"users": {"U123": member("U123", plan="paid_399", membership_source="paid", payment_status="active", paid_until=(NOW + timedelta(days=10)).isoformat(timespec="seconds"))}}
        campaign = self.campaign(state, plan_audiences=["paid_799"])
        state["users"]["U123"].update(
            plan="paid_799",
            paid_until=(NOW + timedelta(days=30)).isoformat(timespec="seconds"),
        )

        recipients = resolve_recipients(state, campaign, NOW, push_audience_code)

        self.assertEqual([row["line_user_id"] for row in recipients], ["U123"])
        self.assertEqual(recipients[0]["audience_code"], "paid_799")

    def test_explicit_and_plan_targets_are_deduplicated_by_full_uid(self):
        full_uid = "U1234567890abcdefghijklmnopqrstuvwxyz"
        state = {"users": {full_uid: member(full_uid, plan="paid_799", membership_source="paid", payment_status="active", paid_until=(NOW + timedelta(days=10)).isoformat(timespec="seconds"))}}
        campaign = self.campaign(
            state,
            plan_audiences=["paid_799"],
            explicit_member_ids=[full_uid],
        )

        recipients = resolve_recipients(state, campaign, NOW, push_audience_code)

        self.assertEqual(len(recipients), 1)
        self.assertEqual(recipients[0]["line_user_id"], full_uid)

    def test_explicit_target_can_include_inactive_member_but_not_blocked_or_missing_uid(self):
        state = {
            "users": {
                "U-inactive": member("U-inactive", plan="free", membership_source="expired", payment_status="expired"),
                "U-blocked": member("U-blocked", line_blocked=True),
                "": member(""),
            }
        }
        campaign = self.campaign(
            state,
            explicit_member_ids=["U-inactive", "U-blocked", ""],
        )

        recipients = resolve_recipients(state, campaign, NOW, push_audience_code)

        self.assertEqual([row["line_user_id"] for row in recipients], ["U-inactive"])
        self.assertEqual(recipients[0]["audience_code"], "explicit")

    def test_prepare_records_preview_counts_without_freezing_delivery_rows(self):
        state = {
            "users": {
                "U1": member("U1", plan="paid_799", membership_source="paid", payment_status="active", paid_until=(NOW + timedelta(days=10)).isoformat(timespec="seconds")),
                "U2": member("U2", plan="paid_799", membership_source="paid", payment_status="active", paid_until=(NOW + timedelta(days=10)).isoformat(timespec="seconds")),
            }
        }
        campaign = self.campaign(state, plan_audiences=["paid_799"])

        prepared = prepare_campaign(
            state,
            campaign["id"],
            actor="super_admin",
            now=NOW,
            audience_classifier=push_audience_code,
        )

        self.assertEqual(prepared["preview_recipient_count"], 2)
        self.assertEqual(prepared["preview_counts"], {"paid_799": 2})
        self.assertEqual(state["push_delivery_records"], [])
        prepared_event = state["push_campaign_events"][-1]
        self.assertEqual(prepared_event["preview_recipient_count"], 2)

    def test_prepare_rejects_unknown_audience_code(self):
        state = {"users": {}}
        campaign = self.campaign(state, plan_audiences=["not-a-plan"])

        with self.assertRaises(CampaignValidationError):
            prepare_campaign(
                state,
                campaign["id"],
                actor="super_admin",
                now=NOW,
                audience_classifier=push_audience_code,
            )


if __name__ == "__main__":
    unittest.main()
