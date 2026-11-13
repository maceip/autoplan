import { Select as SelectPrimitive } from "@base-ui/react/select";

type SelectOption = {
  value: string;
  label: string;
};

type SelectProps = {
  value?: string;
  defaultValue?: string;
  placeholder?: string;
  options: Array<SelectOption>;
  onValueChange?: (value: string | null) => void;
  className?: string;
  name?: string;
};

export function Select({
  value,
  defaultValue,
  placeholder = "Select an option",
  options,
  onValueChange,
  className,
  name,
}: SelectProps) {
  return (
    <SelectPrimitive.Root
      value={value}
      defaultValue={defaultValue}
      onValueChange={onValueChange}
      name={name}
    >
      <SelectPrimitive.Trigger
        className={[
          "flex w-full items-center justify-between rounded-xl border border-neutral-200",
          "bg-white px-3 py-2 text-sm text-neutral-900 transition-colors",
          "focus:outline-none focus:ring-2 focus:ring-neutral-900/10",
          className,
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <SelectPrimitive.Value
          placeholder={placeholder}
          className="text-neutral-900 data-placeholder:text-neutral-400"
        />
        <SelectPrimitive.Icon className="text-neutral-400">
          <svg
            viewBox="0 0 20 20"
            aria-hidden="true"
            className="size-4"
            fill="none"
          >
            <path
              d="M6 8l4 4 4-4"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>

      <SelectPrimitive.Portal>
        <SelectPrimitive.Positioner sideOffset={6}>
          <SelectPrimitive.Popup className="min-w-[12rem] rounded-xl border border-neutral-200 bg-white p-1 text-sm text-neutral-900 shadow-lg">
            {options.map((option) => (
              <SelectPrimitive.Item
                key={option.value}
                value={option.value}
                className="flex w-full items-center rounded-lg px-2 py-1.5 outline-none hover:bg-neutral-100 data-highlighted:bg-neutral-100"
              >
                <SelectPrimitive.ItemText>
                  {option.label}
                </SelectPrimitive.ItemText>
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Popup>
        </SelectPrimitive.Positioner>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}
