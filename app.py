import os
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, redirect, url_for, flash, request
from models import db, Employee, ShiftTemplate, Schedule


DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


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

    db.session.add(ShiftTemplate(name="Morning Shift", start_time="10:00", end_time="18:00", hours=8))
    db.session.add(ShiftTemplate(name="Dinner Shift", start_time="16:00", end_time="00:00", hours=8))
    db.session.commit()


def generate_basic_schedule(week_start):
    employees = Employee.query.order_by(Employee.name.asc()).all()
    shifts = ShiftTemplate.query.all()

    role_needs = {
        "Morning Shift": {
            "Server": 2,
            "Bartender": 1,
            "Host": 1,
            "Runner": 1,
            "Backwaiter": 1,
            "Expo": 1,
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
            "Expo": 1,
            "Food Expeditor": 1,
            "Barback": 1,
            "Manager": 1,
        },
    }

    employee_hours = {emp.id: 0 for emp in employees}
    schedule_rows = []
    violations = []

    for day_index, day in enumerate(DAYS):
        current_date = week_start + timedelta(days=day_index)

        for shift in shifts:
            needs = role_needs.get(shift.name, {})

            for role, needed_count in needs.items():
                candidates = [
                    emp for emp in employees
                    if emp.role == role
                    and employee_hours[emp.id] + shift.hours <= emp.weekly_hours_target
                ]

                candidates.sort(key=lambda emp: employee_hours[emp.id])
                selected = candidates[:needed_count]

                for emp in selected:
                    employee_hours[emp.id] += shift.hours

                    schedule_rows.append({
                        "date": current_date.strftime("%Y-%m-%d"),
                        "day": day,
                        "shift": shift.name,
                        "role": role,
                        "employee": emp.name,
                        "start": shift.start_time,
                        "end": shift.end_time,
                        "hours": shift.hours,
                    })

                if len(selected) < needed_count:
                    missing = needed_count - len(selected)
                    violations.append(f"{day} {shift.name}: missing {missing} {role}(s)")

                    for _ in range(missing):
                        schedule_rows.append({
                            "date": current_date.strftime("%Y-%m-%d"),
                            "day": day,
                            "shift": shift.name,
                            "role": role,
                            "employee": "UNASSIGNED",
                            "start": shift.start_time,
                            "end": shift.end_time,
                            "hours": shift.hours,
                        })

    return {
        "week_start": week_start.strftime("%Y-%m-%d"),
        "week_end": (week_start + timedelta(days=6)).strftime("%Y-%m-%d"),
        "rows": schedule_rows,
        "employee_hours": employee_hours,
        "violations": violations,
    }


def register_routes(app):
    @app.route("/")
    def index():
        employee_count = Employee.query.count()
        schedule_count = Schedule.query.count()
        return render_template("index.html", employee_count=employee_count, schedule_count=schedule_count)

    @app.route("/employees")
    def employees():
        all_employees = Employee.query.order_by(Employee.name.asc()).all()
        return render_template("employees.html", employees=all_employees)

    @app.route("/employees/add", methods=["GET", "POST"])
    def add_employee():
        if request.method == "POST":
            employee = Employee(
                name=request.form.get("name", "").strip(),
                role=request.form.get("role", "Server"),
                employment_type=request.form.get("employment_type", "Part Time"),
                weekly_hours_target=float(request.form.get("weekly_hours_target") or 0),
                hourly_rate=float(request.form.get("hourly_rate") or 15),
            )

            db.session.add(employee)
            db.session.commit()
            return redirect(url_for("employees"))

        return render_template("employee_form.html", employee=None, mode="Add")

    @app.route("/employees/edit/<int:id>", methods=["GET", "POST"])
    def edit_employee(id):
        employee = Employee.query.get_or_404(id)

        if request.method == "POST":
            employee.name = request.form.get("name", "").strip()
            employee.role = request.form.get("role", "Server")
            employee.employment_type = request.form.get("employment_type", "Part Time")
            employee.weekly_hours_target = float(request.form.get("weekly_hours_target") or 0)
            employee.hourly_rate = float(request.form.get("hourly_rate") or 15)

            db.session.commit()
            return redirect(url_for("employees"))

        return render_template("employee_form.html", employee=employee, mode="Edit")

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

            result = generate_basic_schedule(week_start)

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