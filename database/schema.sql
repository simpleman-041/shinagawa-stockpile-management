-- UnFire DB redesign 2026-11-01. 新規DB専用。既存DBへ直接適用しない。
-- 全接続でトランザクション開始前に foreign_keys=ON を設定し、戻り値1を確認する。
-- 業務検証はWord設計書のトランザクション契約に従う。DDLだけで専用件数・割当上限等は保証しない。
-- 数量等はREAL、換算係数のみ100倍INTEGER。数値入力の精度はアプリで十進文字列を検証。
-- 通常は親マスタから登録。計算保存はBEGIN IMMEDIATE内で子行を先に、calculation_runsを最後にINSERT。
-- 計算run_idは同一書込トランザクション内でMAX(run_id)+1を確保。REPLACE/UPSERTは禁止。
-- ABORTは文単位。どの例外でも呼出元がROLLBACKし、途中更新をCOMMITしない。
-- 日時UTC、期限判定・基準日JST。値の推定・初期業務データの投入なし。
PRAGMA foreign_keys=ON;
PRAGMA recursive_triggers=ON;
BEGIN;

-- 担当者 / Q09 Q17
CREATE TABLE operators (
  operator_id INTEGER NOT NULL CHECK (operator_id>0),
  name TEXT NOT NULL CHECK (length(trim(name))>0),
  PRIMARY KEY (operator_id)
);

-- 倉庫 / Q16 Q19 Q27 Q32 U07
CREATE TABLE warehouses (
  warehouse_id INTEGER NOT NULL CHECK (warehouse_id>0),
  name TEXT NOT NULL CHECK (length(trim(name))>0),
  facility_type TEXT NOT NULL CHECK (length(trim(facility_type))>0),
  address TEXT NOT NULL CHECK (length(trim(address))>0),
  latitude REAL CHECK (latitude IS NULL OR (latitude BETWEEN -90 AND 90)),
  longitude REAL CHECK (longitude IS NULL OR (longitude BETWEEN -180 AND 180)),
  capacity_m3 REAL CHECK (capacity_m3 IS NULL OR (typeof(capacity_m3) IN ('real','integer') AND capacity_m3>=0 AND capacity_m3<=1.7976931348623157e308)),
  allocation_mode TEXT CHECK (allocation_mode IS NULL OR (allocation_mode IN ('dedicated','shared'))),
  PRIMARY KEY (warehouse_id),
  CHECK ((latitude IS NULL)=(longitude IS NULL))
);

-- 避難所 / Q13 Q33 Q69 P02 U01
CREATE TABLE shelters (
  shelter_id INTEGER NOT NULL CHECK (shelter_id>0),
  name TEXT NOT NULL CHECK (length(trim(name))>0),
  address TEXT NOT NULL CHECK (length(trim(address))>0),
  target_people INTEGER CHECK (target_people IS NULL OR (typeof(target_people)='integer' AND target_people>=1)),
  target_days INTEGER CHECK (target_days IS NULL OR (typeof(target_days)='integer' AND target_days>=1)),
  setup_state TEXT NOT NULL DEFAULT 'editing' CHECK (setup_state IN ('editing','complete')),
  PRIMARY KEY (shelter_id),
  CHECK ((target_people IS NULL)=(target_days IS NULL))
);

-- 品目 / Q05 Q07 Q46 Q47 Q48 Q49 Q50 Q51 Q52 Q53 U03
CREATE TABLE items (
  item_id INTEGER NOT NULL CHECK (item_id>0),
  name TEXT NOT NULL CHECK (length(trim(name))>0),
  category TEXT NOT NULL CHECK (length(trim(category))>0),
  quantity_unit TEXT NOT NULL CHECK (length(trim(quantity_unit))>0),
  unit_volume_m3 REAL CHECK (unit_volume_m3 IS NULL OR (typeof(unit_volume_m3) IN ('real','integer') AND unit_volume_m3>=0 AND unit_volume_m3<=1.7976931348623157e308)),
  is_divisible INTEGER NOT NULL CHECK (is_divisible IN (0,1)),
  near_expiry_days INTEGER NOT NULL CHECK (typeof(near_expiry_days)='integer' AND near_expiry_days>=1),
  registration_state TEXT NOT NULL DEFAULT 'active' CHECK (registration_state IN ('active','closed')),
  PRIMARY KEY (item_id),
  CHECK (near_expiry_days<=3650)
);

-- 在庫 / Q04 Q28 Q29 Q30 Q31 Q40 Q41 Q44 追加3.2
CREATE TABLE stocks (
  stock_id INTEGER NOT NULL CHECK (stock_id>0),
  warehouse_id INTEGER NOT NULL CHECK (warehouse_id>0),
  item_id INTEGER NOT NULL CHECK (item_id>0),
  location TEXT NOT NULL CHECK (length(trim(location))>0),
  quantity REAL NOT NULL CHECK (typeof(quantity) IN ('real','integer') AND quantity>=0 AND quantity<=1.7976931348623157e308),
  expiry_state TEXT NOT NULL CHECK (expiry_state IN ('dated','none','unconfirmed')),
  expiry_date TEXT CHECK (expiry_date IS NULL OR (length(expiry_date)=10 AND expiry_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')),
  state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active','deleted','merged')),
  merged_into_stock_id INTEGER,
  merged_at TEXT CHECK (merged_at IS NULL OR (length(merged_at)=24 AND merged_at GLOB '????-??-??T??:??:??.???Z')),
  merged_by INTEGER,
  merge_generation INTEGER NOT NULL DEFAULT 0 CHECK (typeof(merge_generation)='integer' AND merge_generation>=0),
  PRIMARY KEY (stock_id),
  CHECK (((expiry_state='dated' AND expiry_date IS NOT NULL) OR (expiry_state IN ('none','unconfirmed') AND expiry_date IS NULL))),
  CHECK ((state='merged' AND merged_into_stock_id IS NOT NULL AND merged_at IS NOT NULL AND merged_by IS NOT NULL AND quantity=0) OR (state IN ('active','deleted') AND merged_into_stock_id IS NULL AND merged_at IS NULL AND merged_by IS NULL)),
  CHECK (merged_into_stock_id IS NULL OR merged_into_stock_id<>stock_id),
  FOREIGN KEY (warehouse_id) REFERENCES warehouses (warehouse_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY (item_id) REFERENCES items (item_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY (merged_into_stock_id) REFERENCES stocks (stock_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY (merged_by) REFERENCES operators (operator_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

-- 避難所と倉庫の対応 / Q03 Q16 Q67 Q68 U01 U02 U07
CREATE TABLE shelter_warehouses (
  shelter_id INTEGER NOT NULL CHECK (shelter_id>0),
  warehouse_id INTEGER NOT NULL CHECK (warehouse_id>0),
  PRIMARY KEY (shelter_id, warehouse_id),
  FOREIGN KEY (shelter_id) REFERENCES shelters (shelter_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY (warehouse_id) REFERENCES warehouses (warehouse_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

-- 共有在庫割当 / Q14 Q15 Q65 Q67
CREATE TABLE stock_allocations (
  stock_id INTEGER NOT NULL CHECK (stock_id>0),
  shelter_id INTEGER NOT NULL CHECK (shelter_id>0),
  quantity REAL NOT NULL CHECK (typeof(quantity) IN ('real','integer') AND quantity>0 AND quantity<=1.7976931348623157e308),
  PRIMARY KEY (stock_id, shelter_id),
  FOREIGN KEY (stock_id) REFERENCES stocks (stock_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY (shelter_id) REFERENCES shelters (shelter_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

-- 日常管理基準 / Q06 Q66 §7 §15
CREATE TABLE stock_thresholds (
  warehouse_id INTEGER NOT NULL CHECK (warehouse_id>0),
  item_id INTEGER NOT NULL CHECK (item_id>0),
  minimum_quantity REAL NOT NULL CHECK (typeof(minimum_quantity) IN ('real','integer') AND minimum_quantity>=0 AND minimum_quantity<=1.7976931348623157e308),
  PRIMARY KEY (warehouse_id, item_id),
  FOREIGN KEY (warehouse_id) REFERENCES warehouses (warehouse_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY (item_id) REFERENCES items (item_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

-- 需要グループと使用量基準 / Q54 Q55 Q57 Q58 Q72 P04 U03 U04
CREATE TABLE demand_groups (
  group_id INTEGER NOT NULL CHECK (group_id>0),
  name TEXT NOT NULL CHECK (length(trim(name))>0),
  calculation_unit TEXT CHECK (calculation_unit IS NULL OR (length(trim(calculation_unit))>0)),
  is_divisible INTEGER CHECK (is_divisible IS NULL OR (is_divisible IN (0,1))),
  daily_usage REAL CHECK (daily_usage IS NULL OR (typeof(daily_usage) IN ('real','integer') AND daily_usage>0 AND daily_usage<=1.7976931348623157e308)),
  source_text TEXT CHECK (source_text IS NULL OR (length(trim(source_text))>0)),
  version_or_date TEXT CHECK (version_or_date IS NULL OR (length(trim(version_or_date))>0)),
  conditions TEXT CHECK (conditions IS NULL OR (length(trim(conditions))>0)),
  PRIMARY KEY (group_id)
);

-- 品目の需要対応と換算 / Q50 Q54 Q55 Q73
CREATE TABLE item_conversions (
  item_id INTEGER NOT NULL CHECK (item_id>0),
  group_id INTEGER NOT NULL CHECK (group_id>0),
  factor_x100 INTEGER CHECK (factor_x100 IS NULL OR (typeof(factor_x100)='integer' AND factor_x100>=1)),
  source_text TEXT CHECK (source_text IS NULL OR (length(trim(source_text))>0)),
  version_or_date TEXT CHECK (version_or_date IS NULL OR (length(trim(version_or_date))>0)),
  conditions TEXT CHECK (conditions IS NULL OR (length(trim(conditions))>0)),
  PRIMARY KEY (item_id),
  FOREIGN KEY (item_id) REFERENCES items (item_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY (group_id) REFERENCES demand_groups (group_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

-- 入出庫履歴 / Q08 Q09 Q10 Q15 Q17 Q39 Q52
CREATE TABLE stock_movements (
  movement_id INTEGER NOT NULL CHECK (movement_id>0),
  stock_id INTEGER NOT NULL CHECK (stock_id>0),
  operator_id INTEGER NOT NULL CHECK (operator_id>0),
  operator_name TEXT NOT NULL CHECK (length(trim(operator_name))>0),
  kind TEXT NOT NULL CHECK (kind IN ('in','out')),
  quantity REAL NOT NULL CHECK (typeof(quantity) IN ('real','integer') AND quantity>0 AND quantity<=1.7976931348623157e308),
  registered_at TEXT NOT NULL CHECK (length(registered_at)=24 AND registered_at GLOB '????-??-??T??:??:??.???Z'),
  reason TEXT CHECK (reason IS NULL OR (length(trim(reason))>0)),
  merge_generation INTEGER NOT NULL CHECK (typeof(merge_generation)='integer' AND merge_generation>=0),
  state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active','cancelled')),
  cancelled_at TEXT CHECK (cancelled_at IS NULL OR (length(cancelled_at)=24 AND cancelled_at GLOB '????-??-??T??:??:??.???Z')),
  cancel_operator_id INTEGER,
  cancel_operator_name TEXT CHECK (cancel_operator_name IS NULL OR (length(trim(cancel_operator_name))>0)),
  PRIMARY KEY (movement_id),
  CHECK ((state='active' AND cancelled_at IS NULL AND cancel_operator_id IS NULL AND cancel_operator_name IS NULL) OR (state='cancelled' AND cancelled_at IS NOT NULL AND cancel_operator_id IS NOT NULL AND cancel_operator_name IS NOT NULL)),
  FOREIGN KEY (stock_id) REFERENCES stocks (stock_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY (operator_id) REFERENCES operators (operator_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY (cancel_operator_id) REFERENCES operators (operator_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

-- 削除と復元の記録 / Q30 Q31 P01
CREATE TABLE stock_state_events (
  event_id INTEGER NOT NULL CHECK (event_id>0),
  stock_id INTEGER NOT NULL CHECK (stock_id>0),
  action TEXT NOT NULL CHECK (action IN ('delete','restore')),
  operator_id INTEGER NOT NULL CHECK (operator_id>0),
  occurred_at TEXT NOT NULL CHECK (length(occurred_at)=24 AND occurred_at GLOB '????-??-??T??:??:??.???Z'),
  PRIMARY KEY (event_id),
  FOREIGN KEY (stock_id) REFERENCES stocks (stock_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY (operator_id) REFERENCES operators (operator_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

-- 使用期限変更履歴 / Q41 Q42 Q43
CREATE TABLE stock_expiry_changes (
  change_id INTEGER NOT NULL CHECK (change_id>0),
  stock_id INTEGER NOT NULL CHECK (stock_id>0),
  before_expiry_state TEXT NOT NULL CHECK (before_expiry_state IN ('dated','none','unconfirmed')),
  before_expiry_date TEXT CHECK (before_expiry_date IS NULL OR (length(before_expiry_date)=10 AND before_expiry_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')),
  after_expiry_state TEXT NOT NULL CHECK (after_expiry_state IN ('dated','none','unconfirmed')),
  after_expiry_date TEXT CHECK (after_expiry_date IS NULL OR (length(after_expiry_date)=10 AND after_expiry_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')),
  operator_id INTEGER NOT NULL CHECK (operator_id>0),
  changed_at TEXT NOT NULL CHECK (length(changed_at)=24 AND changed_at GLOB '????-??-??T??:??:??.???Z'),
  PRIMARY KEY (change_id),
  CHECK (((before_expiry_state='dated' AND before_expiry_date IS NOT NULL) OR (before_expiry_state IN ('none','unconfirmed') AND before_expiry_date IS NULL))),
  CHECK (((after_expiry_state='dated' AND after_expiry_date IS NOT NULL) OR (after_expiry_state IN ('none','unconfirmed') AND after_expiry_date IS NULL))),
  CHECK (before_expiry_state<>after_expiry_state OR before_expiry_date IS NOT after_expiry_date),
  FOREIGN KEY (stock_id) REFERENCES stocks (stock_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY (operator_id) REFERENCES operators (operator_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

-- 保存計算 / Q11 Q13 Q58 Q59 Q60 Q61 Q62 Q63 Q64 U05 U06
CREATE TABLE calculation_runs (
  run_id INTEGER NOT NULL CHECK (run_id>0),
  shelter_id INTEGER NOT NULL CHECK (shelter_id>0),
  shelter_name TEXT NOT NULL CHECK (length(trim(shelter_name))>0),
  target_people INTEGER NOT NULL CHECK (typeof(target_people)='integer' AND target_people>=1),
  target_days INTEGER NOT NULL CHECK (typeof(target_days)='integer' AND target_days>=1),
  base_date TEXT NOT NULL CHECK (length(base_date)=10 AND base_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  calculated_at TEXT NOT NULL CHECK (length(calculated_at)=24 AND calculated_at GLOB '????-??-??T??:??:??.???Z'),
  saved_at TEXT NOT NULL CHECK (length(saved_at)=24 AND saved_at GLOB '????-??-??T??:??:??.???Z'),
  formula_version TEXT NOT NULL CHECK (length(trim(formula_version))>0),
  setup_state TEXT NOT NULL CHECK (setup_state IN ('editing','complete')),
  result_state TEXT NOT NULL CHECK (result_state IN ('computed','partial','unavailable')),
  has_unknown_expiry INTEGER NOT NULL CHECK (has_unknown_expiry IN (0,1)),
  min_people INTEGER CHECK (min_people IS NULL OR (typeof(min_people)='integer' AND min_people>=0)),
  min_days INTEGER CHECK (min_days IS NULL OR (typeof(min_days)='integer' AND min_days>=0)),
  unavailable_reason TEXT CHECK (unavailable_reason IS NULL OR (length(trim(unavailable_reason))>0)),
  correction_of_run_id INTEGER,
  PRIMARY KEY (run_id),
  CHECK ((result_state='computed' AND min_people IS NOT NULL AND min_days IS NOT NULL AND unavailable_reason IS NULL) OR (result_state IN ('partial','unavailable') AND min_people IS NULL AND min_days IS NULL AND unavailable_reason IS NOT NULL)),
  CHECK (correction_of_run_id IS NULL OR correction_of_run_id<run_id),
  CHECK (saved_at>=calculated_at),
  FOREIGN KEY (shelter_id) REFERENCES shelters (shelter_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY (correction_of_run_id) REFERENCES calculation_runs (run_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

-- 需要別結果と基準の写し / Q54 Q58 Q59 Q63 Q69 Q72
CREATE TABLE calculation_group_results (
  run_id INTEGER NOT NULL CHECK (run_id>0),
  group_id INTEGER NOT NULL CHECK (group_id>0),
  group_name TEXT NOT NULL CHECK (length(trim(group_name))>0),
  calculation_unit TEXT CHECK (calculation_unit IS NULL OR (length(trim(calculation_unit))>0)),
  is_divisible INTEGER CHECK (is_divisible IS NULL OR (is_divisible IN (0,1))),
  daily_usage REAL CHECK (daily_usage IS NULL OR (typeof(daily_usage) IN ('real','integer') AND daily_usage>0 AND daily_usage<=1.7976931348623157e308)),
  source_text TEXT CHECK (source_text IS NULL OR (length(trim(source_text))>0)),
  version_or_date TEXT CHECK (version_or_date IS NULL OR (length(trim(version_or_date))>0)),
  conditions TEXT CHECK (conditions IS NULL OR (length(trim(conditions))>0)),
  result_state TEXT NOT NULL CHECK (result_state IN ('computed','unavailable')),
  unavailable_reason TEXT CHECK (unavailable_reason IS NULL OR (length(trim(unavailable_reason))>0)),
  reference_quantity REAL CHECK (reference_quantity IS NULL OR (typeof(reference_quantity) IN ('real','integer') AND reference_quantity>=0 AND reference_quantity<=1.7976931348623157e308)),
  required_quantity REAL CHECK (required_quantity IS NULL OR (typeof(required_quantity) IN ('real','integer') AND required_quantity>=0 AND required_quantity<=1.7976931348623157e308)),
  included_quantity REAL CHECK (included_quantity IS NULL OR (typeof(included_quantity) IN ('real','integer') AND included_quantity>=0 AND included_quantity<=1.7976931348623157e308)),
  covered_quantity REAL CHECK (covered_quantity IS NULL OR (typeof(covered_quantity) IN ('real','integer') AND covered_quantity>=0 AND covered_quantity<=1.7976931348623157e308)),
  shortage_quantity REAL CHECK (shortage_quantity IS NULL OR (typeof(shortage_quantity) IN ('real','integer') AND shortage_quantity>=0 AND shortage_quantity<=1.7976931348623157e308)),
  coverage_rate REAL CHECK (coverage_rate IS NULL OR (typeof(coverage_rate) IN ('real','integer') AND coverage_rate>=0 AND coverage_rate<=1.7976931348623157e308)),
  people INTEGER CHECK (people IS NULL OR (typeof(people)='integer' AND people>=0)),
  days INTEGER CHECK (days IS NULL OR (typeof(days)='integer' AND days>=0)),
  has_unknown_expiry INTEGER NOT NULL CHECK (has_unknown_expiry IN (0,1)),
  limits_people INTEGER NOT NULL CHECK (limits_people IN (0,1)),
  limits_days INTEGER NOT NULL CHECK (limits_days IN (0,1)),
  PRIMARY KEY (run_id, group_id),
  CHECK ((result_state='computed' AND unavailable_reason IS NULL AND required_quantity IS NOT NULL AND included_quantity IS NOT NULL AND covered_quantity IS NOT NULL AND shortage_quantity IS NOT NULL AND coverage_rate IS NOT NULL AND people IS NOT NULL AND days IS NOT NULL) OR (result_state='unavailable' AND unavailable_reason IS NOT NULL AND required_quantity IS NULL AND included_quantity IS NULL AND covered_quantity IS NULL AND shortage_quantity IS NULL AND coverage_rate IS NULL AND people IS NULL AND days IS NULL)),
  FOREIGN KEY (run_id) REFERENCES calculation_runs (run_id) ON UPDATE RESTRICT ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (group_id) REFERENCES demand_groups (group_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

-- 品目と換算の写し / Q50 Q54 Q63 Q73
CREATE TABLE calculation_item_snapshots (
  run_id INTEGER NOT NULL CHECK (run_id>0),
  item_id INTEGER NOT NULL CHECK (item_id>0),
  group_id INTEGER NOT NULL CHECK (group_id>0),
  item_name TEXT NOT NULL CHECK (length(trim(item_name))>0),
  quantity_unit TEXT NOT NULL CHECK (length(trim(quantity_unit))>0),
  is_divisible INTEGER NOT NULL CHECK (is_divisible IN (0,1)),
  registration_state TEXT NOT NULL CHECK (registration_state IN ('active','closed')),
  factor_x100 INTEGER CHECK (factor_x100 IS NULL OR (typeof(factor_x100)='integer' AND factor_x100>=1)),
  source_text TEXT CHECK (source_text IS NULL OR (length(trim(source_text))>0)),
  version_or_date TEXT CHECK (version_or_date IS NULL OR (length(trim(version_or_date))>0)),
  conditions TEXT CHECK (conditions IS NULL OR (length(trim(conditions))>0)),
  PRIMARY KEY (run_id, item_id),
  FOREIGN KEY (run_id, group_id) REFERENCES calculation_group_results (run_id, group_id) ON UPDATE RESTRICT ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (item_id) REFERENCES items (item_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

-- 倉庫区分の写し / Q63 U05
CREATE TABLE calculation_warehouse_snapshots (
  run_id INTEGER NOT NULL CHECK (run_id>0),
  warehouse_id INTEGER NOT NULL CHECK (warehouse_id>0),
  warehouse_name TEXT NOT NULL CHECK (length(trim(warehouse_name))>0),
  allocation_mode TEXT CHECK (allocation_mode IS NULL OR (allocation_mode IN ('dedicated','shared'))),
  PRIMARY KEY (run_id, warehouse_id),
  FOREIGN KEY (run_id) REFERENCES calculation_runs (run_id) ON UPDATE RESTRICT ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (warehouse_id) REFERENCES warehouses (warehouse_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

-- 倉庫対応先の写し / U05 Q63
CREATE TABLE calculation_warehouse_links (
  run_id INTEGER NOT NULL CHECK (run_id>0),
  warehouse_id INTEGER NOT NULL CHECK (warehouse_id>0),
  shelter_id INTEGER NOT NULL CHECK (shelter_id>0),
  shelter_name TEXT NOT NULL CHECK (length(trim(shelter_name))>0),
  PRIMARY KEY (run_id, warehouse_id, shelter_id),
  FOREIGN KEY (run_id, warehouse_id) REFERENCES calculation_warehouse_snapshots (run_id, warehouse_id) ON UPDATE RESTRICT ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (shelter_id) REFERENCES shelters (shelter_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

-- 算入根拠の写し / Q18 Q44 Q63 Q65 Q67 U05
CREATE TABLE calculation_stock_snapshots (
  run_id INTEGER NOT NULL CHECK (run_id>0),
  stock_id INTEGER NOT NULL CHECK (stock_id>0),
  item_id INTEGER NOT NULL CHECK (item_id>0),
  warehouse_id INTEGER NOT NULL CHECK (warehouse_id>0),
  stock_quantity REAL NOT NULL CHECK (typeof(stock_quantity) IN ('real','integer') AND stock_quantity>=0 AND stock_quantity<=1.7976931348623157e308),
  allocated_total REAL NOT NULL CHECK (typeof(allocated_total) IN ('real','integer') AND allocated_total>=0 AND allocated_total<=1.7976931348623157e308),
  selected_allocation REAL NOT NULL CHECK (typeof(selected_allocation) IN ('real','integer') AND selected_allocation>=0 AND selected_allocation<=1.7976931348623157e308),
  expiry_state TEXT NOT NULL CHECK (expiry_state IN ('dated','none','unconfirmed')),
  expiry_date TEXT CHECK (expiry_date IS NULL OR (length(expiry_date)=10 AND expiry_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')),
  included_quantity REAL NOT NULL CHECK (typeof(included_quantity) IN ('real','integer') AND included_quantity>=0 AND included_quantity<=1.7976931348623157e308),
  converted_quantity REAL CHECK (converted_quantity IS NULL OR (typeof(converted_quantity) IN ('real','integer') AND converted_quantity>=0 AND converted_quantity<=1.7976931348623157e308)),
  selection_reason TEXT NOT NULL CHECK (selection_reason IN ('dedicated','shared','unallocated','expired','unresolved')),
  unknown_expiry_warning INTEGER NOT NULL CHECK (unknown_expiry_warning IN (0,1)),
  expires_in_period INTEGER NOT NULL CHECK (expires_in_period IN (0,1)),
  PRIMARY KEY (run_id, stock_id),
  CHECK (((expiry_state='dated' AND expiry_date IS NOT NULL) OR (expiry_state IN ('none','unconfirmed') AND expiry_date IS NULL))),
  CHECK (allocated_total<=stock_quantity),
  CHECK (selected_allocation<=allocated_total),
  CHECK (included_quantity<=stock_quantity),
  CHECK (selection_reason NOT IN ('unallocated','expired','unresolved') OR included_quantity=0),
  FOREIGN KEY (run_id, item_id) REFERENCES calculation_item_snapshots (run_id, item_id) ON UPDATE RESTRICT ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (run_id, warehouse_id) REFERENCES calculation_warehouse_snapshots (run_id, warehouse_id) ON UPDATE RESTRICT ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (stock_id) REFERENCES stocks (stock_id) ON UPDATE RESTRICT ON DELETE RESTRICT
);
-- 有効在庫の倉庫品目別集計
CREATE INDEX ix_stocks_1 ON stocks (warehouse_id,item_id) WHERE state='active';
-- 品目使用・終了確認
CREATE INDEX ix_stocks_2 ON stocks (item_id);
-- 統合元参照
CREATE INDEX ix_stocks_3 ON stocks (merged_into_stock_id);
-- 統合担当者参照
CREATE INDEX ix_stocks_4 ON stocks (merged_by);
-- 期限警告一覧
CREATE INDEX ix_stocks_5 ON stocks (expiry_date) WHERE state='active' AND expiry_state='dated';
-- 倉庫から対応・専用件数確認
CREATE INDEX ix_shelter_warehouses_1 ON shelter_warehouses (warehouse_id,shelter_id);
-- 避難所の共有割当表示
CREATE INDEX ix_stock_allocations_1 ON stock_allocations (shelter_id,stock_id);
-- 品目別基準参照
CREATE INDEX ix_stock_thresholds_1 ON stock_thresholds (item_id);
-- 需要グループの品目一覧
CREATE INDEX ix_item_conversions_1 ON item_conversions (group_id,item_id);
-- 在庫別取引履歴
CREATE INDEX ix_stock_movements_1 ON stock_movements (stock_id,registered_at);
-- 担当者FK確認
CREATE INDEX ix_stock_movements_2 ON stock_movements (operator_id);
-- 取消担当者FK確認
CREATE INDEX ix_stock_movements_3 ON stock_movements (cancel_operator_id);
-- 復元履歴
CREATE INDEX ix_stock_state_events_1 ON stock_state_events (stock_id,occurred_at);
-- 担当者FK確認
CREATE INDEX ix_stock_state_events_2 ON stock_state_events (operator_id);
-- 期限変更履歴
CREATE INDEX ix_stock_expiry_changes_1 ON stock_expiry_changes (stock_id,changed_at);
-- 担当者FK確認
CREATE INDEX ix_stock_expiry_changes_2 ON stock_expiry_changes (operator_id);
-- 避難所日時絞込み
CREATE INDEX ix_calculation_runs_1 ON calculation_runs (shelter_id,calculated_at);
-- 状態日時絞込み
CREATE INDEX ix_calculation_runs_2 ON calculation_runs (result_state,calculated_at);
-- 訂正先検索
CREATE INDEX ix_calculation_runs_3 ON calculation_runs (correction_of_run_id);
-- 元需要参照
CREATE INDEX ix_calculation_group_results_1 ON calculation_group_results (group_id);
-- 需要内訳FK
CREATE INDEX ix_calculation_item_snapshots_1 ON calculation_item_snapshots (run_id,group_id);
-- 元品目参照
CREATE INDEX ix_calculation_item_snapshots_2 ON calculation_item_snapshots (item_id);
-- 元倉庫参照
CREATE INDEX ix_calculation_warehouse_snapshots_1 ON calculation_warehouse_snapshots (warehouse_id);
-- 元対応先参照
CREATE INDEX ix_calculation_warehouse_links_1 ON calculation_warehouse_links (shelter_id);
-- 品目根拠FK
CREATE INDEX ix_calculation_stock_snapshots_1 ON calculation_stock_snapshots (run_id,item_id);
-- 倉庫根拠FK
CREATE INDEX ix_calculation_stock_snapshots_2 ON calculation_stock_snapshots (run_id,warehouse_id);
-- 元在庫参照
CREATE INDEX ix_calculation_stock_snapshots_3 ON calculation_stock_snapshots (stock_id);
-- 保存結果・操作履歴の変更削除禁止
CREATE TRIGGER tr_calculation_runs_update BEFORE UPDATE ON calculation_runs BEGIN
  SELECT RAISE(ABORT,'immutable_record');
END;
-- 保存結果・操作履歴の変更削除禁止
CREATE TRIGGER tr_calculation_runs_delete BEFORE DELETE ON calculation_runs BEGIN
  SELECT RAISE(ABORT,'immutable_record');
END;
-- 保存結果・操作履歴の変更削除禁止
CREATE TRIGGER tr_calculation_group_results_update BEFORE UPDATE ON calculation_group_results BEGIN
  SELECT RAISE(ABORT,'immutable_record');
END;
-- 保存結果・操作履歴の変更削除禁止
CREATE TRIGGER tr_calculation_group_results_delete BEFORE DELETE ON calculation_group_results BEGIN
  SELECT RAISE(ABORT,'immutable_record');
END;
-- 保存結果・操作履歴の変更削除禁止
CREATE TRIGGER tr_calculation_item_snapshots_update BEFORE UPDATE ON calculation_item_snapshots BEGIN
  SELECT RAISE(ABORT,'immutable_record');
END;
-- 保存結果・操作履歴の変更削除禁止
CREATE TRIGGER tr_calculation_item_snapshots_delete BEFORE DELETE ON calculation_item_snapshots BEGIN
  SELECT RAISE(ABORT,'immutable_record');
END;
-- 保存結果・操作履歴の変更削除禁止
CREATE TRIGGER tr_calculation_warehouse_snapshots_update BEFORE UPDATE ON calculation_warehouse_snapshots BEGIN
  SELECT RAISE(ABORT,'immutable_record');
END;
-- 保存結果・操作履歴の変更削除禁止
CREATE TRIGGER tr_calculation_warehouse_snapshots_delete BEFORE DELETE ON calculation_warehouse_snapshots BEGIN
  SELECT RAISE(ABORT,'immutable_record');
END;
-- 保存結果・操作履歴の変更削除禁止
CREATE TRIGGER tr_calculation_warehouse_links_update BEFORE UPDATE ON calculation_warehouse_links BEGIN
  SELECT RAISE(ABORT,'immutable_record');
END;
-- 保存結果・操作履歴の変更削除禁止
CREATE TRIGGER tr_calculation_warehouse_links_delete BEFORE DELETE ON calculation_warehouse_links BEGIN
  SELECT RAISE(ABORT,'immutable_record');
END;
-- 保存結果・操作履歴の変更削除禁止
CREATE TRIGGER tr_calculation_stock_snapshots_update BEFORE UPDATE ON calculation_stock_snapshots BEGIN
  SELECT RAISE(ABORT,'immutable_record');
END;
-- 保存結果・操作履歴の変更削除禁止
CREATE TRIGGER tr_calculation_stock_snapshots_delete BEFORE DELETE ON calculation_stock_snapshots BEGIN
  SELECT RAISE(ABORT,'immutable_record');
END;
-- 保存結果・操作履歴の変更削除禁止
CREATE TRIGGER tr_stock_state_events_update BEFORE UPDATE ON stock_state_events BEGIN
  SELECT RAISE(ABORT,'immutable_record');
END;
-- 保存結果・操作履歴の変更削除禁止
CREATE TRIGGER tr_stock_state_events_delete BEFORE DELETE ON stock_state_events BEGIN
  SELECT RAISE(ABORT,'immutable_record');
END;
-- 保存結果・操作履歴の変更削除禁止
CREATE TRIGGER tr_stock_expiry_changes_update BEFORE UPDATE ON stock_expiry_changes BEGIN
  SELECT RAISE(ABORT,'immutable_record');
END;
-- 保存結果・操作履歴の変更削除禁止
CREATE TRIGGER tr_stock_expiry_changes_delete BEFORE DELETE ON stock_expiry_changes BEGIN
  SELECT RAISE(ABORT,'immutable_record');
END;
-- ヘッダー保存後の子行追加を禁止。ヘッダーは最後に作成
CREATE TRIGGER tr_calculation_group_results_sealed BEFORE INSERT ON calculation_group_results WHEN EXISTS(SELECT 1 FROM calculation_runs WHERE run_id=NEW.run_id) BEGIN
  SELECT RAISE(ABORT,'sealed_calculation');
END;
-- ヘッダー保存後の子行追加を禁止。ヘッダーは最後に作成
CREATE TRIGGER tr_calculation_item_snapshots_sealed BEFORE INSERT ON calculation_item_snapshots WHEN EXISTS(SELECT 1 FROM calculation_runs WHERE run_id=NEW.run_id) BEGIN
  SELECT RAISE(ABORT,'sealed_calculation');
END;
-- ヘッダー保存後の子行追加を禁止。ヘッダーは最後に作成
CREATE TRIGGER tr_calculation_warehouse_snapshots_sealed BEFORE INSERT ON calculation_warehouse_snapshots WHEN EXISTS(SELECT 1 FROM calculation_runs WHERE run_id=NEW.run_id) BEGIN
  SELECT RAISE(ABORT,'sealed_calculation');
END;
-- ヘッダー保存後の子行追加を禁止。ヘッダーは最後に作成
CREATE TRIGGER tr_calculation_warehouse_links_sealed BEFORE INSERT ON calculation_warehouse_links WHEN EXISTS(SELECT 1 FROM calculation_runs WHERE run_id=NEW.run_id) BEGIN
  SELECT RAISE(ABORT,'sealed_calculation');
END;
-- ヘッダー保存後の子行追加を禁止。ヘッダーは最後に作成
CREATE TRIGGER tr_calculation_stock_snapshots_sealed BEFORE INSERT ON calculation_stock_snapshots WHEN EXISTS(SELECT 1 FROM calculation_runs WHERE run_id=NEW.run_id) BEGIN
  SELECT RAISE(ABORT,'sealed_calculation');
END;
-- 訂正元は既に保存された結果のみ
CREATE TRIGGER tr_run_correction BEFORE INSERT ON calculation_runs WHEN NEW.correction_of_run_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM calculation_runs WHERE run_id=NEW.correction_of_run_id) BEGIN
  SELECT RAISE(ABORT,'invalid_correction');
END;
-- 空の保存を拒否
CREATE TRIGGER tr_run_children BEFORE INSERT ON calculation_runs WHEN NOT EXISTS(SELECT 1 FROM calculation_group_results WHERE run_id=NEW.run_id) BEGIN
  SELECT RAISE(ABORT,'missing_group_results');
END;
-- 取引を物理削除しない
CREATE TRIGGER tr_movement_delete BEFORE DELETE ON stock_movements BEGIN
  SELECT RAISE(ABORT,'retain_movement');
END;
-- 登録情報の変更と二重取消を禁止
CREATE TRIGGER tr_movement_update BEFORE UPDATE ON stock_movements WHEN NOT (OLD.state='active' AND NEW.state='cancelled' AND NEW.movement_id IS OLD.movement_id AND NEW.stock_id IS OLD.stock_id AND NEW.operator_id IS OLD.operator_id AND NEW.operator_name IS OLD.operator_name AND NEW.kind IS OLD.kind AND NEW.quantity IS OLD.quantity AND NEW.registered_at IS OLD.registered_at AND NEW.reason IS OLD.reason AND NEW.merge_generation IS OLD.merge_generation) BEGIN
  SELECT RAISE(ABORT,'movement_cancel_only');
END;
-- 統合元の自己参照・識別情報を固定
CREATE TRIGGER tr_merged_frozen BEFORE UPDATE ON stocks WHEN OLD.state='merged' BEGIN
  SELECT RAISE(ABORT,'merged_stock_frozen');
END;
-- ID参照を維持。アプリに物理削除機能なし
CREATE TRIGGER tr_warehouses_retain BEFORE DELETE ON warehouses BEGIN
  SELECT RAISE(ABORT,'retain_master_or_stock');
END;
-- ID参照を維持。アプリに物理削除機能なし
CREATE TRIGGER tr_items_retain BEFORE DELETE ON items BEGIN
  SELECT RAISE(ABORT,'retain_master_or_stock');
END;
-- ID参照を維持。アプリに物理削除機能なし
CREATE TRIGGER tr_stocks_retain BEFORE DELETE ON stocks BEGIN
  SELECT RAISE(ABORT,'retain_master_or_stock');
END;
-- ID参照を維持。アプリに物理削除機能なし
CREATE TRIGGER tr_shelters_retain BEFORE DELETE ON shelters BEGIN
  SELECT RAISE(ABORT,'retain_master_or_stock');
END;
-- ID参照を維持。アプリに物理削除機能なし
CREATE TRIGGER tr_operators_retain BEFORE DELETE ON operators BEGIN
  SELECT RAISE(ABORT,'retain_master_or_stock');
END;
-- ID参照を維持。アプリに物理削除機能なし
CREATE TRIGGER tr_demand_groups_retain BEFORE DELETE ON demand_groups BEGIN
  SELECT RAISE(ABORT,'retain_master_or_stock');
END;
-- 終了品目の再有効化禁止
CREATE TRIGGER tr_items_closed BEFORE UPDATE ON items WHEN OLD.registration_state='closed' AND NEW.registration_state<>'closed' BEGIN
  SELECT RAISE(ABORT,'closed_item_cannot_reopen');
END;
-- 既存在庫の単位不変
CREATE TRIGGER tr_item_unit BEFORE UPDATE ON items WHEN NEW.quantity_unit IS NOT OLD.quantity_unit AND EXISTS(SELECT 1 FROM stocks WHERE item_id=OLD.item_id) BEGIN
  SELECT RAISE(ABORT,'unit_has_stock');
END;
COMMIT;
PRAGMA foreign_key_check;
PRAGMA integrity_check;
