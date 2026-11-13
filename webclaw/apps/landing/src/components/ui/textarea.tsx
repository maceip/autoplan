import { mergeProps } from "@base-ui/react/merge-props";
import { useRender } from "@base-ui/react/use-render";

type TextareaProps = useRender.ComponentProps<"textarea">;

export function Textarea({ className, render, ...props }: TextareaProps) {
  const classes = [
    "w-full min-h-[120px] rounded-xl border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-900",
    "placeholder:text-neutral-400 focus:outline-none focus:ring-2 focus:ring-neutral-900/10",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return useRender({
    defaultTagName: "textarea",
    props: mergeProps<"textarea">({ className: classes }, props),
    render,
  });
}
