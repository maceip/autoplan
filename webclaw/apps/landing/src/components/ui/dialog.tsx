import { Dialog as DialogPrimitive } from "@base-ui/react/dialog";
import type * as React from "react";

type DialogRootProps = React.ComponentProps<typeof DialogPrimitive.Root>;

function DialogRoot({ children, ...props }: DialogRootProps) {
  return <DialogPrimitive.Root {...props}>{children}</DialogPrimitive.Root>;
}

type DialogTriggerProps = React.ComponentProps<typeof DialogPrimitive.Trigger>;

function DialogTrigger({ className, ...props }: DialogTriggerProps) {
  return <DialogPrimitive.Trigger className={className} {...props} />;
}

type DialogContentProps = React.ComponentProps<typeof DialogPrimitive.Popup>;

function DialogContent({ className, ...props }: DialogContentProps) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Backdrop className="fixed inset-0 bg-neutral-900/30" />
      <DialogPrimitive.Popup
        className={
          "fixed left-1/2 top-1/2 w-full max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-neutral-200 bg-white p-6 shadow-xl " +
          (className ?? "")
        }
        {...props}
      />
    </DialogPrimitive.Portal>
  );
}

type DialogTitleProps = React.ComponentProps<typeof DialogPrimitive.Title>;

function DialogTitle({ className, ...props }: DialogTitleProps) {
  return (
    <DialogPrimitive.Title
      className={"text-lg font-[450] text-neutral-900 " + (className ?? "")}
      {...props}
    />
  );
}

type DialogDescriptionProps = React.ComponentProps<
  typeof DialogPrimitive.Description
>;

function DialogDescription({ className, ...props }: DialogDescriptionProps) {
  return (
    <DialogPrimitive.Description
      className={"text-sm text-neutral-500 " + (className ?? "")}
      {...props}
    />
  );
}

type DialogCloseProps = React.ComponentProps<typeof DialogPrimitive.Close>;

function DialogClose({ className, ...props }: DialogCloseProps) {
  return (
    <DialogPrimitive.Close
      className={
        "absolute right-4 top-4 inline-flex size-8 items-center justify-center rounded-full text-neutral-500 hover:bg-neutral-100 " +
        (className ?? "")
      }
      {...props}
    />
  );
}

export {
  DialogRoot,
  DialogTrigger,
  DialogContent,
  DialogTitle,
  DialogDescription,
  DialogClose,
};
