import os
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

import cosmos_db

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", uuid.uuid4().hex)

login_manager = LoginManager(app)
login_manager.login_view = "login"

# ---------------------------------------------------------------------------
# SSE subscribers (in-memory, transient by nature)
# ---------------------------------------------------------------------------
subscribers = {}  # app_id -> list[queue.Queue]

SPECIES_EMOJI = {"Dog": "🐕", "Cat": "🐈", "Fish": "🐠", "Bird": "🐦", "Rabbit": "🐇", "Reptile": "🐢"}
SPECIES_IMAGE = {
    "Dog": "dog.svg", "Cat": "cat.svg", "Fish": "fish.svg",
    "Bird": "bird.svg", "Rabbit": "rabbit.svg", "Reptile": "reptile.svg",
}


# ---------------------------------------------------------------------------
# User model (wraps Cosmos document for flask-login)
# ---------------------------------------------------------------------------
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

    def to_doc(self):
        """Serialize to Cosmos document with type discriminator (model-type-discriminator)."""
        return {
            "id": self.id,
            "type": "user",
            "username": self.username,
            "passwordHash": self.password_hash,
            "fullName": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "address": self.address,
        }

    @staticmethod
    def from_doc(doc):
        if doc is None:
            return None
        return User(
            id=doc["id"],
            username=doc["username"],
            password_hash=doc["passwordHash"],
            full_name=doc.get("fullName", ""),
            email=doc.get("email", ""),
            phone=doc.get("phone", ""),
            address=doc.get("address", ""),
        )


@login_manager.user_loader
def load_user(user_id):
    """Point read from Cosmos (query-point-reads): 1 RU."""
    return User.from_doc(cosmos_db.get_user(user_id))


def _id():
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Seed data — upsert is idempotent, safe to re-run
# ---------------------------------------------------------------------------
SEED_PETS = [
    {"id": "pet-001", "name": "Buddy",    "species": "Dog",     "breed": "Golden Retriever",
     "age": "3 years", "location": "Seattle, WA",      "listedDate": "2026-03-01",
     "description": "Friendly and energetic golden retriever who loves fetch, belly rubs, and long walks in the park."},
    {"id": "pet-002", "name": "Whiskers", "species": "Cat",     "breed": "Tabby",
     "age": "2 years", "location": "Portland, OR",     "listedDate": "2026-03-05",
     "description": "Calm indoor cat who enjoys sunny windowsills, gentle head scratches, and the occasional laser pointer chase."},
    {"id": "pet-003", "name": "Luna",     "species": "Dog",     "breed": "Husky",
     "age": "1 year",  "location": "Denver, CO",       "listedDate": "2026-03-08",
     "description": "Playful husky puppy with striking blue eyes and endless energy. Needs a yard and an active family."},
    {"id": "pet-004", "name": "Oliver",   "species": "Cat",     "breed": "Persian",
     "age": "4 years", "location": "San Francisco, CA","listedDate": "2026-03-12",
     "description": "Fluffy Persian who loves being brushed and curling up on laps. Perfect for a quiet home."},
    {"id": "pet-005", "name": "Rex",      "species": "Dog",     "breed": "German Shepherd",
     "age": "5 years", "location": "Austin, TX",       "listedDate": "2026-03-15",
     "description": "Loyal and well-trained family dog, great with kids. Knows sit, stay, and shake."},
    {"id": "pet-006", "name": "Nemo",     "species": "Fish",    "breed": "Clownfish",
     "age": "1 year",  "location": "Miami, FL",        "listedDate": "2026-03-18",
     "description": "Vibrant clownfish with bright orange and white bands. Easy to care for and mesmerizing to watch."},
    {"id": "pet-007", "name": "Coco",     "species": "Rabbit",  "breed": "Holland Lop",
     "age": "6 months","location": "Chicago, IL",      "listedDate": "2026-03-22",
     "description": "Adorable floppy-eared bunny who loves carrots and gentle cuddles. Litter-trained and sociable."},
    {"id": "pet-008", "name": "Kiwi",     "species": "Bird",    "breed": "Budgerigar",
     "age": "1 year",  "location": "New York, NY",     "listedDate": "2026-03-25",
     "description": "Cheerful green budgie who chirps along to music and enjoys perching on shoulders."},
    {"id": "pet-009", "name": "Milo",     "species": "Dog",     "breed": "Beagle",
     "age": "2 years", "location": "Nashville, TN",    "listedDate": "2026-03-28",
     "description": "Curious beagle with a nose for adventure. Loves sniffing trails and playing with other dogs."},
    {"id": "pet-010", "name": "Shelly",   "species": "Reptile", "breed": "Red-Eared Slider",
     "age": "3 years", "location": "Phoenix, AZ",      "listedDate": "2026-04-01",
     "description": "Easygoing turtle who enjoys basking under a heat lamp and swimming in her tank."},
    {"id": "pet-011", "name": "Bella",    "species": "Cat",     "breed": "Maine Coon",
     "age": "3 years", "location": "Boston, MA",       "listedDate": "2026-04-05",
     "description": "Majestic Maine Coon with a luxurious coat. Dog-like personality — follows you everywhere."},
    {"id": "pet-012", "name": "Sunny",    "species": "Bird",    "breed": "Cockatiel",
     "age": "2 years", "location": "San Diego, CA",    "listedDate": "2026-04-10",
     "description": "Friendly cockatiel who whistles tunes and loves head scratches. Hand-raised and very tame."},
]


def seed_pets():
    for pet in SEED_PETS:
        doc = {**pet, "type": "pet", "status": "available"}
        cosmos_db.upsert_pet(doc)


cosmos_db.init_db()
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
        doc = cosmos_db.find_user_by_username(username)
        user = User.from_doc(doc)

        if user is None:
            # Demo mode: auto-create account
            uid = _id()
            user = User(uid, username, generate_password_hash(password))
            cosmos_db.upsert_user(user.to_doc())
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

        if cosmos_db.find_user_by_username(username) is not None:
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
        cosmos_db.upsert_user(user.to_doc())
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
        cosmos_db.upsert_user(current_user.to_doc())
        flash("Profile updated!", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html")


# ---------------------------------------------------------------------------
# Pet browsing
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    all_pets = cosmos_db.list_pets()
    pets_dict = {p["id"]: p for p in all_pets
                 if p.get("status") in ("available", "pending")}
    # Build pet_id -> application mapping for the current user
    user_apps = {}
    if current_user.is_authenticated:
        for a in cosmos_db.list_applications_for_user(current_user.id):
            user_apps[a["petId"]] = a
    return render_template("index.html", pets=pets_dict, emoji=SPECIES_EMOJI,
                           images=SPECIES_IMAGE, user_apps=user_apps)


@app.route("/pets/<pet_id>")
def pet_detail(pet_id):
    pet = cosmos_db.get_pet(pet_id)
    if not pet:
        flash("Pet not found.", "error")
        return redirect(url_for("index"))
    user_app = None
    if current_user.is_authenticated:
        user_app = cosmos_db.find_application_for_pet(
            pet_id, current_user.id
        )
    return render_template("detail.html", pet=pet,
                           user_app=user_app, emoji=SPECIES_EMOJI,
                           images=SPECIES_IMAGE)


# ---------------------------------------------------------------------------
# Adoption applications
# ---------------------------------------------------------------------------
@app.route("/pets/<pet_id>/apply", methods=["GET", "POST"])
@login_required
def apply(pet_id):
    pet = cosmos_db.get_pet(pet_id)
    if not pet:
        flash("Pet not found.", "error")
        return redirect(url_for("index"))
    if pet["status"] != "available":
        flash("This pet is no longer available for adoption.", "error")
        return redirect(url_for("pet_detail", pet_id=pet_id))

    existing = cosmos_db.find_application_for_pet(pet_id, current_user.id)
    if existing:
        flash("You already applied to adopt this pet.", "error")
        return redirect(url_for("application_detail", app_id=existing["id"]))

    if request.method == "POST":
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        app_id = _id()
        # Timeline embedded in application doc (model-embed-related)
        cosmos_db.upsert_application({
            "id": app_id,
            "type": "application",
            "petId": pet_id,
            "petName": pet["name"],
            "userId": current_user.id,
            "fullName": request.form.get("full_name", "").strip(),
            "email": request.form.get("email", "").strip(),
            "phone": request.form.get("phone", "").strip(),
            "address": request.form.get("address", "").strip(),
            "reason": request.form.get("reason", "").strip(),
            "experience": request.form.get("experience", "").strip(),
            "status": "Submitted",
            "submittedAt": now,
            "timeline": [{"status": "Submitted", "time": now,
                          "note": "Application received."}],
        })
        pet["status"] = "pending"
        cosmos_db.upsert_pet(pet)
        flash(f"Application submitted for {pet['name']}!", "success")
        return redirect(url_for("application_detail", app_id=app_id))

    return render_template("apply.html", pet=pet)


@app.route("/my-applications")
@login_required
def my_applications():
    apps = cosmos_db.list_applications_for_user(current_user.id)
    apps_dict = {a["id"]: a for a in apps}
    return render_template("my_applications.html", applications=apps_dict)


@app.route("/applications/<app_id>")
@login_required
def application_detail(app_id):
    a = cosmos_db.get_application(app_id, current_user.id)
    if not a:
        flash("Application not found.", "error")
        return redirect(url_for("my_applications"))
    return render_template("application_detail.html", application=a)


# ---------------------------------------------------------------------------
# Realtime: SSE stream + demo status advance
# ---------------------------------------------------------------------------
@app.route("/applications/<app_id>/stream")
@login_required
def application_stream(app_id):
    a = cosmos_db.get_application(app_id, current_user.id)
    if not a:
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
    a = cosmos_db.get_application(app_id, current_user.id)
    if not a:
        return jsonify(error="Not found"), 404

    cur = a["status"]
    if cur not in STATUS_FLOW or cur == STATUS_FLOW[-1]:
        return jsonify(error="No further status changes."), 400

    new_status = STATUS_FLOW[STATUS_FLOW.index(cur) + 1]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    note = STATUS_NOTES.get(new_status, "")

    a["status"] = new_status
    a["timeline"].append(dict(status=new_status, time=now, note=note))
    cosmos_db.upsert_application(a)

    if new_status == "Approved":
        pet = cosmos_db.get_pet(a["petId"])
        if pet:
            pet["status"] = "adopted"
            cosmos_db.upsert_pet(pet)

    # Notify SSE listeners
    update = dict(status=new_status, time=now, note=note, timeline=a["timeline"])
    for q in subscribers.get(app_id, []):
        q.put(update)

    return jsonify(status=new_status, timeline=a["timeline"])


if __name__ == "__main__":
    app.run(debug=True, port=5000, threaded=True)
