import { Modal, Space, Typography } from "antd";

import { SchemaForm } from "../../components/SchemaForm";
import type { JsonObject } from "../../types/api";
import type { IndicatorDescriptor } from "../../types/indicator";
import type { ActiveIndicatorInstance } from "./indicatorInstances";

export interface IndicatorEditorProps {
  instance: ActiveIndicatorInstance;
  descriptor: IndicatorDescriptor | null;
  onSubmit: (params: JsonObject) => void;
  onCancel: () => void;
}

/** Re-parameterize an existing instance; the instance id never changes. */
export function IndicatorEditor({
  instance,
  descriptor,
  onSubmit,
  onCancel,
}: IndicatorEditorProps) {
  return (
    <Modal
      open
      title={`编辑 ${instance.displayName} 参数`}
      onCancel={onCancel}
      footer={null}
      destroyOnHidden
    >
      {descriptor === null ? (
        <Typography.Text type="danger">
          后端已不再提供该指标（{instance.name}），请移除该实例后重试。
        </Typography.Text>
      ) : (
        <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
          <SchemaForm
            schema={descriptor.params_schema}
            formData={instance.params}
            submitText="保存"
            onSubmit={onSubmit}
          />
        </Space>
      )}
    </Modal>
  );
}
