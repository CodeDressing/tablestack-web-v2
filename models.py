from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Employee(db.Model):
    __tablename__ = "employees"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(80), nullable=False)
    employment_type = db.Column(db.String(40), nullable=False, default="Part Time")
    weekly_hours_target = db.Column(db.Float, default=20.0)
    hourly_rate = db.Column(db.Float, default=15.0)

    pref = db.Column(db.String(80), default="Any")
    custom_times_json = db.Column(db.Text, default="{}")
    availability_json = db.Column(db.Text, default="{}")
    unavailable_dates_json = db.Column(db.Text, default="[]")
    notes = db.Column(db.Text, default="")

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TimeOffRequest(db.Model):
    __tablename__ = "timeoff_requests"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)

    start_date = db.Column(db.String(20), nullable=False)
    end_date = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.String(120), default="Other")
    status = db.Column(db.String(30), default="Pending")

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    employee = db.relationship("Employee", backref="timeoff_requests")


class Schedule(db.Model):
    __tablename__ = "schedules"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    week_start = db.Column(db.String(20), nullable=False)
    week_end = db.Column(db.String(20), nullable=False)
    schedule_json = db.Column(db.Text, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ShiftTemplate(db.Model):
    __tablename__ = "shift_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    start_time = db.Column(db.String(20), nullable=False)
    end_time = db.Column(db.String(20), nullable=False)
    hours = db.Column(db.Float, default=8.0)
    role_times_json = db.Column(db.Text, default="{}")

    created_at = db.Column(db.DateTime, default=datetime.utcnow)