import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BillingApiError, type BillingMe, type RechargeOrder } from "@/lib/billing-api";
import { AccountPanel } from "./account-panel";

const mockQrcode = vi.hoisted(() => ({
  toDataURL: vi.fn(),
}));

vi.mock("qrcode", () => ({
  default: mockQrcode,
}));

const mockBillingApi = vi.hoisted(() => ({
  me: vi.fn(),
  createRechargeOrder: vi.fn(),
  getRechargeOrder: vi.fn(),
  confirmMockPayment: vi.fn(),
}));

vi.mock("@/lib/billing-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/billing-api")>()),
  billingApi: mockBillingApi,
}));

const mockBilling: BillingMe = {
  balance: "66.00000000",
  currency: "CNY",
  entries: [
    { id: "entry-1", amount: "66.00000000", entry_type: "recharge", created_at: "2026-08-29T02:00:00Z" },
  ],
  total: 1,
  limit: 20,
  offset: 0,
  payment_provider: "mock",
};

const pendingOrder: RechargeOrder = {
  id: "order-1",
  out_trade_no: "Rabc123",
  provider: "mock",
  amount: "30.00",
  state: "pending",
  pay_url: null,
  code_url: null,
  mock_confirmable: true,
  created_at: "2026-08-29T02:00:00Z",
  paid_at: null,
};

const paidOrder: RechargeOrder = { ...pendingOrder, state: "paid", mock_confirmable: false };

beforeEach(() => {
  Object.values(mockBillingApi).forEach((mock) => mock.mockReset());
  mockQrcode.toDataURL.mockReset();
  mockQrcode.toDataURL.mockResolvedValue("data:image/png;base64,QRBYTES");
  mockBillingApi.me.mockResolvedValue(mockBilling);
});

describe("AccountPanel", () => {
  it("shows balance, entries and the mock cashier channel", async () => {
    render(<AccountPanel onClose={vi.fn()} />);

    expect(await screen.findByText("我的账户")).toBeInTheDocument();
    expect(screen.getByText("66.00")).toBeInTheDocument();
    expect(screen.getByText("1 积分 = 1 元，用于调用 AI 大模型")).toBeInTheDocument();
    expect(screen.getByText("充值")).toBeInTheDocument();
    expect(screen.getByText("模拟支付（本地）")).toBeInTheDocument();
    expect(screen.getByText("支付宝（暂未开通）")).toBeInTheDocument();
  });

  it("recharges with a preset amount and refreshes the balance after mock payment", async () => {
    const user = userEvent.setup();
    mockBillingApi.createRechargeOrder.mockResolvedValue(pendingOrder);
    mockBillingApi.confirmMockPayment.mockResolvedValue(paidOrder);
    mockBillingApi.me
      .mockResolvedValueOnce(mockBilling)
      .mockResolvedValueOnce({ ...mockBilling, balance: "96.00000000" });
    render(<AccountPanel onClose={vi.fn()} />);

    await screen.findByText("我的账户");
    await user.click(screen.getByRole("button", { name: "30 积分" }));
    await user.click(screen.getByRole("button", { name: "立即充值" }));

    await screen.findByText("已创建模拟订单，本环境不发生真实扣款。");
    expect(mockBillingApi.createRechargeOrder).toHaveBeenCalledWith("mock", "30.00");
    await user.click(screen.getByRole("button", { name: "模拟支付成功" }));

    expect(await screen.findByText("充值成功！余额已更新。")).toBeInTheDocument();
    expect(await screen.findByText("96.00")).toBeInTheDocument();
    expect(mockBillingApi.confirmMockPayment).toHaveBeenCalledWith("order-1");
  });

  it("validates the amount locally before calling the API", async () => {
    const user = userEvent.setup();
    render(<AccountPanel onClose={vi.fn()} />);

    await screen.findByText("我的账户");
    await user.clear(screen.getByLabelText(/或输入自定义金额/));
    await user.type(screen.getByLabelText(/或输入自定义金额/), "20000");
    await user.click(screen.getByRole("button", { name: "立即充值" }));

    expect(await screen.findByText("充值金额需在 1 - 10000 积分之间。")).toBeInTheDocument();
    expect(mockBillingApi.createRechargeOrder).not.toHaveBeenCalled();
  });

  it("offers a cashier link for alipay orders and does not show the mock button", async () => {
    const user = userEvent.setup();
    mockBillingApi.me.mockResolvedValue({ ...mockBilling, payment_provider: "alipay" });
    mockBillingApi.createRechargeOrder.mockResolvedValue({
      ...pendingOrder,
      provider: "alipay",
      mock_confirmable: false,
      pay_url: "https://openapi.alipay.com/gateway.do?sign=abc",
    });
    render(<AccountPanel onClose={vi.fn()} />);

    await screen.findByText("我的账户");
    await user.click(screen.getByRole("button", { name: "立即充值" }));

    expect(await screen.findByRole("link", { name: "打开支付宝收银台" })).toHaveAttribute(
      "href",
      "https://openapi.alipay.com/gateway.do?sign=abc",
    );
    expect(screen.queryByRole("button", { name: "模拟支付成功" })).not.toBeInTheDocument();
  });

  it("renders a WeChat QR code for wechat orders and polls until paid", async () => {
    const user = userEvent.setup();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      mockBillingApi.me
        .mockResolvedValueOnce({ ...mockBilling, payment_provider: "wechat" })
        .mockResolvedValue({ ...mockBilling, balance: "96.00000000" });
      mockBillingApi.createRechargeOrder.mockResolvedValue({
        ...pendingOrder,
        provider: "wechat",
        mock_confirmable: false,
        pay_url: null,
        code_url: "weixin://wxpay/bizpayurl?pr=abc123",
      });
      mockBillingApi.getRechargeOrder.mockResolvedValue(paidOrder);
      render(<AccountPanel onClose={vi.fn()} />);

      await screen.findByText("我的账户");
      await user.click(screen.getByRole("button", { name: "立即充值" }));

      const qr = await screen.findByRole("img", { name: "微信支付二维码" });
      expect(qr).toHaveAttribute("src", "data:image/png;base64,QRBYTES");
      expect(screen.getByText(/请使用微信扫码支付/)).toBeInTheDocument();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(3000);
      });
      expect(await screen.findByText("充值成功！余额已更新。")).toBeInTheDocument();
      expect(await screen.findByText("96.00")).toBeInTheDocument();
      expect(mockBillingApi.getRechargeOrder).toHaveBeenCalledWith("order-1");
    } finally {
      vi.useRealTimers();
    }
  });

  it("reports a load failure and supports retry", async () => {
    const user = userEvent.setup();
    mockBillingApi.me.mockRejectedValueOnce(new BillingApiError(503)).mockResolvedValueOnce(mockBilling);
    render(<AccountPanel onClose={vi.fn()} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("账户信息加载失败");
    await user.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("66.00")).toBeInTheDocument();
  });

  it("lists entry history with signed amounts", async () => {
    render(<AccountPanel onClose={vi.fn()} />);
    const history = await screen.findByRole("region", { name: "积分流水" });
    const row = within(history).getByText("+66.00 积分").closest("li");
    expect(row).not.toBeNull();
    expect(within(history).getByText("充值")).toBeInTheDocument();
  });
});
