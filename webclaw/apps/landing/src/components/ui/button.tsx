import { mergeProps } from "@base-ui/react/merge-props";
import { useRender } from "@base-ui/react/use-render";
import type * as React from "react";

type ButtonVariant = "primary" | "secondary";
type ButtonSize = "md" | "sm";

type ButtonProps = useRender.ComponentProps<"button"> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
};

const variantClasses: Record<ButtonVariant, string> = {
  primary:
    "bg-neutral-900 text-white hover:bg-neutral-800 shadow-sm shadow-neutral-900/10",
  secondary:
    "bg-white text-neutral-900 border border-neutral-200 hover:bg-neutral-100",
};

const sizeClasses: Record<ButtonSize, string> = {
  md: "px-5 py-2.5 text-base",
  sm: "px-4 py-2 text-sm",
};

export function Button({
  className,
  variant = "primary",
  size = "md",
  render,
  ...props
}: ButtonProps) {
  const typeValue: React.ButtonHTMLAttributes<HTMLButtonElement>["type"] =
    render ? undefined : "button";
  const classes = [
    "inline-flex items-center justify-center gap-1.5 rounded-full font-[450] transition-colors",
    sizeClasses[size],
    variantClasses[variant],
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return useRender({
    defaultTagName: "button",
    props: mergeProps<"button">({ className: classes, type: typeValue }, props),
    render,
  });
}
