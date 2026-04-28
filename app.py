import os
import json
from flask import Flask, render_template, redirect, url_for, flash
from models import db, Employee, ShiftTemplate


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

    morning_role_times = {
        "Server": {"start": "10:00", "end": "18:00", "hours": 8},
        "Bartender": {"start": "11:00", "end": "19:00", "hours": 8},
        "Barback": {"start": "11:00", "end": "19:00", "hours": 8},
        "Runner": {"start": "10:30", "end": "18:30", "hours": 8},
        "Backwaiter": {"start": "10:30", "end": "18:30", "hours": 8},
        "Expo": {"start": "10:30", "end": "18:30", "hours": 8},
        "Food Expeditor": {"start": "10:30", "end": "18:30", "hours": 8},
        "Host": {"start": "10:30", "end": "18:30", "hours": 8},
        "Manager": {"start": "10:00", "end": "18:00", "hours": 8},
        "Owner": {"start": "10:00", "end": "18:00", "hours": 8},
    }

    dinner_role_times = {
        "Server": {"start": "16:00", "end": "00:00", "hours": 8},
        "Bartender": {"start": "17:00", "end": "01:00", "hours": 8},
        "Barback": {"start": "17:00", "end": "01:00", "hours": 8},
        "Runner": {"start": "16:30", "end": "00:30", "hours": 8},
        "Backwaiter": {"start": "16:30", "end": "00:30", "hours": 8},
        "Expo": {"start": "16:30", "end": "00:30", "hours": 8},
        "Food Expeditor": {"start": "16:30", "end": "00:30", "hours": 8},
        "Host": {"start": "16:30", "end": "00:30", "hours": 8},
        "Manager": {"start": "16:00", "end": "00:00", "hours": 8},
        "Owner": {"start": "16:00", "end": "00:00", "hours": 8},
    }

    db.session.add(
        ShiftTemplate(
            name="Morning Shift",
            start_time="10:00",
            end_time="18:00",
            hours=8,
            role_times_json=json.dumps(morning_role_times),
        )
    )

    db.session.add(
        ShiftTemplate(
            name="Dinner Shift",
            start_time="16:00",
            end_time="00:00",
            hours=8,
            role_times_json=json.dumps(dinner_role_times),
        )
    )

    db.session.commit()


def register_routes(app):
    @app.route("/")
    def index():
        employee_count = Employee.query.count()
        return render_template("index.html", employee_count=employee_count)

    @app.route("/employees")
    def employees():
        all_employees = Employee.query.order_by(Employee.name.asc()).all()
        return render_template("employees.html", employees=all_employees)

    @app.route("/health")
    def health():
        return {
            "status": "ok",
            "app": "TableStack Web v2",
        }


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)