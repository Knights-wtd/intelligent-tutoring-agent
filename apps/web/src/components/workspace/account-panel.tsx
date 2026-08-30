"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import QRCode from "qrcode";

import {
  BillingApiError,
  billingApi,
  type BillingMe,
  type RechargeOrder,
} from "@/lib/billing-api";

import styles from "./workspace-shell.module.css";

type Props = {
  onClose: () => void;
};

const PRESET_AMOUNTS = ["10", "30", "50", "100"];
const POLL_INTERVAL_MS = 2500;

const ENTRY_TYPE_LABELS: Record<BillingEntryType, string> = {
  recharge: "充值",
  consumption: "消费",
  reversal: "冲正",
};

type BillingEntryType = BillingMe["entries"][number]["entry_type"];

const ALL_PROVIDERS: Array<{ id: string; label: string }> = [
  { id: "alipay", label: "支付宝" },
  { id: "wechat", label: "微信支付" },
  { id: "mock", label: "模拟支付（本地）" },
];

function entryAmountLabel(entry: BillingMe["entries"][number]): string {
  const amount = Number(entry.amount);
  const sign = amount >= 0 ? "+" : "";
  return `${sign}${amount.toFixed(2)} 积分`;
}

function entryTimeLabel(entry: BillingMe["entries"][number]): string {
  if (!entry.created_at) return "";
  return new Date(entry.created_at).toLocaleString("zh-CN", { hour12: false });
}

function providerLabel(provider: string): string {
  return ALL_PROVIDERS.find((candidate) => candidate.id === provider)?.label ?? provider;
}

export function AccountPanel({ onClose }: Props) {
  const [billing, setBilling] = useState<BillingMe | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadAttempt, setReloadAttempt] = useState(0);
  const [selectedAmount, setSelectedAmount] = useState<string>("30");
  const [customAmount, setCustomAmount] = useState<string>("");
  const [order, setOrder] = useState<RechargeOrder | null>(null);
  const [orderError, setOrderError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [confirmingMock, setConfirmingMock] = useState(false);
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const applyBilling = useCallback(async (signal: AbortSignal) => {
    try {
      const me = await billingApi.me(signal);
      if (!signal.aborted) {
        setBilling(me);
        setLoadError(null);
      }
    } catch {
      if (!signal.aborted) {
        setLoadError("账户信息加载失败，请稍后重试。");
      }
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void billingApi
      .me(controller.signal)
      .then((me) => {
        if (!controller.signal.aborted) {
          setBilling(me);
          setLoadError(null);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setLoadError("账户信息加载失败，请稍后重试。");
        }
      });
    return () => controller.abort();
  }, [reloadAttempt]);

  const reloadBilling = useCallback(() => {
    const controller = new AbortController();
    void applyBilling(controller.signal);
  }, [applyBilling]);

  useEffect(() => {
    if (!order || order.state !== "pending") {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }
    const orderId = order.id;
    pollRef.current = setInterval(() => {
      void billingApi
        .getRechargeOrder(orderId)
        .then((next) => {
          setOrder((current) => (current && current.id === next.id ? next : current));
          if (next.state === "paid") {
            reloadBilling();
          }
        })
        .catch(() => undefined);
    }, POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [order, reloadBilling]);

  useEffect(() => {
    const codeUrl = order?.code_url;
    // Without a code_url the QR block is not rendered, so there is nothing to
    // reset here; stale data URLs are simply never displayed.
    if (!codeUrl) return;
    let cancelled = false;
    void QRCode.toDataURL(codeUrl, { width: 220, margin: 1 }).then(
      (url) => {
        if (!cancelled) setQrDataUrl(url);
      },
      () => {
        if (!cancelled) setQrDataUrl(null);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [order?.code_url]);

  const effectiveAmount = customAmount.trim() !== "" ? customAmount.trim() : selectedAmount;

  const submitRecharge = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!billing || submitting) return;
    const amount = Number(effectiveAmount);
    if (!Number.isFinite(amount) || amount < 1 || amount > 10000) {
      setOrderError("充值金额需在 1 - 10000 积分之间。");
      return;
    }
    setSubmitting(true);
    setOrderError(null);
    try {
      const created = await billingApi.createRechargeOrder(
        billing.payment_provider,
        amount.toFixed(2),
      );
      setOrder(created);
    } catch (error) {
      setOrderError(
        error instanceof BillingApiError && error.status === 422
          ? "充值金额需在 1 - 10000 积分之间。"
          : "创建充值订单失败，请稍后重试。",
      );
    } finally {
      setSubmitting(false);
    }
  };

  const confirmMockPayment = async () => {
    if (!order || confirmingMock) return;
    setConfirmingMock(true);
    setOrderError(null);
    try {
      const next = await billingApi.confirmMockPayment(order.id);
      setOrder(next);
      if (next.state === "paid") {
        reloadBilling();
      }
    } catch {
      setOrderError("模拟支付失败，请重试。");
    } finally {
      setConfirmingMock(false);
    }
  };

  const dismissOrder = () => {
    setOrder(null);
    setOrderError(null);
  };

  const isMock = billing?.payment_provider === "mock";
  const orderPaid = order?.state === "paid";
  const orderMismatch = order?.state === "paid_mismatch";

  return (
    <div className={styles.classroomDialogBackdrop} role="presentation">
      <section aria-label="我的账户" aria-modal="true" className={styles.classroomDialog} role="dialog">
        <header>
          <div>
            <span className={styles.eyebrow}>个人学习库房</span>
            <h2>我的账户</h2>
          </div>
          <button aria-label="关闭账户窗口" onClick={onClose} type="button">
            关闭
          </button>
        </header>

        {billing === null && !loadError ? (
          <p role="status">正在加载账户信息…</p>
        ) : null}
        {loadError ? (
          <div className={styles.tutorError} role="alert">
            <p>{loadError}</p>
            <button onClick={() => { setLoadError(null); setReloadAttempt((value) => value + 1); }} type="button">
              重试
            </button>
          </div>
        ) : null}

        {billing ? (
          <>
            <div className={styles.accountBalanceCard}>
              <span className={styles.accountBalanceLabel}>当前余额</span>
              <strong className={styles.accountBalanceValue}>
                {Number(billing.balance).toFixed(2)}
                <span className={styles.accountBalanceUnit}> 积分</span>
              </strong>
              <span className={styles.accountBalanceHint}>1 积分 = 1 元，用于调用 AI 大模型</span>
            </div>

            {orderPaid ? (
              <div className={styles.accountSuccess} role="status">
                <p>充值成功！余额已更新。</p>
                <button onClick={dismissOrder} type="button">继续充值</button>
              </div>
            ) : order && !orderPaid ? (
              <div className={styles.accountAwaiting} role="status">
                <p>
                  {orderMismatch
                    ? "支付金额与订单不一致，本单未入账，请联系管理员处理。"
                    : isMock
                      ? "已创建模拟订单，本环境不发生真实扣款。"
                      : "订单已创建，完成支付后本页会自动确认到账。"}
                </p>
                {!orderMismatch ? (
                  <>
                    {order.mock_confirmable ? (
                      <button disabled={confirmingMock} onClick={() => void confirmMockPayment()} type="button">
                        {confirmingMock ? "正在确认…" : "模拟支付成功"}
                      </button>
                    ) : order.code_url ? (
                      <div className={styles.accountQrBlock}>
                        {qrDataUrl ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img alt="微信支付二维码" className={styles.accountQrImage} src={qrDataUrl} />
                        ) : (
                          <p className={styles.accountQrPlaceholder}>正在生成微信收款码…</p>
                        )}
                        <p className={styles.accountQrHint}>请使用微信扫码支付（积分 1:1 到账）</p>
                      </div>
                    ) : order.pay_url ? (
                      <a
                        className={styles.accountPayLink}
                        href={order.pay_url}
                        rel="noreferrer"
                        target="_blank"
                      >
                        打开{providerLabel(order.provider)}收银台
                      </a>
                    ) : null}
                    <button onClick={dismissOrder} type="button">返回</button>
                  </>
                ) : (
                  <button onClick={dismissOrder} type="button">返回</button>
                )}
              </div>
            ) : (
              <form
                className={styles.accountRechargeForm}
                noValidate
                onSubmit={(event) => void submitRecharge(event)}
              >
                <fieldset className={styles.accountFieldset}>
                  <legend>充值金额</legend>
                  <div className={styles.accountAmountChips}>
                    {PRESET_AMOUNTS.map((preset) => (
                      <button
                        aria-pressed={selectedAmount === preset && customAmount.trim() === ""}
                        key={preset}
                        onClick={() => {
                          setSelectedAmount(preset);
                          setCustomAmount("");
                        }}
                        type="button"
                      >
                        {preset} 积分
                      </button>
                    ))}
                  </div>
                  <label className={styles.accountCustomLabel} htmlFor="account-custom-amount">
                    或输入自定义金额（1 - 10000）
                  </label>
                  <input
                    id="account-custom-amount"
                    inputMode="decimal"
                    max="10000"
                    min="1"
                    onChange={(event) => setCustomAmount(event.target.value)}
                    placeholder="例如 66.00"
                    step="0.01"
                    type="number"
                    value={customAmount}
                  />
                </fieldset>
                <fieldset className={styles.accountFieldset}>
                  <legend>支付方式</legend>
                  <div className={styles.accountProviderRow}>
                    {ALL_PROVIDERS.map((candidate) =>
                      candidate.id === billing.payment_provider ? (
                        <span
                          aria-current="true"
                          className={styles.accountProviderOption}
                          key={candidate.id}
                        >
                          {candidate.label}
                        </span>
                      ) : (
                        <span className={styles.accountProviderDisabled} key={candidate.id}>
                          {candidate.label.replace("（本地）", "")}
                          {candidate.id === "mock" ? "" : "（暂未开通）"}
                        </span>
                      ),
                    )}
                  </div>
                </fieldset>
                {orderError ? (
                  <p className={styles.accountError} role="alert">
                    {orderError}
                  </p>
                ) : null}
                <button
                  className={styles.accountSubmitButton}
                  disabled={submitting}
                  type="submit"
                >
                  {submitting ? "正在创建订单…" : "立即充值"}
                </button>
              </form>
            )}

            <section aria-label="积分流水" className={styles.accountHistory}>
              <h3>积分流水</h3>
              {billing.entries.length === 0 ? (
                <p className={styles.accountHistoryEmpty}>还没有流水记录</p>
              ) : (
                <ul className={styles.accountHistoryList}>
                  {billing.entries.map((entry) => (
                    <li className={styles.accountHistoryRow} key={entry.id}>
                      <span className={styles.accountEntryType}>{ENTRY_TYPE_LABELS[entry.entry_type]}</span>
                      <span className={styles.accountEntryAmount}>{entryAmountLabel(entry)}</span>
                      <span className={styles.accountEntryTime}>{entryTimeLabel(entry)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        ) : null}
      </section>
    </div>
  );
}
