import { generateForm } from "@rjsf/antd";
import type { FormProps, IChangeEvent } from "@rjsf/core";
import { getSubmitButtonOptions } from "@rjsf/utils";
import type { FormContextType, RJSFSchema, SubmitButtonProps, UiSchema } from "@rjsf/utils";
import validator from "@rjsf/validator-ajv8";
import { Button } from "antd";
import { createContext, useContext, useMemo, type ReactNode } from "react";

/**
 * RJSF keeps the first `ButtonTemplates` closure after mount, so a later
 * `actions` node would render stale inside that slot. Publish the latest
 * actions through context: the stable template always reads the current node.
 */
const SchemaFormActionsContext = createContext<ReactNode>(undefined);

export interface SchemaFormProps<T extends Record<string, unknown>> {
  schema: RJSFSchema;
  formData?: T;
  onSubmit: (data: T) => void;
  disabled?: boolean;
  submitText?: string;
  formContext?: FormContextType;
  actions?: ReactNode;
  uiSchema?: UiSchema<T>;
  widgets?: FormProps<T>["widgets"];
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
  formContext,
  actions,
  uiSchema: customUiSchema,
  widgets,
}: SchemaFormProps<T>) {
  const TypedForm = useMemo(() => generateForm<T>(), []);
  const isolatedFormData = useMemo(
    () => (formData === undefined ? undefined : structuredClone(formData)),
    [formData],
  );
  const uiSchema = useMemo(
    () => ({
      ...customUiSchema,
      ...submitUiSchema<T>(disabled, submitText),
    }),
    [customUiSchema, disabled, submitText],
  );
  const templates = useMemo(() => {
    if (actions === undefined) {
      return undefined;
    }
    return {
      ButtonTemplates: {
        SubmitButton: (props: SubmitButtonProps) => {
          const options = getSubmitButtonOptions(props.uiSchema);
          return (
            <div className="schema-form-actions">
              <Button type="primary" htmlType="submit" {...options.props}>
                {options.submitText}
              </Button>
              <SchemaFormActionsSlot />
            </div>
          );
        },
      },
    };
  }, [actions === undefined]);

  const handleSubmit = (event: IChangeEvent<T>): void => {
    if (event.formData === undefined) {
      throw new Error("Submitted form data is missing");
    }
    onSubmit(structuredClone(event.formData));
  };

  return (
    <SchemaFormActionsContext.Provider value={actions}>
      <TypedForm
        schema={schema}
        uiSchema={uiSchema}
        formData={isolatedFormData}
        validator={validator}
        disabled={disabled}
        formContext={formContext}
        templates={templates}
        widgets={widgets}
        onSubmit={handleSubmit}
      />
    </SchemaFormActionsContext.Provider>
  );
}

function SchemaFormActionsSlot() {
  return <>{useContext(SchemaFormActionsContext)}</>;
}
