import uuid
import json
import queue
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, Response, jsonify, stream_with_context,
)
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user,
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = uuid.uuid4().hex

login_manager = LoginManager(app)
login_manager.login_view = "login"

# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------
users = {}
pets = {}
applications = {}
subscribers = {}  # app_id -> list[queue.Queue]  (SSE)

SPECIES_EMOJI = {"Dog": "🐕", "Cat": "🐈", "Fish": "🐠", "Bird": "🐦", "Rabbit": "🐇"}


class User(UserMixin):
    def __init__(self, id, username, password_hash,
                 full_name="", email="", phone="", address=""):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.full_name = full_name
        self.email = email
        self.phone = phone
        self.address = address


@login_manager.user_loader
def load_user(user_id):
    return users.get(user_id)


def _id():
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------
def seed_pets():
    sample = [
        ("Buddy", "Dog", "Golden Retriever", "3 years",
         "Friendly and energetic golden retriever who loves fetch and belly rubs."),
        ("Whiskers", "Cat", "Tabby", "2 years",
         "Calm indoor cat who enjoys sunny windowsills and gentle head scratches."),
        ("Luna", "Dog", "Husky", "1 year",
         "Playful husky puppy with striking blue eyes and endless energy."),
        ("Oliver", "Cat", "Persian", "4 years",
         "Fluffy Persian who loves being brushed and curling up on laps."),
        ("Rex", "Dog", "German Shepherd", "5 years",
         "Loyal and well-trained family dog, great with kids."),
        ("Nemo", "Fish", "Clownfish", "1 year",
         "Vibrant clownfish, easy to care for and fun to watch."),
    ]
    for name, species, breed, age, desc in sample:
        pid = _id()
        pets[pid] = dict(id=pid, name=name, species=species, breed=breed,
                         age=age, description=desc, status="available")


seed_pets()

# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if not username or not password:
            flash("Username and password are required.", "error")
            return render_template("login.html")

        # Find existing user
        user = next((u for u in users.values() if u.username == username), None)

        if user is None:
            # Demo mode: auto-create account
            uid = _id()
            user = User(uid, username, generate_password_hash(password))
            users[uid] = user
            flash(f"Welcome! Account '{username}' created automatically (demo mode).", "success")
        elif not check_password_hash(user.password_hash, password):
            flash("Invalid password.", "error")
            return render_template("login.html")

        login_user(user)
        return redirect(request.args.get("next") or url_for("index"))

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if not username or not password:
            flash("Username and password are required.", "error")
            return render_template("register.html")

        if any(u.username == username for u in users.values()):
            flash("Username already taken.", "error")
            return render_template("register.html")

        uid = _id()
        user = User(
            uid, username, generate_password_hash(password),
            full_name=request.form.get("full_name", "").strip(),
            email=request.form.get("email", "").strip(),
            phone=request.form.get("phone", "").strip(),
            address=request.form.get("address", "").strip(),
        )
        users[uid] = user
        login_user(user)
        flash("Registration successful!", "success")
        return redirect(url_for("index"))

    return render_template("register.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out.", "success")
    return redirect(url_for("index"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        current_user.full_name = request.form.get("full_name", "").strip()
        current_user.email = request.form.get("email", "").strip()
        current_user.phone = request.form.get("phone", "").strip()
        current_user.address = request.form.get("address", "").strip()
        flash("Profile updated!", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html")


# ---------------------------------------------------------------------------
# Pet browsing
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html", pets=pets, emoji=SPECIES_EMOJI)


@app.route("/pets/<pet_id>")
def pet_detail(pet_id):
    pet = pets.get(pet_id)
    if not pet:
        flash("Pet not found.", "error")
        return redirect(url_for("index"))
    already_applied = False
    if current_user.is_authenticated:
        already_applied = any(
            a["pet_id"] == pet_id and a["user_id"] == current_user.id
            for a in applications.values()
        )
    return render_template("detail.html", pet=pet,
                           already_applied=already_applied, emoji=SPECIES_EMOJI)


# ---------------------------------------------------------------------------
# Adoption applications
# ---------------------------------------------------------------------------
@app.route("/pets/<pet_id>/apply", methods=["GET", "POST"])
@login_required
def apply(pet_id):
    pet = pets.get(pet_id)
    if not pet:
        flash("Pet not found.", "error")
        return redirect(url_for("index"))
    if pet["status"] != "available":
        flash("This pet is no longer available for adoption.", "error")
        return redirect(url_for("pet_detail", pet_id=pet_id))

    existing = next(
        (a for a in applications.values()
         if a["pet_id"] == pet_id and a["user_id"] == current_user.id), None)
    if existing:
        flash("You already applied to adopt this pet.", "error")
        return redirect(url_for("application_detail", app_id=existing["id"]))

    if request.method == "POST":
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        app_id = _id()
        applications[app_id] = dict(
            id=app_id, pet_id=pet_id, pet_name=pet["name"],
            user_id=current_user.id,
            full_name=request.form.get("full_name", "").strip(),
            email=request.form.get("email", "").strip(),
            phone=request.form.get("phone", "").strip(),
            address=request.form.get("address", "").strip(),
            reason=request.form.get("reason", "").strip(),
            experience=request.form.get("experience", "").strip(),
            status="Submitted", submitted_at=now,
            timeline=[dict(status="Submitted", time=now,
                           note="Application received.")],
        )
        pet["status"] = "pending"
        flash(f"Application submitted for {pet['name']}!", "success")
        return redirect(url_for("application_detail", app_id=app_id))

    return render_template("apply.html", pet=pet)


@app.route("/my-applications")
@login_required
def my_applications():
    user_apps = {k: v for k, v in applications.items()
                 if v["user_id"] == current_user.id}
    return render_template("my_applications.html", applications=user_apps)


@app.route("/applications/<app_id>")
@login_required
def application_detail(app_id):
    a = applications.get(app_id)
    if not a or a["user_id"] != current_user.id:
        flash("Application not found.", "error")
        return redirect(url_for("my_applications"))
    return render_template("application_detail.html", application=a)


# ---------------------------------------------------------------------------
# Realtime: SSE stream + demo status advance
# ---------------------------------------------------------------------------
@app.route("/applications/<app_id>/stream")
@login_required
def application_stream(app_id):
    a = applications.get(app_id)
    if not a or a["user_id"] != current_user.id:
        return "Forbidden", 403

    def event_stream():
        q = queue.Queue()
        subscribers.setdefault(app_id, []).append(q)
        try:
            while True:
                data = q.get()
                yield f"data: {json.dumps(data)}\n\n"
        except GeneratorExit:
            subscribers[app_id].remove(q)
            if not subscribers[app_id]:
                del subscribers[app_id]

    return Response(stream_with_context(event_stream()),
                    content_type="text/event-stream")


STATUS_FLOW = ["Submitted", "Under Review", "Home Check Scheduled", "Approved"]
STATUS_NOTES = {
    "Under Review": "Your application is being reviewed by our team.",
    "Home Check Scheduled": "A home visit has been scheduled.",
    "Approved": "Congratulations! Your adoption has been approved! 🎉",
}


@app.route("/applications/<app_id>/advance", methods=["POST"])
@login_required
def advance_status(app_id):
    a = applications.get(app_id)
    if not a or a["user_id"] != current_user.id:
        return jsonify(error="Not found"), 404

    cur = a["status"]
    if cur not in STATUS_FLOW or cur == STATUS_FLOW[-1]:
        return jsonify(error="No further status changes."), 400

    new_status = STATUS_FLOW[STATUS_FLOW.index(cur) + 1]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    note = STATUS_NOTES.get(new_status, "")

    a["status"] = new_status
    a["timeline"].append(dict(status=new_status, time=now, note=note))

    if new_status == "Approved":
        pet = pets.get(a["pet_id"])
        if pet:
            pet["status"] = "adopted"

    # Notify SSE listeners
    update = dict(status=new_status, time=now, note=note, timeline=a["timeline"])
    for q in subscribers.get(app_id, []):
        q.put(update)

    return jsonify(status=new_status, timeline=a["timeline"])


if __name__ == "__main__":
    app.run(debug=True, port=5000, threaded=True)
