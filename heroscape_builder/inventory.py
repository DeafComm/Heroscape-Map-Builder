"""Which sets the user owns, and how many of each piece that gives them."""

DEFAULT_SET = "rotv"
MAX_COPIES = 20


class Inventory:
    def __init__(self, copies=None):
        # set id -> number of copies owned; a set that isn't listed isn't owned.
        self.copies = dict(copies) if copies is not None else {DEFAULT_SET: 1}

    def owned_counts(self, pieces):
        counts = {}
        for p in pieces:
            counts[p.id] = sum(n * self.copies.get(set_id, 0) for set_id, n in p.counts.items())
        return counts

    def to_dict(self):
        return {"copies": dict(self.copies)}

    @classmethod
    def from_dict(cls, data, known_sets):
        """Build from saved settings, ignoring anything unexpected."""
        try:
            raw = data["copies"]
            copies = {}
            for set_id, n in raw.items():
                n = int(n)
                if set_id in known_sets and n > 0:
                    copies[set_id] = min(n, MAX_COPIES)
            return cls(copies)
        except (KeyError, TypeError, ValueError, AttributeError):
            return cls()
