import type { ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export function Button({ className, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center rounded-full border border-ink/15 bg-ink px-4 py-2 text-sm font-medium text-paper transition hover:-translate-y-0.5 hover:bg-pine disabled:cursor-not-allowed disabled:opacity-60",
        className,
      )}
      {...props}
    />
  );
}
