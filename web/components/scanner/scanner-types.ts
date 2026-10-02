// Shape dữ liệu hợp đồng cho màn M3 (docs/ui-api-contract.md §2 watchlist, §5 daily pipeline rev 3).
// §5 rev 3: worker per-coin, enqueue ngay khi coin xong, job KHÔNG BAO GIỜ tự
// thực thi — kết quả chỉ mang kế hoạch (plan) + approval_id, không có
// executed/order_id (bất biến §5: mọi lệnh chỉ đi qua màn Duyệt lệnh).

export interface WatchlistSymbol {
  symbol: string;
  added_at: string;
}

export interface WatchlistResponse {
  generated_at: string;
  symbols: WatchlistSymbol[];
  /** Server khôi phục từ config default khi file state hỏng (contract §2). */
  warning?: string;
}

export type DailyJobMode = "live" | "mock";

/** Chi tiết kế hoạch của một coin (đủ cho màn Duyệt lệnh — contract §5). */
export interface DailyPlan {
  side: string;
  quantity: number;
  price_est: number;
  cost: number;
  ccxt_symbol: string;
  market: string;
  leverage: number;
  mode_at_plan: string;
  plan_reason: string | null;
  /** Giá cắt lỗ/chốt lời đính kèm (ATR-derived, rev 5) — null khi ATR thiếu. */
  stop_loss?: number | null;
  take_profit?: number | null;
}

export interface DailyResultItem {
  ticker: string;
  /** 5-tier hoặc "REVIEW"; coin fail giữa pipeline → null. */
  signal: string | null;
  /** Lý do không trade / "awaiting approval" / "<ExceptionType>: <message>". */
  reason: string | null;
  plan: DailyPlan | null;
  /** Tham chiếu GET /api/approvals — null khi kế hoạch không trade được. */
  approval_id: string | null;
  /** Lỗi hệ thống (khác reason nghiệp vụ). */
  error: string | null;
  /** Chỉ job mode:"mock" — "replay:<path>" hoặc "synthetic". */
  mock_source?: string;
  /** "crypto" | "stock" — stock chỉ advisory, không sinh lệnh (rev 4). */
  asset_type?: string;
}

export type DailyJobStatus = "queued" | "running" | "completed" | "failed";

/** Response 202 của POST /api/daily (contract §5). */
export interface DailyJobStart {
  job_id: string;
  status: DailyJobStatus;
  mode: DailyJobMode;
  tickers: string[];
  created_at: string;
  detail_url: string;
}

/** Response 200 của GET /api/daily/{job_id} (contract §5 rev 3+4). */
export interface DailyJobStatusResponse {
  generated_at: string;
  job_id: string;
  status: DailyJobStatus;
  mode: DailyJobMode;
  created_at: string;
  finished_at: string | null;
  tickers: string[];
  /** Job auto (rev 4): sàng lọc thị trường gắn trên payload. */
  asset_types?: Record<string, string>;
  screening?: ScreeningInfo | null;
  results: DailyResultItem[];
}

export type ApiErrorInfo = {
  status: number;
  code: string;
  message: string;
};

/** Một ứng viên sau khi server sàng lọc thị trường (auto-scan, contract §5 rev 4).
 *  Metrics theo chuẩn screener thực chiến: RSI(14), ATR%, khoảng cách đỉnh 52 tuần,
 *  RVOL, breakout 20 phiên kèm khối lượng, dollar-volume trung bình 20 phiên. */
export interface ScreeningCandidate {
  ticker: string;
  asset_type: "crypto" | "stock";
  score: number;
  last_close: number;
  momentum_pct: number;
  trend_pct: number;
  volume_ratio: number;
  rsi14: number | null;
  atr_pct: number | null;
  dist_52w_pct: number;
  breakout: boolean;
  avg_dollar_volume: number;
  reasons: string[];
}

/** Khối screening gắn trên job mode auto (contract §5 rev 4). */
export interface ScreeningInfo {
  universe_count: number;
  universe_crypto: number;
  universe_stock: number;
  candidates: ScreeningCandidate[];
  /** Chỉ job mock — sàng cố định, không đụng network. */
  mock?: boolean;
}
