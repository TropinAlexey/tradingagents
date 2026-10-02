// Shape của GET/POST /api/autoloop, POST /api/autoloop/run-now, POST /api/halt,
// POST /api/halt/reset (server/autoloop.py) — mirror hợp đồng, không thêm gì.
// Nhãn tiếng Việt của 4 cổng an toàn sống ở đây vì ánh xạ 1-1 theo key máy chủ trả.

export type AutoloopGates = {
  auto_confirm_config: boolean;
  auto_confirm_env: boolean;
  exec_live_config: boolean;
  exec_live_env: boolean;
  all_open: boolean;
};

export type AutoloopGateKey = Exclude<keyof AutoloopGates, "all_open">;

export type AutoloopLastCycleResult = {
  ticker: string;
  signal: string | null;
  executed: boolean;
  order_id: string | null;
  reason: string | null;
  stop_loss: number | null;
  take_profit: number | null;
};

export type AutoloopLastCycle = {
  started_at: string;
  finished_at: string | null;
  status: string;
  reason: string | null;
  error: string | null;
  candidates: string[];
  results: AutoloopLastCycleResult[];
  universe?: { crypto: number; stock: number };
};

export type AutoloopPayload = {
  generated_at: string;
  enabled: boolean;
  interval_minutes: number;
  running_cycle: boolean;
  gates: AutoloopGates;
  last_cycle: AutoloopLastCycle | null;
};

export type AutoloopRunNowResponse = {
  generated_at: string;
  status: string;
};

export type AutoloopHaltResponse = {
  generated_at: string;
  halted: boolean;
};

// Ràng buộc giống server/autoloop.py (MIN/MAX/DEFAULT_INTERVAL_MINUTES).
export const AUTOLOOP_MIN_INTERVAL = 15;
export const AUTOLOOP_MAX_INTERVAL = 1440;
export const AUTOLOOP_DEFAULT_INTERVAL = 1440;

/** Thứ tự + nhãn hiển thị của 4 cổng an toàn (server/autoloop.py gates()). */
export const AUTOLOOP_GATE_ROWS: readonly { key: AutoloopGateKey; label: string }[] = [
  { key: "auto_confirm_config", label: "Auto-confirm trong config" },
  { key: "auto_confirm_env", label: "Biến môi trường TRADINGAGENTS_EXEC_AUTO_CONFIRM" },
  { key: "exec_live_config", label: "exec_live trong config" },
  { key: "exec_live_env", label: "Biến môi trường TRADINGAGENTS_EXEC_LIVE" },
];
