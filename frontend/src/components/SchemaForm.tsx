import { generateForm } from "@rjsf/antd";
import type { IChangeEvent } from "@rjsf/core";
import type { RJSFSchema, UiSchema } from "@rjsf/utils";
import validator from "@rjsf/validator-ajv8";
import { useMemo } from "react";

export interface SchemaFormProps<T extends Record<string, unknown>> {
  schema: RJSFSchema;
  formData?: T;
  onSubmit: (data: T) => void;
  disabled?: boolean;
  submitText?: string;
}

function submitUiSchema<T extends Record<string, unknown>>(
  disabled: boolean,
  submitText: string,
): UiSchema<T> {
  return {
    "ui:submitButtonOptions": {
      submitText,
      props: { disabled },
    },
  };
}

export function SchemaForm<T extends Record<string, unknown>>({
  schema,
  formData,
  onSubmit,
  disabled = false,
  submitText = "Submit",
}: SchemaFormProps<T>) {
  const TypedForm = useMemo(() => generateForm<T>(), []);
  const isolatedFormData = useMemo(
    () => (formData === undefined ? undefined : structuredClone(formData)),
    [formData],
  );
  const uiSchema = useMemo(
    () => submitUiSchema<T>(disabled, submitText),
    [disabled, submitText],
  );

  const handleSubmit = (event: IChangeEvent<T>): void => {
    if (event.formData === undefined) {
      throw new Error("Submitted form data is missing");
    }
    onSubmit(structuredClone(event.formData));
  };

  return (
    <TypedForm
      schema={schema}
      uiSchema={uiSchema}
      formData={isolatedFormData}
      validator={validator}
      disabled={disabled}
      onSubmit={handleSubmit}
    />
  );
}
