import unittest
from pathlib import Path


HTML = Path(__file__).resolve().parents[1] / "index.html"


class XiaoPinganFrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML.read_text(encoding="utf-8")

    def test_chat_has_free_text_form_and_log(self):
        self.assertIn('id="xiaoPinganChatLog"', self.html)
        self.assertIn('id="xiaoPinganQuestionInput"', self.html)
        self.assertIn('id="xiaoPinganChatForm"', self.html)
        self.assertIn('aria-live="polite"', self.html)

    def test_character_remains_separate_from_panel(self):
        self.assertIn('id="xiaoPinganCharacter"', self.html)
        self.assertIn('id="peaceHelperPanel"', self.html)
        self.assertIn('class="xiao-pingan-svg"', self.html)

    def test_character_has_qilin_diamond_guardian_mark(self):
        self.assertIn('class="xp-diamond"', self.html)
        self.assertIn('class="xp-ear xp-ear-left"', self.html)
        self.assertIn('class="xp-mane"', self.html)
        self.assertIn('aria-label="小麒麟小平安"', self.html)

    def test_qilin_horns_are_named_and_positioned_on_outer_top_sides(self):
        self.assertIn('class="xp-horn xp-horn-left"', self.html)
        self.assertIn('class="xp-horn xp-horn-right"', self.html)
        self.assertIn('d="M24 31 Q17 8 35 23 L38 32z"', self.html)
        self.assertIn('d="M58 31 Q74 8 69 32 L64 35z"', self.html)

    def test_open_panel_does_not_capture_page_or_hide_character(self):
        self.assertIn('.peace-helper-panel-wrap', self.html)
        self.assertIn('pointer-events:none', self.html)
        self.assertIn('.peace-helper-panel { pointer-events:auto;', self.html)
        self.assertIn('.peace-helper-launcher { pointer-events:auto;', self.html)
        self.assertIn('overscroll-behavior:contain', self.html)
        self.assertIn('const launcherRect = launcher.getBoundingClientRect()', self.html)

    def test_voice_is_unlocked_by_direct_user_action_and_reports_state(self):
        self.assertIn('function unlockPeaceHelperVoice()', self.html)
        self.assertIn('function pickNaturalTaiwanVoice(voices)', self.html)
        self.assertIn('/natural|neural|premium|enhanced|online/i', self.html)
        self.assertIn('utterance.rate = 1', self.html)
        self.assertIn('utterance.pitch = 1', self.html)
        self.assertIn('utterance.onstart', self.html)
        self.assertIn('utterance.onerror', self.html)
        self.assertIn('await unlockPeaceHelperVoice()', self.html)

    def test_answer_text_is_rendered_immediately_without_character_timer(self):
        start = self.html.index('async function typeXiaoPinganAnswer(message)')
        end = self.html.index('\n    async function askXiaoPingan(question)', start)
        implementation = self.html[start:end]
        self.assertIn('bubble.textContent = message;', implementation)
        self.assertNotIn('for (let index', implementation)
        self.assertNotIn('setTimeout', implementation)

    def test_answer_does_not_add_fake_thinking_bubble(self):
        start = self.html.index('async function askXiaoPingan(question)')
        end = self.html.index('\n    function setPeaceHelperMessage', start)
        implementation = self.html[start:end]
        self.assertNotIn('正在想', implementation)
        self.assertNotIn('"thinking"', implementation)

    def test_binding_celebration_controls_are_initialized_independently(self):
        bind_start = self.html.index('function bindPeaceHelper()')
        bind_end = self.html.index('\n    function todayLocalIsoDate()', bind_start)
        bind_implementation = self.html[bind_start:bind_end]
        self.assertNotIn('guardianBindingCelebrateSave', bind_implementation)
        self.assertIn('function bindGuardianBindingCelebration()', self.html)
        self.assertIn('bindGuardianBindingCelebration();', self.html)

    def test_binding_birthday_preserves_saved_value_or_defaults_to_today(self):
        self.assertIn('function todayLocalIsoDate()', self.html)
        self.assertIn('birthday.value = savedBirthday || todayLocalIsoDate();', self.html)
        self.assertIn('modal.dataset.hasSavedBirthday = savedBirthday ? "true" : "false";', self.html)

    def test_voice_copy_is_short_and_natural_without_reading_symbols(self):
        self.assertIn('function normalizePeaceHelperSpeech(message)', self.html)
        self.assertIn('function refreshPeaceHelperVoices()', self.html)
        self.assertIn('window.speechSynthesis.addEventListener("voiceschanged", refreshPeaceHelperVoices)', self.html)
        self.assertIn('utterance.text = normalizePeaceHelperSpeech(message)', self.html)
        self.assertIn('utterance.rate = 1', self.html)
        self.assertIn('utterance.pitch = 1', self.html)

    def test_manual_help_opens_member_support_form(self):
        self.assertIn('id="xiaoPinganSupportLink"', self.html)
        self.assertIn('function openMemberSupportFromXiaoPingan(event)', self.html)
        self.assertIn('supportPanel.hidden = false;', self.html)
        self.assertIn('supportToggle.setAttribute("aria-expanded", "true");', self.html)
        self.assertIn('supportSection.scrollIntoView', self.html)

    def test_all_fifteen_animations_are_registered(self):
        expected = [
            "smile", "blink", "wave", "heartbeat", "float",
            "clap", "hearts", "stars", "worried", "alert-red",
            "point-location", "phone", "confetti", "hug", "jump",
        ]
        for name in expected:
            self.assertIn(f'"{name}"', self.html)

    def test_reduced_motion_and_accessible_controls_exist(self):
        self.assertIn("prefers-reduced-motion: reduce", self.html)
        self.assertIn('aria-label="輸入想問小平安的問題"', self.html)
        self.assertIn('aria-label="傳送問題"', self.html)


if __name__ == "__main__":
    unittest.main()
