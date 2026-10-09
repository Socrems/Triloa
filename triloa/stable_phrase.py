"""Conservative cumulative transcript selection, with a bounded draft wait."""
import re
from time import monotonic

class StablePhrase:
    def __init__(self, min_interval=0.45, max_wait=1.4, hold=0.35):
        self.min_interval, self.max_wait, self.hold = min_interval, max_wait, hold
        self.latest = ''
        self.last_sent = ''
        self.first_at = None
        self.sent_at = None
        self.ages = []
        self.confirmed = 0

    def observe(self, text, now=None):
        now = monotonic() if now is None else now
        text = ' '.join(text.split())
        if not text:
            return
        if self.first_at is None:
            self.first_at = now
        common = 0
        for a, b in zip(self.latest, text):
            if a != b:
                break
            common += 1
        self.ages = self.ages[:common] + [now] * (len(text) - common)
        self.confirmed = common
        self.latest = text

    @staticmethod
    def phrase(text):
        # Prefer punctuation; otherwise keep a sufficiently long stable prefix.
        matches = list(re.finditer(r'[，、。！？；,.!?;](?:\s|$|(?=[^\x00-\x7f]))', text))
        if matches:
            return text[:matches[-1].end()].strip()
        if re.search(r'[\u3040-\u30ff\u4e00-\u9fff]', text):
            return text.strip() if len(text.strip()) >= 8 else ''
        return text.strip() if len(text.split()) >= 3 else ''

    def poll(self, now=None):
        now = monotonic() if now is None else now
        if self.first_at is None or not self.latest:
            return None
        if self.sent_at is not None and now - self.sent_at < self.min_interval:
            return None
        candidate = ''
        length = 0
        while length < self.confirmed and now - self.ages[length] >= self.hold:
            length += 1
        prefix = self.latest[:length]
        if (prefix and prefix[-1].isascii() and prefix[-1].isalnum() and
                (length == len(self.latest) or self.latest[length].isalnum())):
            boundary = max(prefix.rfind(' '), prefix.rfind(','), prefix.rfind('.'))
            prefix = prefix[:boundary + 1] if boundary >= 0 else ''
        candidate = self.phrase(prefix)
        waited = now - (self.sent_at if self.sent_at is not None else self.first_at)
        if (not candidate or candidate == self.last_sent or len(candidate) < len(self.last_sent)) and waited >= self.max_wait:
            candidate = self.latest
        if not candidate or candidate == self.last_sent:
            return None
        # Do not replace a longer displayed draft by a short prefix after a correction.
        if len(candidate) < len(self.last_sent) and waited < self.max_wait:
            return None
        self.last_sent, self.sent_at = candidate, now
        return candidate
