import type { ComponentProps } from "react";

type IconProps = Omit<ComponentProps<"svg">, "children">;

export function GraphIcon(props: IconProps) {
  return (
    <svg
      fill="none"
      focusable="false"
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
      {...props}
    >
      <circle cx="6" cy="7" r="2.25" />
      <circle cx="18" cy="6" r="2.25" />
      <circle cx="13" cy="18" r="2.25" />
      <path d="m8.1 7 7.7-.8M7.4 8.8l4.2 7.1m5-7.9-2.5 7.8" />
    </svg>
  );
}

export function PlusIcon(props: IconProps) {
  return (
    <svg
      fill="none"
      focusable="false"
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
      {...props}
    >
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}