-- SmartFactory AI schema for SQL Server (generated from backend/app/db.py, v0.3).
-- Run in SSMS against an empty database. The app also creates missing tables and adds missing columns on startup.

IF DB_ID(N'smartfactory') IS NULL CREATE DATABASE smartfactory;
GO
USE smartfactory;
GO
CREATE TABLE api_keys (
	id INTEGER NOT NULL IDENTITY, 
	name NVARCHAR(100) NOT NULL, 
	prefix VARCHAR(12) NOT NULL, 
	key_hash VARCHAR(64) NOT NULL, 
	scopes VARCHAR(200) NOT NULL, 
	created_at DATETIME NOT NULL, 
	last_used_at DATETIME NULL, 
	revoked BIT NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (key_hash)
);
GO
CREATE TABLE audit_log (
	id INTEGER NOT NULL IDENTITY, 
	at DATETIME NOT NULL, 
	actor NVARCHAR(100) NOT NULL, 
	actor_role VARCHAR(30) NOT NULL, 
	event VARCHAR(50) NOT NULL, 
	entity VARCHAR(50) NOT NULL, 
	entity_id VARCHAR(32) NOT NULL, 
	detail NVARCHAR(1000) NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_audit_log_at ON audit_log (at);
GO
CREATE TABLE datasets (
	id VARCHAR(32) NOT NULL, 
	name NVARCHAR(255) NOT NULL, 
	synthetic BIT NOT NULL, 
	warnings_json NVARCHAR(max) NOT NULL, 
	file_uri NVARCHAR(500) NULL, 
	uploaded_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
GO
CREATE TABLE integration_log (
	id INTEGER NOT NULL IDENTITY, 
	ts DATETIME NOT NULL, 
	channel VARCHAR(30) NOT NULL, 
	status VARCHAR(10) NOT NULL, 
	records INTEGER NOT NULL, 
	message NVARCHAR(500) NOT NULL, 
	api_key_prefix VARCHAR(12) NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_integration_log_ts ON integration_log (ts);
GO
CREATE TABLE machines (
	id INTEGER NOT NULL IDENTITY, 
	machine_code NVARCHAR(64) NOT NULL, 
	line NVARCHAR(100) NOT NULL, 
	machine_type NVARCHAR(100) NOT NULL, 
	synthetic BIT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (machine_code)
);
GO
CREATE TABLE model_runs (
	id INTEGER NOT NULL IDENTITY, 
	created_at DATETIME NOT NULL, 
	algorithm VARCHAR(100) NOT NULL, 
	horizon_hours INTEGER NOT NULL, 
	threshold FLOAT NOT NULL, 
	n_train INTEGER NOT NULL, 
	n_test INTEGER NOT NULL, 
	metrics_json NVARCHAR(max) NOT NULL, 
	importance_json NVARCHAR(max) NOT NULL, 
	features_json NVARCHAR(max) NOT NULL, 
	model_uri NVARCHAR(500) NOT NULL, 
	data_from DATETIME NULL, 
	data_to DATETIME NULL, 
	PRIMARY KEY (id)
);
GO
CREATE TABLE station_records (
	id INTEGER NOT NULL IDENTITY, 
	date DATETIME NOT NULL, 
	line NVARCHAR(100) NOT NULL, 
	station NVARCHAR(100) NOT NULL, 
	available_minutes FLOAT NOT NULL, 
	downtime_minutes FLOAT NOT NULL, 
	units_processed FLOAT NOT NULL, 
	ideal_cycle_time_s FLOAT NOT NULL, 
	wip_units FLOAT NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	synthetic BIT NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_station_line_station_date ON station_records (line, station, date);
GO
CREATE TABLE work_orders (
	order_id NVARCHAR(64) NOT NULL, 
	product NVARCHAR(200) NOT NULL, 
	line NVARCHAR(100) NOT NULL, 
	quantity FLOAT NOT NULL, 
	due_date DATETIME NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	customer NVARCHAR(100) NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	synthetic BIT NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (order_id)
);
GO
CREATE TABLE workflow_runs (
	id VARCHAR(32) NOT NULL, 
	dataset_id VARCHAR(32) NULL, 
	finding_id VARCHAR(16) NOT NULL, 
	finding_title NVARCHAR(300) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	mode VARCHAR(10) NOT NULL, 
	requested_by NVARCHAR(100) NOT NULL, 
	steps_json NVARCHAR(max) NOT NULL, 
	plan_json NVARCHAR(max) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_workflow_runs_dataset_id ON workflow_runs (dataset_id);
GO
CREATE TABLE actions (
	id VARCHAR(32) NOT NULL, 
	dataset_id VARCHAR(32) NULL, 
	title NVARCHAR(200) NOT NULL, 
	owner_role NVARCHAR(100) NOT NULL, 
	finding_ids NVARCHAR(500) NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	note NVARCHAR(1000) NOT NULL, 
	priority VARCHAR(10) NOT NULL, 
	due_date DATETIME NULL, 
	workflow_id VARCHAR(32) NULL, 
	action_type VARCHAR(30) NOT NULL, 
	approval_levels INTEGER NOT NULL, 
	approved_levels INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(dataset_id) REFERENCES datasets (id) ON DELETE CASCADE
);
CREATE INDEX ix_actions_workflow_id ON actions (workflow_id);
CREATE INDEX ix_actions_dataset_id ON actions (dataset_id);
GO
CREATE TABLE insight_runs (
	id INTEGER NOT NULL IDENTITY, 
	dataset_id VARCHAR(32) NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	model VARCHAR(100) NULL, 
	question NVARCHAR(500) NULL, 
	note NVARCHAR(1000) NULL, 
	report_json NVARCHAR(max) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(dataset_id) REFERENCES datasets (id) ON DELETE CASCADE
);
CREATE INDEX ix_insight_runs_dataset_id ON insight_runs (dataset_id);
GO
CREATE TABLE inspections (
	id VARCHAR(32) NOT NULL, 
	dataset_id VARCHAR(32) NOT NULL, 
	seq INTEGER NOT NULL, 
	line NVARCHAR(100) NOT NULL, 
	part NVARCHAR(200) NOT NULL, 
	notes NVARCHAR(500) NOT NULL, 
	image_uri NVARCHAR(500) NOT NULL, 
	mime_type VARCHAR(50) NOT NULL, 
	defect_detected BIT NOT NULL, 
	defect_type VARCHAR(50) NOT NULL, 
	severity VARCHAR(20) NOT NULL, 
	confidence FLOAT NOT NULL, 
	description NVARCHAR(1000) NOT NULL, 
	visible_evidence NVARCHAR(1000) NOT NULL, 
	recommended_action NVARCHAR(500) NOT NULL, 
	image_quality_ok BIT NOT NULL, 
	model VARCHAR(100) NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(dataset_id) REFERENCES datasets (id) ON DELETE CASCADE
);
CREATE INDEX ix_inspections_dataset_id ON inspections (dataset_id);
GO
CREATE TABLE machine_events (
	id INTEGER NOT NULL IDENTITY, 
	machine_id INTEGER NOT NULL, 
	ts DATETIME NOT NULL, 
	event_type VARCHAR(20) NOT NULL, 
	description NVARCHAR(500) NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(machine_id) REFERENCES machines (id) ON DELETE CASCADE
);
CREATE INDEX ix_machine_events_machine_id ON machine_events (machine_id);
GO
CREATE TABLE production_records (
	id INTEGER NOT NULL IDENTITY, 
	dataset_id VARCHAR(32) NOT NULL, 
	date DATETIME NOT NULL, 
	line NVARCHAR(100) NOT NULL, 
	shift NVARCHAR(50) NOT NULL, 
	product NVARCHAR(200) NOT NULL, 
	target_output FLOAT NOT NULL, 
	actual_output FLOAT NOT NULL, 
	inspected_units FLOAT NOT NULL, 
	defective_units FLOAT NOT NULL, 
	downtime_minutes FLOAT NOT NULL, 
	downtime_reason NVARCHAR(200) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(dataset_id) REFERENCES datasets (id) ON DELETE CASCADE
);
CREATE INDEX ix_production_records_dataset_id ON production_records (dataset_id);
GO
CREATE TABLE sensor_readings (
	id BIGINT NOT NULL IDENTITY, 
	machine_id INTEGER NOT NULL, 
	ts DATETIME NOT NULL, 
	temperature_c FLOAT NULL, 
	vibration_mm_s FLOAT NULL, 
	current_a FLOAT NULL, 
	pressure_bar FLOAT NULL, 
	rpm FLOAT NULL, 
	source VARCHAR(20) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(machine_id) REFERENCES machines (id) ON DELETE CASCADE
);
CREATE INDEX ix_sensor_machine_ts ON sensor_readings (machine_id, ts);
GO
CREATE TABLE approvals (
	id INTEGER NOT NULL IDENTITY, 
	action_id VARCHAR(32) NOT NULL, 
	level INTEGER NOT NULL, 
	role VARCHAR(30) NOT NULL, 
	decision VARCHAR(10) NOT NULL, 
	by_name NVARCHAR(100) NOT NULL, 
	comment NVARCHAR(1000) NOT NULL, 
	at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(action_id) REFERENCES actions (id) ON DELETE CASCADE
);
CREATE INDEX ix_approvals_action_id ON approvals (action_id);
GO
