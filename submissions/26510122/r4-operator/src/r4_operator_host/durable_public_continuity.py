"""HOST persistence for original public-only continuity, without financial authority."""
from time import time

class DurablePublicContinuity:
    def __init__(self, state_db, original_class, *, ttl=300, limit=300, clock=time):
        self.state_db, self.original_class = state_db, original_class
        self.ttl, self.limit, self.clock = ttl, limit, clock

    def current(self, task, context):
        key = self.original_class.key(task, context)
        return None if key is None else self.state_db.get_public_facts(key, self.clock())

    def remember(self, task, context, facts):
        # Reuse the actual original validator/sanitizer, not a second business rule.
        key = self.original_class.key(task, context)
        if key is None:
            return False
        now = self.clock()
        validator = self.original_class(ttl=self.ttl, limit=self.limit, clock=lambda: now)
        if not validator.remember(task, context, facts):
            return False
        safe = validator.current(task, context)
        if safe is None:
            return False
        self.state_db.save_public_facts(key, safe, now, ttl=self.ttl, limit=self.limit)
        return True
