import json
from app import app
from models import db, Employee


DAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def normalize_role(role):
    role_map = {
        "Food Runner": "Runner",
        "Food Expeditor": "Food Expeditor",
        "Expo": "Expo",
        "Parkside": "Server",
    }

    return role_map.get(role, role)


def default_availability():
    return {day: "Both" for day in DAYS}


def seed_employees_from_json(path="employees.json"):
    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)

    employees = data.get("employees", [])

    created = 0
    updated = 0

    for item in employees:
        employee_id = item.get("id")
        existing = Employee.query.get(employee_id)

        if existing:
            emp = existing
            updated += 1
        else:
            emp = Employee(id=employee_id)
            db.session.add(emp)
            created += 1

        emp.name = item.get("name", "Unnamed Employee")
        emp.role = normalize_role(item.get("role", "Server"))
        emp.employment_type = item.get("type", "Part Time")
        emp.weekly_hours_target = float(item.get("hours", 20) or 0)
        emp.hourly_rate = float(item.get("rate", 15) or 15)
        emp.pref = item.get("pref", "Any")

        emp.custom_times_json = json.dumps(item.get("custom_times", {}))
        emp.availability_json = json.dumps(item.get("availability", default_availability()))
        emp.unavailable_dates_json = json.dumps(item.get("unavailable_dates", []))
        emp.notes = item.get("notes", "")

    db.session.commit()

    print(f"Seed complete.")
    print(f"Created: {created}")
    print(f"Updated: {updated}")
    print(f"Total employees in DB: {Employee.query.count()}")


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        seed_employees_from_json()