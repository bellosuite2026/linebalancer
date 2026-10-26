export type Role = "owner" | "admin" | "methodes" | "chef_ligne" | "lecteur";

export interface Org {
  id: string; name: string; country: string; role: Role; created_at?: string;
  subscription?: { plan_code: string; status: string; trial_ends_at: string | null; current_period_end: string | null } | null;
}
export interface Plan { code: string; name: string; price_tnd_month: number | null; max_lines: number; max_users: number; max_operations: number; cpsat: boolean }
export interface OrgDetail extends Org {
  plan: { plan_code: string; status: string; trial_ends_at: string | null; current_period_end: string | null; plan: Plan } | null;
  members: { user_id: string; role: Role; created_at: string }[];
}
export interface Line { id: string; org_id: string; name: string; product: string; target_cycle_time: number | null; created_at: string }

export interface Operation { id: string; name: string; duration: number; predecessors: string[]; machine_type: string; required_skills: string[]; section: string; optional: boolean; task_type: string }
export interface Workstation { id: string; name: string; machine_type: string; available: boolean; max_workers: number; section: string }
export interface Worker { id: string; name: string; skills: string[]; efficiency: number; assigned_station: string | null; available: boolean }
export interface Problem { name: string; target_cycle_time: number; operations: Operation[]; workstations: Workstation[]; workers: Worker[]; max_stations?: number | null }

export interface Issue { code: string; severity: string; message: string; suggestion: string }
export interface Precheck { feasible: boolean; issues: Issue[]; validation_errors: string[] }

export interface StationDetail {
  station: number; total_time: number; load_pct: number; operations: string[]; workers: string[];
  workstation?: string; workstations?: string[]; parallel?: number; machine_types?: string[]; sections?: string[];
  shares?: Record<string, number>; worker_time?: number; worker_efficiency?: number;
}
export interface Result {
  success: boolean; compliant: boolean; status: string; solver: string; solve_time_seconds: number;
  target_cycle_time: number; stations_used: number; actual_cycle_time: number; efficiency: number;
  balance_delay: number; smoothness_index: number; operators: number; station_details: StationDetail[];
  warnings: string[]; error_message: string; violations: Issue[];
}
export interface MinCycle { found: boolean; min_cycle_time: number | null; result: Result | null }

export interface Run {
  id: string; org_id: string; problem_id: string | null; kind: "balance" | "min_cycle"; solver: string;
  status: "queued" | "running" | "done" | "failed"; success: boolean | null; compliant: boolean | null;
  stations_used: number | null; actual_cycle_time: number | null; efficiency: number | null; min_cycle_time: number | null;
  error: string; created_at: string; started_at: string | null; finished_at: string | null;
  params: Record<string, unknown>; result?: Result | MinCycle | null;
}
export interface ProblemRow { id: string; name: string; target_cycle_time: number; operations_count: number; line_id: string | null; created_at: string; payload?: Problem }
