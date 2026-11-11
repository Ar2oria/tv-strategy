import { Alert, Button, Drawer, Input, Space, Switch, Typography } from "antd";
import { useEffect, useState } from "react";

import { CommaSeparatedWidget } from "../../components/CommaSeparatedWidget";
import { SchemaForm } from "../../components/SchemaForm";
import type { JsonObject } from "../../types/api";
import type { TaskDescriptor } from "../../types/task";
import { validateCronShape } from "./cron";

const TASK_FORM_CONTEXT = { labelAlign: "left", colSpan: 24 } as const;
const TASK_UI_SCHEMA = {
  universe_codes: { "ui:widget": "commaSeparated" },
  symbols: { "ui:widget": "commaSeparated" },
} as const;
const TASK_WIDGETS = { commaSeparated: CommaSeparatedWidget };

export interface TaskConfigDrawerProps {
  task: TaskDescriptor | null;
  saving: boolean;
  saveError: string | null;
  conflict: boolean;
  onSave: (update: {
    cron: string;
    enabled: boolean;
    params: JsonObject;
  }) => void;
  onClose: () => void;
}

/**
 * Cron, enable state, and typed Task params with server-side validation.
 *
 * Local edits survive a rejected save: on 409 the parent reloads the newest
 * revision into `task`, and this component then shows the fresh server values
 * under a "reapply" notice instead of silently submitting the user's stale
 * values again. `conflict` is what distinguishes that refresh from a normal
 * successful save, so a successful save re-seeds the form as usual.
 */
export function TaskConfigDrawer({
  task,
  saving,
  saveError,
  conflict,
  onSave,
  onClose,
}: TaskConfigDrawerProps) {
  const [cron, setCron] = useState(task?.cron ?? "");
  const [enabled, setEnabled] = useState(task?.enabled ?? true);
  const [params, setParams] = useState<JsonObject>(task?.params ?? {});
  const [cronError, setCronError] = useState<string | null>(null);

  const identity = `${task?.name ?? ""}@${task?.revision ?? -1}`;
  useEffect(() => {
    setCron(task?.cron ?? "");
    setEnabled(task?.enabled ?? true);
    setParams(task?.params ?? {});
    setCronError(null);
    // A conflict refresh must show the newest server values; a normal save
    // re-seeds the form from the returned document.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [identity]);

  if (task === null) {
    return null;
  }

  const submit = (submitted: JsonObject): void => {
    const shape = validateCronShape(cron);
    if (!shape.valid) {
      setCronError(shape.message);
      return;
    }
    setCronError(null);
    setParams(submitted);
    onSave({ cron: cron.trim(), enabled, params: { ...submitted } });
  };

  return (
    <Drawer
      open
      rootClassName="task-config-drawer"
      size={640}
      styles={{ wrapper: { maxWidth: "100vw" } }}
      title={`配置 ${task.display_name}`}
      onClose={onClose}
      destroyOnHidden
    >
      <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          标准五段 Crontab：分 时 日 月 周。时区由系统设置决定。
        </Typography.Text>
        {conflict ? (
          <Alert
            type="warning"
            showIcon
            title="配置已被其他页面修改，已加载最新值，请重新确认后再保存。"
          />
        ) : null}
        {saveError === null ? null : (
          <Alert type="error" showIcon title={saveError} />
        )}
        <div>
          <Typography.Text strong>Cron 表达式</Typography.Text>
          <Input
            aria-label="Cron 表达式"
            style={{ marginTop: 4 }}
            value={cron}
            status={cronError === null ? undefined : "error"}
            onChange={(event) => {
              setCron(event.target.value);
              setCronError(null);
            }}
          />
          {cronError === null ? null : (
            <Typography.Text type="danger" style={{ fontSize: 12 }}>
              {cronError}
            </Typography.Text>
          )}
        </div>
        <Space>
          <Typography.Text strong>启用调度</Typography.Text>
          <Switch
            aria-label="启用调度"
            checked={enabled}
            onChange={setEnabled}
          />
        </Space>
        <div>
          <Typography.Text strong>任务参数</Typography.Text>
          <div className="task-schema-form" style={{ marginTop: 8 }}>
            <SchemaForm
              key={`${task.name}-${task.revision}`}
              schema={task.params_schema}
              formData={params}
              formContext={TASK_FORM_CONTEXT}
              uiSchema={TASK_UI_SCHEMA}
              widgets={TASK_WIDGETS}
              actions={<Button onClick={onClose} disabled={saving}>关闭</Button>}
              disabled={saving}
              submitText="保存配置"
              onSubmit={submit}
            />
          </div>
        </div>
      </Space>
    </Drawer>
  );
}
