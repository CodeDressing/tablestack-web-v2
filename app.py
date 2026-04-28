import os
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, redirect, url_for, request
from models import db, Employee, ShiftTemplate, Schedule


DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

ROLES = [
    "Server",
    "Bartender",
    "Barback",
    "Runner",
    "Backwaiter",
    "Expo",
    "Food Expeditor",
    "Host",
    "Manager",
    "Owner",
]

AVAILABILITY_OPTIONS = ["Both", "Morning", "Dinner", "Unavailable"]


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-this")

    database_url = os.environ.get("DATABASE_URL")

    if database_url:
        database_url = database_url.replace("postgres://", "postgresql://", 1)
        app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    else:
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///tablestack_web_v2.db"

    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    with app.app_context():
        db.create_all()
        seed_shift_templates()

    register_routes(app)
    return app


def seed_shift_templates():
    if ShiftTemplate.query.count() > 0:
        return

    db.session.add(
        ShiftTemplate(
            name="Morning Shift",
            start_time="10:00",
            end_time="18:00",
            hours=8,
        )
    )

    db.session.add(
        ShiftTemplate(
            name="Dinner Shift",
            start_time="16:00",
            end_time="00:00",
            hours=8,
        )
    )

    db.session.commit()


def load_json(text, fallback):
    try:
        return json.loads(text or "")
    except Exception:
        return fallback


def default_availability():
    return {day: "Both" for day in DAYS}


def get_employee_availability(emp):
    data = load_json(emp.availability_json, {})
    if not data:
        data = default_availability()

    for day in DAYS:
        data.setdefault(day, "Both")

    return data


def get_employee_custom_times(emp):
    return load_json(emp.custom_times_json, {})


def employee_available_for_shift(emp, day, shift_name):
    availability = get_employee_availability(emp)
    day_status = availability.get(day, "Both")

    if day_status == "Unavailable":
        return False

    if "Morning" in shift_name and day_status not in ["Morning", "Both"]:
        return False

    if "Dinner" in shift_name and day_status not in ["Dinner", "Both"]:
        return False

    return True


def get_shift_times_for_employee(emp, day, shift):
    custom_times = get_employee_custom_times(emp)

    if day in custom_times:
        custom = custom_times[day]
        return {
            "start": custom.get("start", shift.start_time),
            "end": custom.get("end", shift.end_time),
            "hours": shift.hours,
        }

    return {
        "start": shift.start_time,
        "end": shift.end_time,
        "hours": shift.hours,
    }


def role_aliases(role):
    aliases = {
        "Runner": ["Runner", "Food Runner"],
        "Food Expeditor": ["Food Expeditor", "Expo"],
        "Expo": ["Expo", "Food Expeditor"],
        "Backwaiter": ["Backwaiter", "Busser"],
        "Barback": ["Barback"],
        "Server": ["Server"],
        "Bartender": ["Bartender"],
        "Host": ["Host"],
        "Manager": ["Manager", "Owner"],
        "Owner": ["Owner", "Manager"],
    }

    return aliases.get(role, [role])


def generate_smart_schedule(week_start):
    employees = Employee.query.order_by(Employee.name.asc()).all()
    shifts = ShiftTemplate.query.order_by(ShiftTemplate.id.asc()).all()

    role_needs = {
        "Morning Shift": {
            "Server": 2,
            "Bartender": 1,
            "Host": 1,
            "Runner": 1,
            "Backwaiter": 1,
            "Food Expeditor": 1,
            "Barback": 1,
            "Manager": 1,
        },
        "Dinner Shift": {
            "Server": 4,
            "Bartender": 2,
            "Host": 1,
            "Runner": 2,
            "Backwaiter": 1,
            "Food Expeditor": 1,
            "Barback": 1,
            "Manager": 1,
        },
    }

    employee_hours = {emp.id: 0 for emp in employees}
    employee_shift_count = {emp.id: 0 for emp in employees}

    rows = []
    violations = []

    for day_index, day in enumerate(DAYS):
        current_date = week_start + timedelta(days=day_index)

        for shift in shifts:
            needs = role_needs.get(shift.name, {})

            for needed_role, needed_count in needs.items():
                allowed_roles = role_aliases(needed_role)

                candidates = []

                for emp in employees:
                    if emp.role not in allowed_roles:
                        continue

                    if not employee_available_for_shift(emp, day, shift.name):
                        continue

                    projected_hours = employee_hours[emp.id] + shift.hours

                    if emp.weekly_hours_target > 0 and projected_hours > emp.weekly_hours_target:
                        continue

                    candidates.append(emp)

                candidates.sort(
                    key=lambda emp: (
                        employee_hours[emp.id],
                        employee_shift_count[emp.id],
                        emp.weekly_hours_target,
                        emp.name.lower(),
                    )
                )

                selected = candidates[:needed_count]

                for emp in selected:
                    shift_time = get_shift_times_for_employee(emp, day, shift)

                    employee_hours[emp.id] += shift.hours
                    employee_shift_count[emp.id] += 1

                    rows.append(
                        {
                            "date": current_date.strftime("%Y-%m-%d"),
                            "day": day,
                            "shift": shift.name,
                            "role": needed_role,
                            "employee": emp.name,
                            "start": shift_time["start"],
                            "end": shift_time["end"],
                            "hours": shift_time["hours"],
                        }
                    )

                if len(selected) < needed_count:
                    missing = needed_count - len(selected)
                    violations.append(f"{day} {shift.name}: missing {missing} {needed_role}(s)")

                    for _ in range(missing):
                        rows.append(
                            {
                                "date": current_date.strftime("%Y-%m-%d"),
                                "day": day,
                                "shift": shift.name,
                                "role": needed_role,
                                "employee": "UNASSIGNED",
                                "start": shift.start_time,
                                "end": shift.end_time,
                                "hours": shift.hours,
                            }
                        )

    for emp in employees:
        hours = employee_hours.get(emp.id, 0)

        if emp.employment_type == "Full Time" and 0 < hours < 30:
            violations.append(f"{emp.name}: Full Time but only scheduled {hours} hours")

        if emp.employment_type == "Part Time" and hours > 30:
            violations.append(f"{emp.name}: Part Time scheduled over 30 hours")

        if hours > 40:
            violations.append(f"{emp.name}: scheduled over 40 hours")

    return {
        "week_start": week_start.strftime("%Y-%m-%d"),
        "week_end": (week_start + timedelta(days=6)).strftime("%Y-%m-%d"),
        "rows": rows,
        "employee_hours": employee_hours,
        "violations": violations,
        "engine": "Phase 4 Smart Scheduler",
    }


def register_routes(app):
    @app.route("/")
    def index():
        employee_count = Employee.query.count()
        schedule_count = Schedule.query.count()
        return render_template(
            "index.html",
            employee_count=employee_count,
            schedule_count=schedule_count,
        )

    @app.route("/employees")
    def employees():
        all_employees = Employee.query.order_by(Employee.name.asc()).all()
        return render_template("employees.html", employees=all_employees)

    @app.route("/employees/add", methods=["GET", "POST"])
    def add_employee():
        if request.method == "POST":
            availability = {
                day: request.form.get(f"availability_{day}", "Both")
                for day in DAYS
            }

            custom_times = {}
            for day in DAYS:
                start = request.form.get(f"custom_start_{day}", "").strip()
                end = request.form.get(f"custom_end_{day}", "").strip()

                if start and end:
                    custom_times[day] = {
                        "start": start,
                        "end": end,
                    }

            employee = Employee(
                name=request.form.get("name", "").strip(),
                role=request.form.get("role", "Server"),
                employment_type=request.form.get("employment_type", "Part Time"),
                weekly_hours_target=float(request.form.get("weekly_hours_target") or 0),
                hourly_rate=float(request.form.get("hourly_rate") or 15),
                availability_json=json.dumps(availability),
                custom_times_json=json.dumps(custom_times),
            )

            db.session.add(employee)
            db.session.commit()
            return redirect(url_for("employees"))

        return render_template(
            "employee_form.html",
            employee=None,
            mode="Add",
            days=DAYS,
            roles=ROLES,
            availability_options=AVAILABILITY_OPTIONS,
            availability=default_availability(),
            custom_times={},
        )

    @app.route("/employees/edit/<int:id>", methods=["GET", "POST"])
    def edit_employee(id):
        employee = Employee.query.get_or_404(id)

        if request.method == "POST":
            availability = {
                day: request.form.get(f"availability_{day}", "Both")
                for day in DAYS
            }

            custom_times = {}
            for day in DAYS:
                start = request.form.get(f"custom_start_{day}", "").strip()
                end = request.form.get(f"custom_end_{day}", "").strip()

                if start and end:
                    custom_times[day] = {
                        "start": start,
                        "end": end,
                    }

            employee.name = request.form.get("name", "").strip()
            employee.role = request.form.get("role", "Server")
            employee.employment_type = request.form.get("employment_type", "Part Time")
            employee.weekly_hours_target = float(request.form.get("weekly_hours_target") or 0)
            employee.hourly_rate = float(request.form.get("hourly_rate") or 15)
            employee.availability_json = json.dumps(availability)
            employee.custom_times_json = json.dumps(custom_times)

            db.session.commit()
            return redirect(url_for("employees"))

        return render_template(
            "employee_form.html",
            employee=employee,
            mode="Edit",
            days=DAYS,
            roles=ROLES,
            availability_options=AVAILABILITY_OPTIONS,
            availability=get_employee_availability(employee),
            custom_times=get_employee_custom_times(employee),
        )

    @app.route("/employees/delete/<int:id>", methods=["POST"])
    def delete_employee(id):
        employee = Employee.query.get_or_404(id)
        db.session.delete(employee)
        db.session.commit()
        return redirect(url_for("employees"))

    @app.route("/schedules")
    def schedules():
        saved_schedules = Schedule.query.order_by(Schedule.created_at.desc()).all()
        return render_template("schedules.html", schedules=saved_schedules)

    @app.route("/schedules/generate", methods=["GET", "POST"])
    def generate_schedule():
        if request.method == "POST":
            week_start_raw = request.form.get("week_start")
            week_start = datetime.strptime(week_start_raw, "%Y-%m-%d")

            result = generate_smart_schedule(week_start)

            schedule = Schedule(
                name=f"Week of {result['week_start']}",
                week_start=result["week_start"],
                week_end=result["week_end"],
                schedule_json=json.dumps(result),
            )

            db.session.add(schedule)
            db.session.commit()

            return redirect(url_for("view_schedule", id=schedule.id))

        return render_template("generate_schedule.html")

    @app.route("/schedules/<int:id>")
    def view_schedule(id):
        schedule = Schedule.query.get_or_404(id)
        data = json.loads(schedule.schedule_json)
        return render_template("view_schedule.html", schedule=schedule, data=data)

    @app.route("/health")
    def health():
        return {"status": "ok", "app": "TableStack Web v2"}


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)