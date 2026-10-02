"use client";

// Card chạy quét của màn M3: POST /api/daily → poll GET /api/daily/{job_id}
// mỗi 3 giây đến khi terminal (contract §5). Job treo > 15 phút → badge
// "Đang treo" kèm gợi ý. Dòng tiền lệnh luôn có dấu +/− và nhãn chữ.
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Loader2, Play, ScanSearch, TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ApiHttpError, scannerApi, toApiHttpError } from "./scanner-api";
import {
  cashFlowLabel,
  elapsedLabel,
  formatCashFlow,
  formatQty,
  formatUsd,
  sideLabel,
} from "./scanner-format";
import type {
  DailyJobStart,
  DailyJobStatus,
  DailyJobStatusResponse,
  DailyResultItem,
  ScreeningInfo,
} from "./scanner-types";

type Phase = "idle" | "starting" | "running" | "error";
type ScanKind = "watchlist" | "auto";

const POLL_INTERVAL_MS = 3_000;
const STUCK_AFTER_MS = 15 * 60_000;

const STATUS_VI: Record<DailyJobStatus, string> = {
  queued: "Đang chờ",
  running: "Đang chạy",
  completed: "Hoàn tất",
  failed: "Thất bại",
};

const SIGNAL_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  Buy: "default",
  Overweight: "secondary",
  Hold: "outline",
  Underweight: "destructive",
  Sell: "destructive",
};

function ResultRow({ item }: { item: DailyResultItem }) {
  const plan = item.plan;
  return (
    <tr className="align-top">
      <td className="py-2 pr-3 font-mono font-medium">
        {item.ticker}
        {item.mock_source ? (
          <Badge variant="outline" className="ml-2 align-middle text-xs">
            Mock
          </Badge>
        ) : null}
        {item.asset_type === "stock" ? (
          <Badge variant="secondary" className="ml-2 align-middle text-xs">
            Cổ phiếu
          </Badge>
        ) : null}
      </td>
      <td className="py-2 pr-3">
        {item.signal ? (
          <Badge variant={SIGNAL_VARIANT[item.signal] ?? "outline"}>
            {item.signal}
          </Badge>
        ) : (
          "—"
        )}
      </td>
      <td className="py-2 pr-3">
        {plan ? (
          <span className="whitespace-nowrap">
            {sideLabel(plan.side)} · {formatQty(plan.quantity, item.ticker)} @{" "}
            {formatUsd(plan.price_est)}
          </span>
        ) : (
          "—"
        )}
      </td>
      <td className="py-2 pr-3">
        {plan ? (
          <span className="whitespace-nowrap">
            {formatCashFlow(plan.side, plan.cost)}{" "}
            <span className="text-xs text-muted-foreground">
              ({cashFlowLabel(plan.side)})
            </span>
          </span>
        ) : (
          "—"
        )}
      </td>
      <td className="max-w-xs py-2 pr-3">
        {/* Job UI không bao giờ tự thực thi (bất biến §5) — cột này chỉ mang
            lý do nghiệp vụ hoặc lỗi hệ thống của coin. */}
        <span className="line-clamp-2" title={item.error ?? item.reason ?? undefined}>
          {item.error ?? item.reason ?? "—"}
        </span>
      </td>
      <td className="py-2">
        {item.approval_id ? (
          <Link
            href="/approvals"
            className="min-touch inline-flex items-center text-sm underline underline-offset-4"
          >
            Xem hàng duyệt
          </Link>
        ) : (
          "—"
        )}
      </td>
    </tr>
  );
}

export function ScanPanel({ symbolsCount }: { symbolsCount: number }) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [kind, setKind] = useState<ScanKind>("watchlist");
  const [start, setStart] = useState<DailyJobStart | null>(null);
  const [job, setJob] = useState<DailyJobStatusResponse | null>(null);
  const [error, setError] = useState<ApiHttpError | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const jobId = job?.job_id ?? start?.job_id ?? null;
  const createdAt = job?.created_at ?? start?.created_at ?? null;
  const status: DailyJobStatus | null = job?.status ?? start?.status ?? null;
  const isTerminal = status === "completed" || status === "failed";

  // Đồng hồ hiển thị thời lượng — chỉ chạy khi đang poll.
  useEffect(() => {
    if (phase !== "running") return;
    const id = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(id);
  }, [phase]);

  // Poll GET /api/daily/{job_id} mỗi 3 giây đến khi terminal (contract §5).
  useEffect(() => {
    if (phase !== "running" || !jobId) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const next = await scannerApi.dailyJob(jobId);
        if (cancelled) return;
        setJob(next);
        if (next.status === "completed" || next.status === "failed") {
          setPhase("idle");
        }
      } catch (err) {
        if (cancelled) return;
        setError(toApiHttpError(err));
        setPhase("error");
      }
    };
    const id = setInterval(() => void tick(), POLL_INTERVAL_MS);
    void tick();
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [phase, jobId]);

  const startScan = useCallback(async (scanKind: ScanKind) => {
    setPhase("starting");
    setKind(scanKind);
    setError(null);
    setStart(null);
    setJob(null);
    try {
      const res =
        scanKind === "auto"
          ? await scannerApi.startAutoDaily(5)
          : await scannerApi.startDaily();
      setStart(res);
      setPhase("running");
    } catch (err) {
      setError(toApiHttpError(err));
      setPhase("error");
    }
  }, []);

  const resumePolling = useCallback(() => {
    setError(null);
    setPhase(jobId && status && !isTerminal ? "running" : "idle");
  }, [jobId, status, isTerminal]);

  const busy = phase === "starting" || phase === "running";
  const isStuck =
    phase === "running" &&
    createdAt !== null &&
    now - Date.parse(createdAt) > STUCK_AFTER_MS;
  const screening: ScreeningInfo | null | undefined = job?.screening;
  const screeningEmpty =
    screening != null && screening.candidates.length === 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Quét pipeline</CardTitle>
        <CardDescription>
          {kind === "auto" ? (
            <>
              Quét tự động: server tự sàng universe (crypto top khối lượng sàn
              + cổ phiếu Mỹ đang mạnh 52 tuần) bằng bộ tiêu chí thực chiến —
              động lượng, RSI, đỉnh 52 tuần, breakout kèm khối lượng, thanh
              khoản — rồi chạy pipeline LLM trên {job?.tickers.length ?? "top"}{" "}
              ứng viên điểm cao nhất. Không cần danh sách theo dõi.
            </>
          ) : (
            <>
              Chạy pipeline phân tích cho toàn bộ watchlist hiện hành. Mỗi mã
              chạy đầy đủ các agent LLM nên job có thể mất nhiều phút.
            </>
          )}
        </CardDescription>
        <CardAction className="flex items-center gap-2">
          <Button
            variant="outline"
            className="min-touch"
            onClick={() => void startScan("auto")}
            disabled={busy}
          >
            {busy && kind === "auto" ? (
              <Loader2 className="animate-spin" aria-hidden />
            ) : (
              <ScanSearch data-icon="inline-start" aria-hidden />
            )}
            {busy && kind === "auto" ? "Đang quét thị trường…" : "Quét tự động"}
          </Button>
          <Button
            className="min-touch"
            onClick={() => void startScan("watchlist")}
            disabled={symbolsCount === 0 || busy}
          >
            {busy && kind === "watchlist" ? (
              <Loader2 className="animate-spin" aria-hidden />
            ) : (
              <Play data-icon="inline-start" aria-hidden />
            )}
            {busy && kind === "watchlist"
              ? "Đang quét…"
              : phase === "starting"
                ? "Đang gửi…"
                : "Quét ngay"}
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-4">
        {phase === "running" && kind === "auto" && job == null ? (
          <p aria-live="polite" className="text-sm text-muted-foreground">
            Đang sàng thị trường (crypto + cổ phiếu Mỹ)… Bước này chỉ tính chỉ
            báo, không tốn LLM — sau đó pipeline LLM mới chạy trên các ứng viên
            điểm cao nhất.
          </p>
        ) : null}

        {screening && screening.candidates.length > 0 ? (
          <ScreeningTable screening={screening} />
        ) : null}
        {screeningEmpty ? (
          <p className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
            Bước sàng lọc không cho ứng viên nào đủ điểm — không có mã nào đáng
            chạy pipeline lúc này. Thử lại sau phiên giao dịch kế tiếp.
          </p>
        ) : null}

        {symbolsCount === 0 && phase === "idle" && kind === "watchlist" ? (
          <p className="text-sm text-muted-foreground">
            Cần ít nhất một mã trong danh sách theo dõi trước khi quét — hoặc
            bấm “Quét tự động” để server tự tìm mã.
          </p>
        ) : null}

        {phase === "running" ? (
          <div aria-live="polite" className="space-y-1.5">
            <p className="flex items-center gap-2 text-sm">
              <Loader2 className="size-4 animate-spin" aria-hidden />
              {jobId ? (
                <>
                  Job <span className="font-mono">{jobId}</span>
                  {status ? ` — ${STATUS_VI[status]}` : " — đang chờ trạng thái đầu tiên…"}
                  {createdAt
                    ? ` · đã chạy ${elapsedLabel(createdAt, now)}`
                    : null}
                </>
              ) : (
                "Đang chờ trạng thái đầu tiên…"
              )}
            </p>
            {isStuck ? (
              <div className="flex items-start gap-2 rounded-lg bg-muted p-3 text-sm">
                <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                <span>
                  Job không đổi trạng thái trong hơn 15 phút — kiểm tra log của
                  server FastAPI. UI vẫn tiếp tục theo dõi.
                </span>
              </div>
            ) : null}
          </div>
        ) : null}

        {phase === "starting" ? (
          <p aria-live="polite" className="text-sm">
            Đang gửi yêu cầu quét…
          </p>
        ) : null}

        {phase === "error" && error ? (
          <div role="alert" className="space-y-3 rounded-lg border border-destructive/40 p-3">
            <p className="text-sm text-destructive">{error.message}</p>
            {error.status === 404 ? (
              <p className="text-sm text-muted-foreground">
                Chưa có endpoint /api/daily trên backend (hợp đồng §5) hoặc job
                đã mất khi server restart (job là state in-memory). Lỗi sẽ hết
                sau khi backend cập nhật — bấm “Quét ngay” để tạo job mới.
              </p>
            ) : null}
            <Button variant="outline" className="min-touch" onClick={resumePolling}>
              Thử lại
            </Button>
          </div>
        ) : null}

        {job && job.results.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">
                Kết quả quét pipeline theo từng mã
              </caption>
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th scope="col" className="py-2 pr-3 font-medium">Cặp</th>
                  <th scope="col" className="py-2 pr-3 font-medium">Tín hiệu</th>
                  <th scope="col" className="py-2 pr-3 font-medium">Lệnh đề xuất</th>
                  <th scope="col" className="py-2 pr-3 font-medium">Dòng tiền</th>
                  <th scope="col" className="py-2 pr-3 font-medium">Kết quả</th>
                  <th scope="col" className="py-2 font-medium">Duyệt</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {job.results.map((item) => (
                  <ResultRow key={item.ticker} item={item} />
                ))}
              </tbody>
            </table>
            {job.status === "failed" ? (
              <p role="alert" className="mt-3 text-sm text-destructive">
                Job kết thúc với trạng thái “Thất bại” — kết quả bên dưới là
                phần đã chạy được.
              </p>
            ) : null}
          </div>
        ) : null}

        {job && isTerminal && !busy ? (
          // Job xong → dẫn thẳng sang màn Duyệt lệnh nơi kế hoạch đang chờ.
          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-dashed p-3 text-sm">
            <span>
              Job {STATUS_VI[job.status].toLowerCase()} —{" "}
              {job.results.filter((r) => r.approval_id).length} kế hoạch trong
              hàng đợi duyệt.
            </span>
            <Link
              href="/approvals"
              className="min-touch inline-flex items-center rounded-lg border px-3 text-sm font-medium hover:bg-muted"
            >
              Xem trong Duyệt lệnh
            </Link>
          </div>
        ) : null}

        {job && job.results.length === 0 && !busy ? (
          <div className="flex h-40 items-center justify-center rounded-lg border border-dashed p-4 text-center text-sm text-muted-foreground">
            {job.status === "failed"
              ? "Job quét thất bại — không có kết quả nào. Bấm “Quét ngay” để thử lại."
              : "Job kết thúc mà không có kết quả nào cho mã nào."}
          </div>
        ) : null}

        {phase === "idle" && !job ? (
          <div className="flex h-40 items-center justify-center rounded-lg border border-dashed p-4 text-center text-sm text-muted-foreground">
            Chưa có lần quét nào — bấm “Quét tự động” (server tự tìm mã) hoặc
            “Quét ngay” (chạy trên watchlist hiện tại).
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

/** Bảng ứng viên sau bước sàng lọc kỹ thuật (job auto, contract §5 rev 4). */
function ScreeningTable({ screening }: { screening: ScreeningInfo }) {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge variant="outline">Kết quả sàng lọc</Badge>
        <span className="text-muted-foreground">
          universe: {screening.universe_crypto} crypto (top khối lượng) +{" "}
          {screening.universe_stock} cổ phiếu (mạnh 52 tuần) ={" "}
          {screening.universe_count} mã · top {screening.candidates.length}{" "}
          ứng viên đi tiếp vào pipeline
          {screening.mock ? " (mock)" : ""}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">
            Ứng viên sau sàng lọc kỹ thuật, xếp theo điểm
          </caption>
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground">
              <th scope="col" className="py-2 pr-3 font-medium">Mã</th>
              <th scope="col" className="py-2 pr-3 font-medium">Loại</th>
              <th scope="col" className="py-2 pr-3 font-medium">Điểm</th>
              <th scope="col" className="py-2 pr-3 font-medium">Động lượng 20P</th>
              <th scope="col" className="py-2 pr-3 font-medium">RSI 14</th>
              <th scope="col" className="py-2 pr-3 font-medium">RVOL</th>
              <th scope="col" className="py-2 pr-3 font-medium">vs đỉnh 52T</th>
              <th scope="col" className="py-2 font-medium">Lý do</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {screening.candidates.map((candidate) => (
              <tr key={candidate.ticker} className="align-top">
                <td className="py-2 pr-3 font-mono font-medium">
                  {candidate.ticker}
                  {candidate.breakout ? (
                    <Badge className="ml-2 align-middle text-xs">Phá đỉnh</Badge>
                  ) : null}
                </td>
                <td className="py-2 pr-3">
                  <Badge variant={candidate.asset_type === "crypto" ? "default" : "secondary"}>
                    {candidate.asset_type === "crypto" ? "Crypto" : "Cổ phiếu"}
                  </Badge>
                </td>
                <td className="py-2 pr-3 tabular-nums">
                  {candidate.score.toFixed(1)}
                </td>
                <td className="py-2 pr-3 tabular-nums">
                  {candidate.momentum_pct >= 0 ? "+" : ""}
                  {candidate.momentum_pct.toFixed(1)}%
                </td>
                <td className="py-2 pr-3 tabular-nums">
                  {candidate.rsi14 != null ? candidate.rsi14.toFixed(0) : "—"}
                </td>
                <td className="py-2 pr-3 tabular-nums">
                  ×{candidate.volume_ratio.toFixed(1)}
                </td>
                <td className="py-2 pr-3 tabular-nums">
                  {candidate.dist_52w_pct.toFixed(1)}%
                </td>
                <td className="py-2 text-muted-foreground">
                  {candidate.reasons.length > 0
                    ? candidate.reasons.join(" · ")
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
