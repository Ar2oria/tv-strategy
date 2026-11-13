import { Alert, Button, Input, Modal, Space, Typography } from "antd";
import { useEffect, useRef, useState } from "react";

import { testMarketNetwork } from "../../api/endpoints";
import type { NetworkTestResult } from "../../types/settings";
import { defaultNetworkTestSymbol, marketLabel } from "./marketOptions";

export interface NetworkTestModalProps {
  market: string;
  provider: string;
  open: boolean;
  onClose: () => void;
}

function ResultView({ result }: { result: NetworkTestResult }) {
  const latency = `耗时: ${result.latency_ms} ms`;
  if (result.connected) {
    return (
      <Alert
        type="success"
        showIcon
        title="数据源可用"
        description={
          <Space orientation="vertical" size={2}>
            <Typography.Text>{latency}</Typography.Text>
            <Typography.Text>
              最新价格（日线收盘）: {result.price ?? "—"} {result.currency ?? ""}
            </Typography.Text>
            <Typography.Text>价格日期: {result.price_date ?? "—"}</Typography.Text>
          </Space>
        }
      />
    );
  }
  if (result.error_type === "ProviderBusy") {
    return (
      <Alert
        type="warning"
        showIcon
        title="数据源正在使用中，请稍后重试"
        description={<Typography.Text>{latency}</Typography.Text>}
      />
    );
  }
  return (
    <Alert
      type="error"
      showIcon
      title="数据源不可用"
      description={
        <Space orientation="vertical" size={2}>
          <Typography.Text>{latency}</Typography.Text>
          {result.error_type === null ? null : (
            <Typography.Text>错误类型: {result.error_type}</Typography.Text>
          )}
          {result.detail === null ? null : (
            <Typography.Text className="network-test-detail">
              {result.detail}
            </Typography.Text>
          )}
        </Space>
      }
    />
  );
}

export function NetworkTestModal({
  market,
  provider,
  open,
  onClose,
}: NetworkTestModalProps) {
  const [symbol, setSymbol] = useState(defaultNetworkTestSymbol(market));
  const [result, setResult] = useState<NetworkTestResult | null>(null);
  const [pending, setPending] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [transportError, setTransportError] = useState<string | null>(null);
  const requestVersion = useRef(0);

  useEffect(() => {
    if (!open) {
      return;
    }
    requestVersion.current += 1;
    setSymbol(defaultNetworkTestSymbol(market));
    setResult(null);
    setPending(false);
    setValidationError(null);
    setTransportError(null);
  }, [open, market]);

  const close = (): void => {
    requestVersion.current += 1;
    setPending(false);
    onClose();
  };

  const start = async (): Promise<void> => {
    const normalized = symbol.trim();
    if (normalized === "") {
      setValidationError("请输入 Symbol 或交易对");
      return;
    }
    const version = requestVersion.current + 1;
    requestVersion.current = version;
    setPending(true);
    setResult(null);
    setValidationError(null);
    setTransportError(null);
    try {
      const next = await testMarketNetwork(market, { symbol: normalized });
      if (requestVersion.current === version) {
        setResult(next.data);
      }
    } catch {
      if (requestVersion.current === version) {
        setTransportError("网络测试失败，请稍后重试。");
      }
    } finally {
      if (requestVersion.current === version) {
        setPending(false);
      }
    }
  };

  return (
    <Modal
      open={open}
      title={`${marketLabel(market)} 网络测试`}
      rootClassName="network-test-modal"
      onCancel={close}
      footer={null}
    >
      <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
        <Typography.Text type="secondary">数据源：{provider}</Typography.Text>
        <div>
          <Typography.Text strong>Symbol / 交易对</Typography.Text>
          <Input
            aria-label="测试 Symbol 或交易对"
            style={{ marginTop: 8 }}
            value={symbol}
            disabled={pending}
            status={validationError === null ? undefined : "error"}
            onChange={(event) => {
              setSymbol(event.target.value);
              setValidationError(null);
            }}
            onPressEnter={() => {
              if (!pending) {
                void start();
              }
            }}
          />
          {validationError === null ? null : (
            <Typography.Text type="danger" style={{ fontSize: 12 }}>
              {validationError}
            </Typography.Text>
          )}
        </div>
        <Space wrap>
          <Button type="primary" loading={pending} disabled={pending} onClick={() => void start()}>
            开始测试
          </Button>
          <Button onClick={close}>关闭</Button>
        </Space>
        {transportError === null ? null : (
          <Alert type="error" showIcon title={transportError} />
        )}
        {result === null ? null : <ResultView result={result} />}
      </Space>
    </Modal>
  );
}
