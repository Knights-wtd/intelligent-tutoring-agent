import { apiUrl } from "@/lib/api-base";

export type BillingEntry = {
  id: string;
  amount: string;
  entry_type: "recharge" | "consumption" | "reversal";
  created_at: string | null;
};

export type BillingMe = {
  balance: string;
  currency: string;
  entries: BillingEntry[];
  total: number;
  limit: number;
  offset: number;
  /** 当前部署激活的支付渠道:mock 为本地模拟收银台,alipay 支付宝,wechat 微信支付。 */
  payment_provider: "mock" | "alipay" | "wechat";
};

export type RechargeProvider = "mock" | "alipay" | "wechat";

export type RechargeOrder = {
  id: string;
  out_trade_no: string;
  provider: string;
  amount: string;
  state: "pending" | "paid" | "paid_mismatch" | "cancelled";
  pay_url: string | null;
  /** 微信 Native 支付的 weixin:// 二维码内容,由前端渲染成扫码图。 */
  code_url: string | null;
  mock_confirmable: boolean;
  created_at: string | null;
  paid_at: string | null;
};

export class BillingApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(status: number, code: string | null = null) {
    super("Billing request failed");
    this.name = "BillingApiError";
    this.status = status;
    this.code = code;
  }
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(apiUrl(path), {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...init.headers,
    },
  });
  if (!response.ok) {
    let code: string | null = null;
    try {
      const body: unknown = await response.json();
      if (
        body !== null &&
        typeof body === "object" &&
        "detail" in body &&
        typeof (body as { detail: unknown }).detail === "string"
      ) {
        code = (body as { detail: string }).detail;
      }
    } catch {
      // Non-JSON error bodies keep the null code; the status alone still selects the message.
    }
    throw new BillingApiError(response.status, code);
  }
  return response.json() as Promise<T>;
}

export const billingApi = {
  me(signal?: AbortSignal): Promise<BillingMe> {
    return requestJson("/api/v1/billing/me", { signal });
  },

  createRechargeOrder(
    provider: RechargeProvider,
    amount: string,
    signal?: AbortSignal,
  ): Promise<RechargeOrder> {
    return requestJson("/api/v1/billing/recharge-orders", {
      method: "POST",
      body: JSON.stringify({ provider, amount }),
      signal,
    });
  },

  getRechargeOrder(orderId: string, signal?: AbortSignal): Promise<RechargeOrder> {
    return requestJson(`/api/v1/billing/recharge-orders/${encodeURIComponent(orderId)}`, {
      signal,
    });
  },

  confirmMockPayment(orderId: string, signal?: AbortSignal): Promise<RechargeOrder> {
    return requestJson(
      `/api/v1/billing/recharge-orders/${encodeURIComponent(orderId)}/mock-confirm`,
      { method: "POST", signal },
    );
  },
};
