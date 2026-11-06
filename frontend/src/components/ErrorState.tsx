import { Alert, Button, Space } from "antd";

import { ApiError } from "../api/errors";

export interface ErrorStateProps {
  error: unknown;
  onRetry?: () => void;
}

export function ErrorState({ error, onRetry }: ErrorStateProps) {
  const message =
    error instanceof ApiError
      ? error.message
      : "An unexpected error occurred. Please try again.";
  return (
    <Alert
      type="error"
      showIcon
      title="Unable to complete the request"
      description={
        <Space orientation="vertical">
          <span>{message}</span>
          {onRetry === undefined ? null : (
            <Button onClick={onRetry}>Try again</Button>
          )}
        </Space>
      }
    />
  );
}
