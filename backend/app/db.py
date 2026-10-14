"""Database layer (SQLAlchemy). Production target: SQL Server (Cloud SQL for SQL Server).

Connection is chosen from environment variables, in this order:
  1. CLOUD_SQL_INSTANCE=project:region:instance  (+ DB_USER, DB_PASS, DB_NAME)
     -> Cloud SQL Python Connector (pytds driver). Recommended on Cloud Run.
  2. DATABASE_URL, e.g. mssql+pymssql://user:pass@host:1433/smartfactory
     -> any SQL Server reachable over TCP (local SQL Server, SSMS-managed instance, Azure SQL),
     or postgresql://user:pass@host:5432/db (e.g. Render PostgreSQL; the psycopg 3 driver is used).
  3. Nothing set -> local SQLite file (development only).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.dialects import mssql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


# NVARCHAR(max) on SQL Server (avoids deprecated NTEXT), TEXT elsewhere.
LongText = sa.UnicodeText().with_variant(mssql.NVARCHAR("max"), "mssql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    name: Mapped[str] = mapped_column(sa.Unicode(255))
    synthetic: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    warnings_json: Mapped[str] = mapped_column(LongText, default="[]")
    file_uri: Mapped[str | None] = mapped_column(sa.Unicode(500), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(sa.DateTime, default=utcnow)
    records: Mapped[list["ProductionRecord"]] = relationship(back_populates="dataset", cascade="all, delete-orphan")


class ProductionRecord(Base):
    __tablename__ = "production_records"
    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(sa.ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    date: Mapped[datetime] = mapped_column(sa.Date)
    line: Mapped[str] = mapped_column(sa.Unicode(100))
    shift: Mapped[str] = mapped_column(sa.Unicode(50), default="")
    product: Mapped[str] = mapped_column(sa.Unicode(200), default="")
    target_output: Mapped[float] = mapped_column(sa.Float)
    actual_output: Mapped[float] = mapped_column(sa.Float)
    inspected_units: Mapped[float] = mapped_column(sa.Float)
    defective_units: Mapped[float] = mapped_column(sa.Float)
    downtime_minutes: Mapped[float] = mapped_column(sa.Float)
    downtime_reason: Mapped[str] = mapped_column(sa.Unicode(200), default="")
    dataset: Mapped[Dataset] = relationship(back_populates="records")


class InsightRun(Base):
    __tablename__ = "insight_runs"
    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(sa.ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(sa.String(20))
    model: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    question: Mapped[str | None] = mapped_column(sa.Unicode(500), nullable=True)
    note: Mapped[str | None] = mapped_column(sa.Unicode(1000), nullable=True)
    report_json: Mapped[str] = mapped_column(LongText)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=utcnow)


class Action(Base):
    __tablename__ = "actions"
    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    # NULL = plant-level action (e.g. from a machine-health or bottleneck workflow)
    dataset_id: Mapped[str | None] = mapped_column(sa.ForeignKey("datasets.id", ondelete="CASCADE"), index=True, nullable=True)
    title: Mapped[str] = mapped_column(sa.Unicode(200))
    owner_role: Mapped[str] = mapped_column(sa.Unicode(100), default="")
    finding_ids: Mapped[str] = mapped_column(sa.Unicode(500), default="")  # space-separated
    source: Mapped[str] = mapped_column(sa.String(20), default="manual")
    status: Mapped[str] = mapped_column(sa.String(20), default="pending")
    note: Mapped[str] = mapped_column(sa.Unicode(1000), default="")
    priority: Mapped[str] = mapped_column(sa.String(10), default="medium")
    due_date: Mapped[datetime | None] = mapped_column(sa.Date, nullable=True)
    workflow_id: Mapped[str | None] = mapped_column(sa.String(32), nullable=True, index=True)
    action_type: Mapped[str] = mapped_column(sa.String(30), default="corrective")  # corrective | maintenance_work_order | quality_containment | production_change
    approval_levels: Mapped[int] = mapped_column(sa.Integer, default=1)          # 1 = supervisor, 2 = + plant manager
    approved_levels: Mapped[int] = mapped_column(sa.Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime, default=utcnow)


class Inspection(Base):
    __tablename__ = "inspections"
    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(sa.ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(sa.Integer)  # 1,2,3… per dataset -> stable finding IDs V1, V2…
    line: Mapped[str] = mapped_column(sa.Unicode(100))
    part: Mapped[str] = mapped_column(sa.Unicode(200), default="")
    notes: Mapped[str] = mapped_column(sa.Unicode(500), default="")
    image_uri: Mapped[str] = mapped_column(sa.Unicode(500))
    mime_type: Mapped[str] = mapped_column(sa.String(50))
    defect_detected: Mapped[bool] = mapped_column(sa.Boolean)
    defect_type: Mapped[str] = mapped_column(sa.String(50))
    severity: Mapped[str] = mapped_column(sa.String(20))
    confidence: Mapped[float] = mapped_column(sa.Float)
    description: Mapped[str] = mapped_column(sa.Unicode(1000))
    visible_evidence: Mapped[str] = mapped_column(sa.Unicode(1000), default="")
    recommended_action: Mapped[str] = mapped_column(sa.Unicode(500), default="")
    image_quality_ok: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    model: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=utcnow)


# ---------------- Level 3: machines & sensors ----------------

class Machine(Base):
    __tablename__ = "machines"
    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    machine_code: Mapped[str] = mapped_column(sa.Unicode(64), unique=True)
    line: Mapped[str] = mapped_column(sa.Unicode(100), default="")
    machine_type: Mapped[str] = mapped_column(sa.Unicode(100), default="")
    synthetic: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=utcnow)


class SensorReading(Base):
    __tablename__ = "sensor_readings"
    __table_args__ = (sa.Index("ix_sensor_machine_ts", "machine_id", "ts"),)
    id: Mapped[int] = mapped_column(sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True, autoincrement=True)
    machine_id: Mapped[int] = mapped_column(sa.ForeignKey("machines.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(sa.DateTime)
    temperature_c: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    vibration_mm_s: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    current_a: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    pressure_bar: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    rpm: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    source: Mapped[str] = mapped_column(sa.String(20), default="upload")


class MachineEvent(Base):
    __tablename__ = "machine_events"
    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    machine_id: Mapped[int] = mapped_column(sa.ForeignKey("machines.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(sa.DateTime)
    event_type: Mapped[str] = mapped_column(sa.String(20))   # failure | maintenance
    description: Mapped[str] = mapped_column(sa.Unicode(500), default="")
    source: Mapped[str] = mapped_column(sa.String(20), default="upload")


class ModelRun(Base):
    __tablename__ = "model_runs"
    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=utcnow)
    algorithm: Mapped[str] = mapped_column(sa.String(100))
    horizon_hours: Mapped[int] = mapped_column(sa.Integer)
    threshold: Mapped[float] = mapped_column(sa.Float)
    n_train: Mapped[int] = mapped_column(sa.Integer)
    n_test: Mapped[int] = mapped_column(sa.Integer)
    metrics_json: Mapped[str] = mapped_column(LongText)
    importance_json: Mapped[str] = mapped_column(LongText)
    features_json: Mapped[str] = mapped_column(LongText)
    model_uri: Mapped[str] = mapped_column(sa.Unicode(500))
    data_from: Mapped[datetime | None] = mapped_column(sa.DateTime, nullable=True)
    data_to: Mapped[datetime | None] = mapped_column(sa.DateTime, nullable=True)


# ---------------- Level 3: stations, ERP work orders ----------------

class StationRecord(Base):
    __tablename__ = "station_records"
    __table_args__ = (sa.Index("ix_station_line_station_date", "line", "station", "date"),)
    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime] = mapped_column(sa.Date)
    line: Mapped[str] = mapped_column(sa.Unicode(100))
    station: Mapped[str] = mapped_column(sa.Unicode(100))
    available_minutes: Mapped[float] = mapped_column(sa.Float)
    downtime_minutes: Mapped[float] = mapped_column(sa.Float)
    units_processed: Mapped[float] = mapped_column(sa.Float)
    ideal_cycle_time_s: Mapped[float] = mapped_column(sa.Float)
    wip_units: Mapped[float] = mapped_column(sa.Float, default=0)
    source: Mapped[str] = mapped_column(sa.String(20), default="upload")
    synthetic: Mapped[bool] = mapped_column(sa.Boolean, default=False)


class WorkOrder(Base):
    __tablename__ = "work_orders"
    order_id: Mapped[str] = mapped_column(sa.Unicode(64), primary_key=True)
    product: Mapped[str] = mapped_column(sa.Unicode(200), default="")
    line: Mapped[str] = mapped_column(sa.Unicode(100))
    quantity: Mapped[float] = mapped_column(sa.Float)
    due_date: Mapped[datetime] = mapped_column(sa.Date)
    status: Mapped[str] = mapped_column(sa.String(20), default="planned")
    customer: Mapped[str] = mapped_column(sa.Unicode(100), default="")
    source: Mapped[str] = mapped_column(sa.String(20), default="upload")
    synthetic: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime, default=utcnow)


# ---------------- Level 3: integrations ----------------

class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(sa.Unicode(100))
    prefix: Mapped[str] = mapped_column(sa.String(12))
    key_hash: Mapped[str] = mapped_column(sa.String(64), unique=True)
    scopes: Mapped[str] = mapped_column(sa.String(200), default="iot erp")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(sa.DateTime, nullable=True)
    revoked: Mapped[bool] = mapped_column(sa.Boolean, default=False)


class IntegrationLog(Base):
    __tablename__ = "integration_log"
    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(sa.DateTime, default=utcnow, index=True)
    channel: Mapped[str] = mapped_column(sa.String(30))      # iot-http | pubsub | erp-orders | erp-production
    status: Mapped[str] = mapped_column(sa.String(10))       # ok | error
    records: Mapped[int] = mapped_column(sa.Integer, default=0)
    message: Mapped[str] = mapped_column(sa.Unicode(500), default="")
    api_key_prefix: Mapped[str | None] = mapped_column(sa.String(12), nullable=True)


# ---------------- Level 3: agent workflows & approvals ----------------

class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    dataset_id: Mapped[str | None] = mapped_column(sa.String(32), nullable=True, index=True)
    finding_id: Mapped[str] = mapped_column(sa.String(16))
    finding_title: Mapped[str] = mapped_column(sa.Unicode(300))
    status: Mapped[str] = mapped_column(sa.String(20), default="running")   # running | awaiting_approval | approved | rejected | done | failed
    mode: Mapped[str] = mapped_column(sa.String(10), default="rules")         # gemini | rules
    requested_by: Mapped[str] = mapped_column(sa.Unicode(100), default="")
    steps_json: Mapped[str] = mapped_column(LongText, default="[]")
    plan_json: Mapped[str] = mapped_column(LongText, default="{}")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime, default=utcnow)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    action_id: Mapped[str] = mapped_column(sa.ForeignKey("actions.id", ondelete="CASCADE"), index=True)
    level: Mapped[int] = mapped_column(sa.Integer)
    role: Mapped[str] = mapped_column(sa.String(30))
    decision: Mapped[str] = mapped_column(sa.String(10))   # approved | rejected
    by_name: Mapped[str] = mapped_column(sa.Unicode(100))
    comment: Mapped[str] = mapped_column(sa.Unicode(1000), default="")
    at: Mapped[datetime] = mapped_column(sa.DateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(sa.DateTime, default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(sa.Unicode(100))        # person name or agent name
    actor_role: Mapped[str] = mapped_column(sa.String(30))
    event: Mapped[str] = mapped_column(sa.String(50))
    entity: Mapped[str] = mapped_column(sa.String(50))
    entity_id: Mapped[str] = mapped_column(sa.String(32))
    detail: Mapped[str] = mapped_column(sa.Unicode(1000), default="")


def normalise_url(url: str) -> str:
    """Hosting providers (Render, Heroku…) give postgres://… URLs; SQLAlchemy needs a driver name."""
    url = url.strip()
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


class StoredFile(Base):
    """File storage inside the database (STORAGE_BACKEND=db) for hosts without persistent disks."""
    __tablename__ = "stored_files"
    path: Mapped[str] = mapped_column(sa.Unicode(400), primary_key=True)
    content_type: Mapped[str] = mapped_column(sa.String(100))
    data: Mapped[bytes] = mapped_column(sa.LargeBinary().with_variant(mssql.VARBINARY("max"), "mssql"))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=utcnow)


def _make_engine() -> sa.Engine:
    instance = os.getenv("CLOUD_SQL_INSTANCE")
    if instance:
        from google.cloud.sql.connector import Connector, IPTypes

        connector = Connector()
        ip_type = IPTypes.PRIVATE if os.getenv("DB_PRIVATE_IP", "").lower() in ("1", "true") else IPTypes.PUBLIC

        def creator():
            return connector.connect(
                instance, "pytds",
                user=os.environ["DB_USER"], password=os.environ["DB_PASS"],
                db=os.getenv("DB_NAME", "smartfactory"), ip_type=ip_type,
            )
        return sa.create_engine("mssql+pytds://", creator=creator, pool_pre_ping=True, pool_size=5, max_overflow=2)

    url = normalise_url(os.getenv("DATABASE_URL", ""))
    if url:
        return sa.create_engine(url, pool_pre_ping=True, pool_recycle=280)

    path = os.getenv("SQLITE_PATH", "smartfactory_dev.db")
    eng = sa.create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @sa.event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")
    return eng


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
    migrate()


def migrate() -> list[str]:
    """Lightweight forward migration: add columns that exist in the models but not yet in the database
    (e.g. a database created by an earlier version). Works for SQL Server and SQLite. Never drops anything."""
    import logging
    insp = sa.inspect(engine)
    added = []
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            cols = {c["name"]: c for c in insp.get_columns(table.name)}
            have = set(cols)
            for col in table.columns:
                if col.name in cols and col.nullable and not cols[col.name]["nullable"] and not col.primary_key:
                    logging.getLogger("smartfactory").warning(
                        "Column %s.%s is NOT NULL in the database but nullable in this version. Run: "
                        "ALTER TABLE %s ALTER COLUMN %s %s NULL (drop/recreate its index first on SQL Server), "
                        "or recreate a development database.", table.name, col.name, table.name, col.name,
                        col.type.compile(dialect=engine.dialect))
                if col.name in have:
                    continue
                ddl_type = col.type.compile(dialect=engine.dialect)
                kw = "ADD COLUMN" if engine.dialect.name == "sqlite" else "ADD"
                conn.execute(sa.text(f"ALTER TABLE {table.name} {kw} {col.name} {ddl_type} NULL"))
                default = col.default.arg if col.default is not None and not callable(col.default.arg) else None
                if default is not None:
                    conn.execute(sa.text(f"UPDATE {table.name} SET {col.name} = :v"), {"v": default})
                added.append(f"{table.name}.{col.name}")
    if added:
        logging.getLogger("smartfactory").info("Database migrated, added columns: %s", ", ".join(added))
    return added


def get_session():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def backend_name() -> str:
    return engine.dialect.name  # 'mssql' or 'sqlite'
