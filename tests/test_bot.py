
from datetime import datetime

from harness import Bot
from gymbot import model as m
from gymbot.app import COMMANDS


def log_all(b):
    """Tap Log until the card moves to Pick next."""
    for _ in range(10):
        if "pick next" in b.text:
            return
        b.tap("Log")


def test_full_real_session_saves_everything():
    b = Bot()
    before = len(b.sets())
    b.say("/go"); b.tap("UB1")
    for i, ex in enumerate(["Chest press", "Seated cable row", "Shoulder press", "Tricep pushdown", "Bicep curl"]):
        if i:
            b.tap(ex)
        assert ex in b.text
        log_all(b)
    b.tap("Finish")
    assert "UB1 logged" in b.text and "16 sets" in b.text     # first ex 4 sets, others 3
    new = [r for r in b.sets() if r["date"] == "2026-10-26"]
    assert len(new) == len(b.sets()) - before == 16
    s = [r for r in b.real["sessions"].rows if r["session_id"] == "2026-10-26-UB1"][0]
    assert s["status"] == "done" and s["start_time"] == "19:00"
    assert not b.test["sets"].rows                              # nothing in test tabs


def test_prefill_is_exactly_last_time_same_slot():
    b = Bot()
    b.say("/go"); b.tap("UB1")
    b.tap("Log"); b.tap("Log"); b.tap("Log")                   # W1 W2 S1
    s2 = [x for x in b.sets() if x["date"] == "2026-10-26"]
    assert [(r["slot"], r["load"], r["reps"]) for r in s2] == [("W1", 3, 5), ("W2", 6, 3), ("S1", 9, 4)]
    assert "▸ 7 x 8" in b.text                                 # S2 prefilled from last S2, not today's S1


def test_typed_input_and_tags():
    b = Bot()
    b.say("/go"); b.tap("UB1")
    b.say("4x6"); b.say("7 3 +"); b.say("10 5 dropped to 9")
    rows = [r for r in b.sets() if r["date"] == "2026-10-26"]
    assert [(r["load"], r["reps"], r["tag"]) for r in rows] == [(4, 6, ""), (7, 3, "+"), (10, 5, "dropped to 9")]
    b.say("11")                                                 # single number = reps at stepper load
    assert rows[-1]["slot"] == "S1"
    last = [r for r in b.sets() if r["date"] == "2026-10-26"][-1]
    assert (last["slot"], last["load"], last["reps"]) == ("S2", 7, 11)
    b.tap("Seated cable row")                                   # pick next after last slot
    b.say("hello")
    assert "Couldn't read that" in b.text
    assert len(b.tg.deleted) >= 5                               # typed messages cleaned up


def test_steppers_reps_only_and_lb_steps():
    b = Bot()
    b.say("/go"); b.tap("LB1")
    assert "Deficit calf raise" in b.text and "BW" in b.text
    b.tap("Log"); b.tap("Log")                                  # W1 W2 bodyweight
    assert "12 lb" in [x["text"] for x in b.buttons()]
    b.tap("+")                                                  # load + jumps past 12 -> 13
    labels = [x["text"] for x in b.buttons()]
    assert "13 lb" in labels
    btns = [x for x in b.buttons() if x["text"] == "−"]
    b.uid += 1
    b.app.handle({"update_id": 999, "callback_query": {"id": "1", "from": {"id": 42},
                  "data": btns[0]["callback_data"], "message": {"message_id": b.app.screen}}})
    assert "12 lb" in [x["text"] for x in b.buttons()]
    log_all(b)                                                  # S1 S2 S3
    calf = [r for r in b.sets() if r["date"] == "2026-10-26"]
    assert [r["slot"] for r in calf] == ["W1", "W2", "S1", "S2", "S3"]
    assert calf[0]["load"] == 0 and calf[0]["unit"] == "lb"
    b.tap("leg raise")
    assert "plates" not in " ".join(x["text"] for x in b.buttons())
    b.say("12")
    lr = [r for r in b.sets() if r["exercise"] == "Captain's chair leg raise" and r["date"] == "2026-10-26"][0]
    assert lr["load"] == "" and lr["reps"] == 12 and lr["unit"] == "reps"


def test_first_exercise_gets_two_warmups_whichever_it_is():
    b = Bot()
    b.say("/go"); b.tap("UB1")
    b.tap("Pick next"); b.tap("Bicep curl")                     # start with curl instead
    assert "W2" in b.text
    b.tap("Log")
    b.tap("Pick next"); b.tap("Chest press")
    assert "W2" not in b.text                                   # chest is no longer first


def test_last_from_any_session_and_variants():
    b = Bot()
    b.say("/go"); b.tap("UB1")
    b.tap("Pick next"); b.tap("Bicep curl")
    assert "Last: Wed 21 (UB2)" in b.text                       # latest curl was in UB2
    b.tap("Variant"); b.tap("Cable")
    assert "Bicep curl</b> · Cable" in b.text and "9 x 2" in b.text
    b.tap("Variant"); b.tap("New variant"); b.say("Single arm")
    assert "Single arm" in b.text and "Last: —" in b.text
    assert any(r["variant"] == "Single arm" for r in b.real["exercises"].rows)


def test_legacy_only_variant_shows_older_log():
    b = Bot()
    b.say("/go"); b.tap("UB1"); b.tap("Pick next"); b.tap("Bicep curl")
    b.tap("Variant"); b.tap("Substitute")
    assert "older log (UB2)" in b.text


def test_edit_delete_undo():
    b = Bot()
    b.say("/go"); b.tap("UB1")
    b.tap("Log"); b.tap("Log")
    b.tap("✏ W1"); b.tap("+")
    b.tap("Update W1")
    rows = [r for r in b.sets() if r["date"] == "2026-10-26"]
    assert rows[0]["load"] == 4 and len(rows) == 2
    b.tap("✏ W2"); b.tap("Delete")
    assert [r["slot"] for r in b.sets() if r["date"] == "2026-10-26"] == ["W1"]
    b.say("/undo")
    assert not [r for r in b.sets() if r["date"] == "2026-10-26"]
    assert "Removed W1" in b.text


def test_notes_off_main_path():
    b = Bot()
    b.say("/go"); b.tap("UB2")
    assert "Setup: pos: 2, 6" in b.text                         # imported setup note
    b.tap("Notes"); b.tap("Workout note"); b.say("left shoulder tight")
    b.tap("Setup note"); b.say("seat 3")
    assert b.real["notes"].rows[-1]["note"] == "left shoulder tight"
    pec = [r for r in b.real["exercises"].rows if r["exercise"] == "Pec deck fly"][0]
    assert pec["setup_note"] == "seat 3"
    b.tap("Back"); b.tap("Log")
    b.tap("Pick next"); b.tap("Finish"); b.tap("Session note"); b.say("light, knee weak")
    s = [r for r in b.real["sessions"].rows if r["session_id"] == "2026-10-26-UB2"][0]
    assert s["note"] == "light, knee weak"


def test_add_exercise_from_another_session():
    b = Bot()
    b.say("/go"); b.tap("UB2"); b.tap("Pick next"); b.tap("Add exercise"); b.tap("Leg press")
    assert "Leg press</b> · Knee hold" in b.text and "Last: Thu 22 (LB2)" in b.text
    b.tap("Log")
    b.tap("Pick next")
    assert "✓ Leg press · 1" in [x["text"] for x in b.buttons()]


def test_test_mode_is_isolated_and_check_save_passes():
    b = Bot()
    real_before = {k: len(t.rows) for k, t in b.real.items()}
    b.say("/test")
    assert "TEST" in b.text
    b.tap("LB2")
    assert "Last: Thu 22 (LB2)" in b.text                       # real history still shown
    log_all(b)
    b.tap("Back to card")
    b.tap("Notes"); b.tap("Setup note"); b.say("test only")    # must not touch real Exercises
    b.tap("Back"); b.tap("Pick next"); b.tap("Finish")
    assert {k: len(t.rows) for k, t in b.real.items()} == real_before
    assert all(r["setup_note"] != "test only" for r in b.real["exercises"].rows)
    assert len(b.test["sets"].rows) == 4 and b.test["sessions"].rows[0]["status"] == "done"
    b.tap("Check save")
    assert "Check passed: 4/4" in b.text
    b.tap("Clear test data")
    assert not b.test["sets"].rows and not b.test["sessions"].rows


def test_sheet_outage_queues_and_retries():
    b = Bot()
    b.say("/go"); b.tap("UB1")
    b.real["sets"].fail = 3
    b.tap("Log")
    assert "retrying" in b.tg.toasts[-1] and "waiting to save" in b.text
    b.tap("Log")                                                # still down, queue grows in order
    assert b.app.store.pending == 2
    b.app.tick(); b.app.tick()                                 # outage ends
    assert b.app.store.pending == 0
    assert [r["slot"] for r in b.sets() if r["date"] == "2026-10-26"] == ["W1", "W2"]


def test_resume_after_restart_and_autoclose():
    b = Bot()
    b.say("/go"); b.tap("UB1"); b.tap("Log"); b.tap("Log")
    b2 = Bot(tables=(b.real, b.test), start=datetime(2026, 10, 26, 19, 20))   # new GitHub run
    b2.say("/go")
    assert "pick next" in b2.text and "✓ Chest press · 2" in [x["text"] for x in b2.buttons()]
    b2.tap("Chest press")
    assert "▸ 9 x 4" in b2.text                                 # continues at S1
    b2.clock.advance(minutes=91)
    b2.app.tick()
    s = [r for r in b2.real["sessions"].rows if r["session_id"] == "2026-10-26-UB1"][0]
    assert s["status"] == "done" and s["end_time"] == "19:00"   # end = last set, not now
    assert "Auto-closed" in b2.text


def test_empty_session_removed_and_history_edit():
    b = Bot()
    b.say("/go"); b.tap("LB1"); b.tap("Pick next"); b.tap("Finish")
    assert not any(r["session_id"] == "2026-10-26-LB1" for r in b.real["sessions"].rows)
    b.tap("History"); b.tap("Thu 22")
    assert "Leg press (Knee hold): 7 x 6" in b.text
    b.tap("Edit"); b.tap("Leg extension"); b.tap("✏ S2"); b.tap("+", nth=1); b.tap("Update S2")
    ext = [r for r in b.sets() if r["session_id"] == "2026-10-22-LB2" and r["exercise"] == "Leg extension"]
    assert [r["reps"] for r in ext if r["slot"] == "S2"] == [13]
    b.tap("Pick next"); b.tap("Finish")
    s = [r for r in b.real["sessions"].rows if r["session_id"] == "2026-10-22-LB2"][0]
    assert s["status"] == "done" and s["note"] == "Light, knee weak"


def test_strangers_ignored():
    b = Bot()
    b.app.handle({"update_id": 1, "message": {"message_id": 5, "chat": {"id": 7}, "text": "/go"}})
    assert b.app.screen is None


def test_every_button_works_and_fits_64_bytes():
    """Walk the screens, tap every button once; nothing may crash."""
    b = Bot()
    seen = set()
    for start in (["/go", "UB1"], ["/test", "LB1"]):
        b.say(start[0]); b.tap(start[1])
        for _ in range(80):
            btns = [x for x in b.buttons() if x["callback_data"] not in seen and x["callback_data"] not in ("fin", "h", "clr")]
            if not btns:                                      # dead end: hop back to the card
                if b.app.active and b.app.active.cur:
                    b.say("/go")
                    btns = [x for x in b.buttons() if x["callback_data"] not in seen
                            and x["callback_data"] not in ("fin", "h", "clr")]
                if not btns:
                    break
            for x in b.buttons():
                assert len(x["callback_data"].encode()) <= 64
            seen.add(btns[0]["callback_data"])
            b.tap(btns[0]["text"])
            if b.app.prompt:
                b.say("note")
        if b.app.active:
            b.say("/go"); b.tap("Pick next"); b.tap("Finish")
    for need in ("log", "lp", "rm", "ed:W1", "x", "var", "v:0", "nt", "pn"):  # rest covered by tests above
        assert need in seen, need
    assert not b.logs


def test_parser():
    assert m.parse_set("7 9", False) == (7, 9, "")
    assert m.parse_set("7x9", False) == (7, 9, "")
    assert m.parse_set("7 x 9 +", False) == (7, 9, "+")
    assert m.parse_set("12", False) == (None, 12, "")
    assert m.parse_set("10+2", True) == (None, 10, "+2")
    assert m.parse_set("hi", False) is None


def test_commands_registered():
    assert [c for c, _ in COMMANDS] == ["go", "undo", "test", "cleartest"]
