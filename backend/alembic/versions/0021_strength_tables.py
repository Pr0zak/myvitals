"""strength training — equipment, workouts, exercises, sets

Revision ID: 0021
Revises: 0020
Create Date: 2026-05-06 23:30:00.000000

The exercise catalog itself is shipped as a static JSON asset
(backend/src/myvitals/data/exercises.json, derived from
yuhonas/free-exercise-db, public domain) and served from memory —
no exercises table.

`strength_workouts` is the parent session row (planned / in_progress
/ completed / skipped). `strength_workout_exercises` are the
exercises within it (preserves order + superset pairing).
`strength_sets` are the actual logged sets, with both target and
actual fields so the UI can show "you targeted 25 lb x 8, did 25 lb
x 7 (rating: hard)".

`user_equipment` is a single-row JSON-payload table (id always 1) so
adding new equipment categories doesn't need a migration. The
Pydantic layer in api/strength.py validates the payload shape.

Adds `strength_recovery_aware` to `user_profile` so the user can
toggle whether the workout generator reads from daily_summary
(recovery_score, sleep_duration_s, readiness_score).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_equipment",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("unit", sa.String(4), nullable=False, server_default="lb"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "strength_workouts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("split_focus", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="planned"),
        sa.Column("seed", sa.String(64), nullable=False),
        sa.Column("recovery_score_used", sa.Float, nullable=True),
        sa.Column("readiness_score_used", sa.Float, nullable=True),
        sa.Column("sleep_h_used", sa.Float, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
    )
    # One workout row per local day — the latest plan for that day wins on regenerate
    op.create_index(
        "ix_strength_workouts_date_status", "strength_workouts", ["date", "status"]
    )
    op.create_index(
        "ix_strength_workouts_completed_at", "strength_workouts", ["completed_at"]
    )

    op.create_table(
        "strength_workout_exercises",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("workout_id", sa.BigInteger, nullable=False),
        sa.Column("exercise_id", sa.String(128), nullable=False),
        sa.Column("order_index", sa.Integer, nullable=False),
        sa.Column("superset_id", sa.String(16), nullable=True),
        sa.Column("target_sets", sa.Integer, nullable=False),
        sa.Column("target_reps_low", sa.Integer, nullable=False),
        sa.Column("target_reps_high", sa.Integer, nullable=False),
        sa.Column("target_weight_lb", sa.Float, nullable=True),
        sa.Column("target_rest_s", sa.Integer, nullable=False, server_default="90"),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.create_index(
        "ix_strength_workout_exercises_workout",
        "strength_workout_exercises",
        ["workout_id", "order_index"],
    )

    op.create_table(
        "strength_sets",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("workout_exercise_id", sa.BigInteger, nullable=False),
        sa.Column("set_number", sa.Integer, nullable=False),
        sa.Column("target_weight_lb", sa.Float, nullable=True),
        sa.Column("target_reps", sa.Integer, nullable=False),
        sa.Column("actual_weight_lb", sa.Float, nullable=True),
        sa.Column("actual_reps", sa.Integer, nullable=True),
        sa.Column("rating", sa.Integer, nullable=True),  # 1=Failed .. 5=Easy
        sa.Column("rest_seconds_taken", sa.Integer, nullable=True),
        sa.Column("logged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("skipped", sa.Boolean, nullable=False, server_default=sa.text("false")),
    )
    op.create_index(
        "ix_strength_sets_workout_exercise",
        "strength_sets",
        ["workout_exercise_id", "set_number"],
        unique=True,
    )
    op.create_index("ix_strength_sets_logged_at", "strength_sets", ["logged_at"])

    op.add_column(
        "user_profile",
        sa.Column(
            "strength_recovery_aware",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_profile", "strength_recovery_aware")
    op.drop_index("ix_strength_sets_logged_at", table_name="strength_sets")
    op.drop_index("ix_strength_sets_workout_exercise", table_name="strength_sets")
    op.drop_table("strength_sets")
    op.drop_index(
        "ix_strength_workout_exercises_workout",
        table_name="strength_workout_exercises",
    )
    op.drop_table("strength_workout_exercises")
    op.drop_index("ix_strength_workouts_completed_at", table_name="strength_workouts")
    op.drop_index("ix_strength_workouts_date_status", table_name="strength_workouts")
    op.drop_table("strength_workouts")
    op.drop_table("user_equipment")
