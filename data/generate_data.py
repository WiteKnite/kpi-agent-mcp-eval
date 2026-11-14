"""Generate a small synthetic sales-funnel dataset as a SQLite file.

The data is fake and deterministic (fixed seed). It tells a simple story:
automated first response starts in 2025-07, first-response time drops
sharply, and lead-to-contract conversion rises afterwards.
"""
import pathlib
import random
import sqlite3

SEED = 42
CHANNELS = ["web_form", "whatsapp", "phone", "email"]
REPS = ["Amira", "Bruno", "Chen", "Dana", "Eli"]
MONTHS = [f"2025-{m:02d}" for m in range(1, 13)]
LAUNCH_MONTH = "2025-07"
DB_PATH = pathlib.Path(__file__).with_name("sales.db")


def build(path: pathlib.Path = DB_PATH) -> pathlib.Path:
    rnd = random.Random(SEED)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.execute(
        """CREATE TABLE leads (
            id INTEGER PRIMARY KEY,
            month TEXT NOT NULL,
            channel TEXT NOT NULL,
            rep TEXT NOT NULL,
            first_response_minutes REAL NOT NULL,
            converted INTEGER NOT NULL
        )"""
    )
    lead_id = 1
    for i, month in enumerate(MONTHS):
        launched = month >= LAUNCH_MONTH
        n_leads = rnd.randint(170, 230)
        for _ in range(n_leads):
            channel = rnd.choices(CHANNELS, weights=[4, 3, 2, 3])[0]
            rep = rnd.choice(REPS)
            if launched:
                response = max(0.5, rnd.gauss(3, 1))
                p = 0.045 + 0.003 * (i - 6) + (0.01 if channel == "whatsapp" else 0)
            else:
                response = max(5.0, rnd.gauss(140, 40))
                p = 0.02 + 0.001 * i
            converted = 1 if rnd.random() < p else 0
            con.execute(
                "INSERT INTO leads VALUES (?,?,?,?,?,?)",
                (lead_id, month, channel, rep, round(response, 1), converted),
            )
            lead_id += 1
    con.commit()
    con.close()
    return path


if __name__ == "__main__":
    print(f"Wrote {build()}")
