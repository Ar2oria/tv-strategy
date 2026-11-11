import { Alert, Button, Modal, Radio, Space, Typography } from "antd";
import { useMemo, useState } from "react";

import { SchemaForm } from "../../components/SchemaForm";
import type { JsonObject } from "../../types/api";
import type { IndicatorDescriptor } from "../../types/indicator";
import type { ActiveIndicatorInstanceInput } from "./indicatorInstances";

export interface IndicatorPickerProps {
  open: boolean;
  descriptors: readonly IndicatorDescriptor[];
  onCancel: () => void;
  onAdd: (instance: ActiveIndicatorInstanceInput) => void;
}

function defaultsOf(descriptor: IndicatorDescriptor): JsonObject {
  const properties = (descriptor.params_schema.properties ?? {}) as Record<
    string,
    { default?: unknown }
  >;
  const entries = Object.entries(properties).map(([key, property]) => [
    key,
    (property.default ?? null) as JsonObject[string],
  ]);
  return Object.fromEntries(entries) as JsonObject;
}

/** Choose one backend indicator and parameterize a new immutable instance. */
export function IndicatorPicker({
  open,
  descriptors,
  onCancel,
  onAdd,
}: IndicatorPickerProps) {
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const selected = useMemo(
    () => descriptors.find((item) => item.name === selectedName) ?? null,
    [descriptors, selectedName],
  );

  const close = (): void => {
    setSelectedName(null);
    setSubmitError(null);
    onCancel();
  };

  const handleSubmit = (params: JsonObject): void => {
    if (selected === null) {
      setSubmitError("请选择指标");
      return;
    }
    if (typeof crypto?.randomUUID !== "function") {
      setSubmitError("浏览器不支持生成实例 ID");
      return;
    }
    onAdd({
      instanceId: crypto.randomUUID(),
      name: selected.name,
      displayName: selected.display_name,
      params: { ...params },
    });
    setSelectedName(null);
    setSubmitError(null);
  };

  return (
    <Modal
      open={open}
      title="添加指标"
      onCancel={close}
      footer={null}
      destroyOnHidden
    >
      <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
        <Radio.Group
          aria-label="指标选择"
          value={selectedName ?? undefined}
          onChange={(event) => {
            setSelectedName(String(event.target.value));
            setSubmitError(null);
          }}
        >
          <Space orientation="vertical">
            {descriptors.map((descriptor) => (
              <Radio key={descriptor.name} value={descriptor.name}>
                <Space orientation="vertical" size={0}>
                  <Typography.Text strong>
                    {descriptor.display_name}
                  </Typography.Text>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {descriptor.description}
                  </Typography.Text>
                </Space>
              </Radio>
            ))}
          </Space>
        </Radio.Group>
        {submitError === null ? null : (
          <Alert type="error" showIcon title={submitError} />
        )}
        {selected === null ? (
          <Typography.Text type="secondary">
            先选择一个指标，再设置参数。
          </Typography.Text>
        ) : (
          <SchemaForm
            key={selected.name}
            schema={selected.params_schema}
            formData={defaultsOf(selected)}
            submitText="添加"
            onSubmit={handleSubmit}
          />
        )}
      </Space>
    </Modal>
  );
}

export interface AddIndicatorButtonProps {
  onOpen: () => void;
}

export function AddIndicatorButton({ onOpen }: AddIndicatorButtonProps) {
  return (
    <Button type="primary" onClick={onOpen}>
      添加指标
    </Button>
  );
}
