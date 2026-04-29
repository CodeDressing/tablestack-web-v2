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
    "Dishwasher",
    "Kitchen",
    "Manager",
    "Owner",
]

SCHEDULE_ROLES = [
    "Server",
    "Bartender",
    "Kitchen",
    "Dishwasher",
    "Busser",
    "Runner",
    "Host",
    "Barback",
    "Food Expeditor",
    "Manager",
]

AVAILABILITY_OPTIONS = ["Both", "Morning", "Dinner", "Unavailable"]

SHIFT_NAMES = ["Morning Shift", "Dinner Shift"]


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


# ============================================================
# SEEDING
# ============================================================

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


# ============================================================
# JSON / EMPLOYEE HELPERS
# ============================================================

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
            "hours": estimate_hours(custom.get("start"), custom.get("end"), shift.hours),
        }

    return {
        "start": shift.start_time,
        "end": shift.end_time,
        "hours": shift.hours,
    }


def estimate_hours(start, end, fallback):
    if not start or not end:
        return fallback

    try:
        start_dt = datetime.strptime(start, "%H:%M")
        end_dt = datetime.strptime(end, "%H:%M")

        if end_dt <= start_dt:
            end_dt += timedelta(days=1)

        hours = (end_dt - start_dt).total_seconds() / 3600
        return round(hours, 2)
    except Exception:
        return fallback


def role_aliases(role):
    aliases = {
        "Runner": ["Runner", "Food Runner"],
        "Food Expeditor": ["Food Expeditor", "Expo"],
        "Expo": ["Expo", "Food Expeditor"],
        "Backwaiter": ["Backwaiter", "Busser"],
        "Busser": ["Busser", "Backwaiter"],
        "Dishwasher": ["Dishwasher"],
        "Kitchen": ["Kitchen", "Kitchen Worker"],
        "Server": ["Server", "Parkside"],
        "Bartender": ["Bartender"],
        "Host": ["Host"],
        "Barback": ["Barback"],
        "Manager": ["Manager", "Owner"],
        "Owner": ["Owner", "Manager"],
    }

    return aliases.get(role, [role])


# ============================================================
# STAFFING PLAN
# ============================================================

def default_staffing_plan():
    plan = {}

    for day in DAYS:
        plan[day] = {
            "Morning Shift": {
                "Server": 2,
                "Bartender": 1,
                "Kitchen": 1,
                "Dishwasher": 0,
                "Busser": 1,
                "Runner": 1,
                "Host": 1,
                "Barback": 0,
                "Food Expeditor": 1,
                "Manager": 1,
            },
            "Dinner Shift": {
                "Server": 4,
                "Bartender": 2,
                "Kitchen": 2,
                "Dishwasher": 1,
                "Busser": 1,
                "Runner": 2,
                "Host": 1,
                "Barback": 1,
                "Food Expeditor": 1,
                "Manager": 1,
            },
        }

    return plan


def parse_staffing_plan_from_form(form):
    plan = {}

    for day in DAYS:
        plan[day] = {}

        for shift_name in SHIFT_NAMES:
            plan[day][shift_name] = {}

            for role in SCHEDULE_ROLES:
                field_name = staffing_field_name(day, shift_name, role)
                raw_value = form.get(field_name, "0")

                try:
                    count = int(raw_value)
                except ValueError:
                    count = 0

                plan[day][shift_name][role] = max(0, count)

    return plan


def staffing_field_name(day, shift_name, role):
    clean_day = day.replace(" ", "_")
    clean_shift = shift_name.replace(" ", "_")
    clean_role = role.replace(" ", "_")
    return f"staff_{clean_day}_{clean_shift}_{clean_role}"


# ============================================================
# SCHEDULE ENGINE
# ============================================================

def generate_smart_schedule(week_start, staffing_plan):
    employees = Employee.query.order_by(Employee.name.asc()).all()
    shifts = ShiftTemplate.query.order_by(ShiftTemplate.id.asc()).all()

    employee_hours = {emp.id: 0 for emp in employees}
    employee_shift_count = {emp.id: 0 for emp in employees}
    employee_labor_cost = {emp.id: 0 for emp in employees}

    rows = []
    violations = []
    coverage_summary = {}
    labor_total = 0

    for day_index, day in enumerate(DAYS):
        current_date = week_start + timedelta(days=day_index)
        coverage_summary[day] = {}

        for shift in shifts:
            shift_plan = staffing_plan.get(day, {}).get(shift.name, {})
            coverage_summary[day][shift.name] = {}

            for needed_role, needed_count in shift_plan.items():
                if needed_count <= 0:
                    continue

                allowed_roles = role_aliases(needed_role)
                candidates = []

                for emp in employees:
                    if emp.role not in allowed_roles:
                        continue

                    if not employee_available_for_shift(emp, day, shift.name):
                        continue

                    shift_time = get_shift_times_for_employee(emp, day, shift)
                    projected_hours = employee_hours[emp.id] + shift_time["hours"]

                    if emp.weekly_hours_target > 0 and projected_hours > emp.weekly_hours_target:
                        continue

                    candidates.append(emp)

                candidates.sort(
                    key=lambda emp: (
                        employee_hours[emp.id],
                        employee_shift_count[emp.id],
                        emp.weekly_hours_target,
                        emp.hourly_rate,
                        emp.name.lower(),
                    )
                )

                selected = candidates[:needed_count]
                filled_count = len(selected)
                missing_count = max(0, needed_count - filled_count)

                coverage_summary[day][shift.name][needed_role] = {
                    "needed": needed_count,
                    "filled": filled_count,
                    "missing": missing_count,
                }

                for emp in selected:
                    shift_time = get_shift_times_for_employee(emp, day, shift)
                    shift_hours = shift_time["hours"]
                    shift_cost = round(shift_hours * emp.hourly_rate, 2)

                    employee_hours[emp.id] += shift_hours
                    employee_shift_count[emp.id] += 1
                    employee_labor_cost[emp.id] += shift_cost
                    labor_total += shift_cost

                    rows.append(
                        {
                            "date": current_date.strftime("%Y-%m-%d"),
                            "day": day,
                            "shift": shift.name,
                            "role": needed_role,
                            "employee": emp.name,
                            "employee_id": emp.id,
                            "start": shift_time["start"],
                            "end": shift_time["end"],
                            "hours": shift_hours,
                            "rate": emp.hourly_rate,
                            "labor_cost": shift_cost,
                            "status": "assigned",
                        }
                    )

                if missing_count > 0:
                    violations.append(
                        f"{day} {shift.name}: missing {missing_count} {needed_role}(s)"
                    )

                    for _ in range(missing_count):
                        rows.append(
                            {
                                "date": current_date.strftime("%Y-%m-%d"),
                                "day": day,
                                "shift": shift.name,
                                "role": needed_role,
                                "employee": "UNASSIGNED",
                                "employee_id": None,
                                "start": shift.start_time,
                                "end": shift.end_time,
                                "hours": shift.hours,
                                "rate": 0,
                                "labor_cost": 0,
                                "status": "unassigned",
                            }
                        )

    employee_hour_summary = []
    for emp in employees:
        hours = round(employee_hours.get(emp.id, 0), 2)
        cost = round(employee_labor_cost.get(emp.id, 0), 2)

        if hours > 0:
            employee_hour_summary.append(
                {
                    "employee": emp.name,
                    "role": emp.role,
                    "target_hours": emp.weekly_hours_target,
                    "scheduled_hours": hours,
                    "hourly_rate": emp.hourly_rate,
                    "labor_cost": cost,
                }
            )

        if emp.employment_type == "Full Time" and 0 < hours < 30:
            violations.append(f"{emp.name}: Full Time but only scheduled {hours} hours")

        if emp.employment_type == "Part Time" and hours > 30:
            violations.append(f"{emp.name}: Part Time scheduled over 30 hours")

        if hours > 40:
            violations.append(f"{emp.name}: scheduled over 40 hours")

    employee_hour_summary.sort(key=lambda item: item["employee"].lower())

    assigned_rows = [row for row in rows if row["status"] == "assigned"]
    unassigned_rows = [row for row in rows if row["status"] == "unassigned"]

    return {
        "week_start": week_start.strftime("%Y-%m-%d"),
        "week_end": (week_start + timedelta(days=6)).strftime("%Y-%m-%d"),
        "rows": rows,
        "staffing_plan": staffing_plan,
        "coverage_summary": coverage_summary,
        "employee_hour_summary": employee_hour_summary,
        "labor_total": round(labor_total, 2),
        "assigned_count": len(assigned_rows),
        "unassigned_count": len(unassigned_rows),
        "violations": violations,
        "engine": "Phase 5 Manager Staffing Planner",
    }


# ============================================================
# ROUTES
# ============================================================

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

            if not week_start_raw:
                return redirect(url_for("generate_schedule"))

            week_start = datetime.strptime(week_start_raw, "%Y-%m-%d")
            staffing_plan = parse_staffing_plan_from_form(request.form)
            result = generate_smart_schedule(week_start, staffing_plan)

            schedule = Schedule(
                name=request.form.get("schedule_name") or f"Week of {result['week_start']}",
                week_start=result["week_start"],
                week_end=result["week_end"],
                schedule_json=json.dumps(result),
            )

            db.session.add(schedule)
            db.session.commit()

            return redirect(url_for("view_schedule", id=schedule.id))

        return render_template(
            "generate_schedule.html",
            days=DAYS,
            shifts=SHIFT_NAMES,
            roles=SCHEDULE_ROLES,
            staffing_plan=default_staffing_plan(),
            staffing_field_name=staffing_field_name,
        )

    @app.route("/schedules/<int:id>")
    def view_schedule(id):
        schedule = Schedule.query.get_or_404(id)
        data = json.loads(schedule.schedule_json)

        return render_template(
            "view_schedule.html",
            schedule=schedule,
            data=data,
        )

    @app.route("/health")
    def health():
        return {
            "status": "ok",
            "app": "TableStack Web v2",
            "routes": "registered",
            "engine": "Phase 5 Manager Staffing Planner",
        }


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=True,
    )