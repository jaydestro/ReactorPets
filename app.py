import uuid
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = uuid.uuid4().hex

# In-memory pet store
pets = {}


def generate_id():
    return uuid.uuid4().hex[:8]


@app.route("/")
def index():
    return render_template("index.html", pets=pets)


@app.route("/pets/new", methods=["GET", "POST"])
def create_pet():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        species = request.form.get("species", "").strip()
        breed = request.form.get("breed", "").strip()
        age = request.form.get("age", "").strip()

        if not name or not species:
            flash("Name and species are required.", "error")
            return render_template("form.html", pet=request.form, action="Create")

        pet_id = generate_id()
        pets[pet_id] = {
            "id": pet_id,
            "name": name,
            "species": species,
            "breed": breed,
            "age": age,
        }
        flash(f"Pet '{name}' created!", "success")
        return redirect(url_for("index"))

    return render_template("form.html", pet={}, action="Create")


@app.route("/pets/<pet_id>")
def read_pet(pet_id):
    pet = pets.get(pet_id)
    if not pet:
        flash("Pet not found.", "error")
        return redirect(url_for("index"))
    return render_template("detail.html", pet=pet)


@app.route("/pets/<pet_id>/edit", methods=["GET", "POST"])
def update_pet(pet_id):
    pet = pets.get(pet_id)
    if not pet:
        flash("Pet not found.", "error")
        return redirect(url_for("index"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        species = request.form.get("species", "").strip()
        breed = request.form.get("breed", "").strip()
        age = request.form.get("age", "").strip()

        if not name or not species:
            flash("Name and species are required.", "error")
            return render_template("form.html", pet=request.form, action="Update")

        pet.update({"name": name, "species": species, "breed": breed, "age": age})
        flash(f"Pet '{name}' updated!", "success")
        return redirect(url_for("read_pet", pet_id=pet_id))

    return render_template("form.html", pet=pet, action="Update")


@app.route("/pets/<pet_id>/delete", methods=["POST"])
def delete_pet(pet_id):
    pet = pets.pop(pet_id, None)
    if pet:
        flash(f"Pet '{pet['name']}' deleted.", "success")
    else:
        flash("Pet not found.", "error")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
