from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from models import init_db, Booking
from nlp_utils import detect_intent, extract_entities, looks_like_name_response
from datetime import datetime
import uuid

DB_SESSION = init_db()
app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)


def get_or_create_pending(session, db):
    pending = db.query(Booking).filter_by(session_id=session, confirmed=False).order_by(Booking.created_at.desc()).first()
    if not pending:
        pending = Booking(session_id=session)
        db.add(pending)
        db.commit()
        db.refresh(pending)
    return pending


def booking_to_dict(b):
    return {
        "id": b.id,
        "session_id": b.session_id,
        "guest_name": b.guest_name,
        "checkin": b.checkin.isoformat() if b.checkin else None,
        "checkout": b.checkout.isoformat() if b.checkout else None,
        "nights": b.nights,
        "guests": b.guests,
        "breakfast": b.breakfast,
        "payment_method": b.payment_method,
        "confirmed": bool(b.confirmed),
        "notes": b.notes
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/session", methods=["POST"])
def create_session():
    sid = str(uuid.uuid4())
    return jsonify({"session_id": sid})


@app.route("/api/message", methods=["POST"])
def handle_message():
    data = request.json or {}
    text = (data.get("message") or "").strip()
    session_id = data.get("session_id")
    if not session_id:
        return jsonify({"error": "session_id required"}), 400

    db_sess = DB_SESSION()
    booking = get_or_create_pending(session_id, db_sess)

    def compute_missing(b):
        missing = []
        if not b.guest_name:
            missing.append("name")
        if not (b.checkin and (b.checkout or b.nights)):
            missing.append("dates")
        if not b.guests:
            missing.append("number of guests")
        return missing

    # If booking is missing a name and the reply looks like a name, set it directly (avoid date parser stealing it)
    missing_now = compute_missing(booking)
    extracted = {}
    if "name" in missing_now and text and looks_like_name_response(text):
        booking.guest_name = text
        db_sess.add(booking)
        db_sess.commit()
        db_sess.refresh(booking)
        # treat as an update without running extract_entities further
    else:
        extracted = extract_entities(text)

    intent = detect_intent(text)

    # merge extracted into booking where present
    changed_fields = []
    if extracted.get("name"):
        booking.guest_name = extracted["name"]
        changed_fields.append("guest_name")
    if extracted.get("guests"):
        booking.guests = extracted["guests"]
        changed_fields.append("guests")
    if extracted.get("checkin"):
        booking.checkin = extracted["checkin"]
        changed_fields.append("checkin")
    if extracted.get("checkout"):
        booking.checkout = extracted["checkout"]
        changed_fields.append("checkout")
    if extracted.get("nights"):
        booking.nights = extracted["nights"]
        changed_fields.append("nights")
    if extracted.get("breakfast"):
        booking.breakfast = extracted["breakfast"]
        changed_fields.append("breakfast")
    if extracted.get("payment_method"):
        booking.payment_method = extracted["payment_method"]
        changed_fields.append("payment_method")

    db_sess.add(booking)
    db_sess.commit()
    db_sess.refresh(booking)

    # --- Handle confirmation/cancellation intents first ---
    if intent == "confirm":
        missing = compute_missing(booking)
        if missing:
            reply = f"I need a few more details before I can confirm: {', '.join(missing)}. Could you provide them?"
            return jsonify({"reply": reply, "booking": booking_to_dict(booking), "all_required_present": False})
        booking.confirmed = True
        booking.notes = (booking.notes or "") + f"\nConfirmed at {datetime.utcnow().isoformat()}"
        db_sess.add(booking)
        db_sess.commit()
        db_sess.refresh(booking)
        # explicit flag to tell client it's ready to render final summary
        return jsonify({"reply": f"Thanks {booking.guest_name or ''}! Your booking is confirmed.", "booking": booking_to_dict(booking), "all_required_present": True})

    if intent == "cancel":
        booking.notes = (booking.notes or "") + f"\nCancelled by user at {datetime.utcnow().isoformat()}"
        db_sess.add(booking)
        db_sess.commit()
        db_sess.refresh(booking)
        return jsonify({"reply": "Okay — I have canceled the current booking draft. If you'd like to start again, say 'I want to book'.", "booking": booking_to_dict(booking), "all_required_present": False})

    # --- Normal conversational flow ---
    reply = ""
    missing = compute_missing(booking)
    all_required_present = len(missing) == 0

    # Build a short update message if something changed
    if changed_fields:
        # user-friendly names
        pretty = []
        for f in changed_fields:
            pretty.append(f.replace("_", " "))
        reply += "Got it — I updated: " + ", ".join(pretty) + ". "

    if all_required_present:
        # When required fields are present, invite optional additions or a confirm.
        # If the user just edited optional fields, give a confirm prompt.
        if any(f in ("breakfast", "payment_method") for f in changed_fields):
            reply += "Would you like to confirm this booking now? Reply 'confirm' to finish, or change breakfast/payment if needed."
        else:
            reply += ("I have the full booking details. Would you like to add breakfast or a payment method before confirming? "
                      "Reply 'breakfast: Continental, American or English' or 'payment: card, cash, crypto etc', or reply 'confirm' to finish.")
        return jsonify({"reply": reply.strip(), "booking": booking_to_dict(booking), "all_required_present": True})
    else:
        # missing required fields — ask for the first one
        first = missing[0]
        if "name" in first:
            follow = "What's the name for the reservation?"
        elif "dates" in first:
            follow = "When would you like to check in and check out? (e.g., 'June 10 to June 13' or 'next Monday for 3 nights')"
        elif "number of guests" in first:
            follow = "How many guests will stay?"
        else:
            follow = "Could you provide that?"
        reply += "I still need " + ", ".join(missing) + ". " + follow
        return jsonify({"reply": reply.strip(), "booking": booking_to_dict(booking), "all_required_present": False})


@app.route("/api/booking/<int:bid>/confirm", methods=["POST"])
def confirm_booking(bid):
    db_sess = DB_SESSION()
    b = db_sess.query(Booking).filter_by(id=bid).first()
    if not b:
        return jsonify({"error": "booking not found"}), 404
    if not b.guest_name or not b.checkin or not b.guests:
        return jsonify({"error": "Booking missing required fields", "booking": booking_to_dict(b)}), 400
    b.confirmed = True
    db_sess.add(b)
    db_sess.commit()
    db_sess.refresh(b)
    return jsonify({"reply": "Booking confirmed. Thank you!", "booking": booking_to_dict(b), "all_required_present": True})


@app.route("/api/booking/<int:bid>", methods=["GET"])
def get_booking(bid):
    db_sess = DB_SESSION()
    b = db_sess.query(Booking).filter_by(id=bid).first()
    if not b:
        return jsonify({"error": "booking not found"}), 404
    return jsonify({"booking": booking_to_dict(b)})

@app.route("/admin")
def admin_page():
    db_sess = DB_SESSION()
    bookings = db_sess.query(Booking).order_by(Booking.created_at.desc()).all()
    return render_template("admin.html", bookings=bookings)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
